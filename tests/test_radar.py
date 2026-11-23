"""Prove del radar (celle e ordine di ricerca) e della memoria storica (niente doppioni)."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.db.memory import InMemoryRepository
from app.domain.dedupe import (
    Candidate,
    fingerprints,
    normalize_cin,
    normalize_email,
    normalize_name_address,
    normalize_phone,
)
from app.domain.radar import (
    CellMemory,
    ZoneRef,
    after_search,
    cell_bounds,
    cell_center,
    cell_id,
    cells_in_circle,
    distance_km,
    plan,
    province_codes,
    zone_cells,
)
from app.services.radar import RadarService

NOW = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
ABETONE = (44.1425, 10.6633)


# ── Griglia ──────────────────────────────────────────────────
def test_la_cella_contiene_il_punto_ed_e_di_circa_5_km():
    cell = cell_id(*ABETONE)
    south, west, north, east = cell_bounds(cell)
    assert south <= ABETONE[0] < north and west <= ABETONE[1] < east
    assert 4.5 < distance_km(south, west, north, west) < 5.5
    assert 4.5 < distance_km(south, west, south, east) < 5.5
    assert cell_id(*cell_center(cell)) == cell


def test_celle_del_cerchio():
    small = cells_in_circle(*ABETONE, 1)
    big = cells_in_circle(*ABETONE, 15)
    assert cell_id(*ABETONE) in small and len(small) <= 4
    assert set(small) <= set(big)
    assert 25 < len(big) < 80  # un cerchio di 15 km copre circa 700 km², cioè una trentina di celle
    assert all(distance_km(*ABETONE, *cell_center(c)) < 15 + 4 for c in big)


def test_zone_attive_province_e_cerchi_senza_doppioni():
    zones = [
        {"tipo": "provincia", "codice": "047", "nome": "Pistoia", "attiva": True},
        {"nome": "Abetone", "lat": ABETONE[0], "lng": ABETONE[1], "raggio_km": 3, "attiva": True},
        {"nome": "Spenta", "lat": 45.0, "lng": 9.0, "raggio_km": 10, "attiva": False},
        {"nome": "Incompleta", "raggio_km": 10},
    ]
    abetone_cells = cells_in_circle(*ABETONE, 3)
    province = {"047": [*abetone_cells[:2], "999_999"]}
    cells = zone_cells(zones, province)
    assert province_codes(zones) == ["047"]
    assert cells["999_999"] == ZoneRef("Pistoia", "047")
    assert cells[abetone_cells[0]] == ZoneRef("Pistoia", "047")  # già della provincia: conta una volta
    assert cells[abetone_cells[-1]] == ZoneRef("Abetone", None)
    assert not any(cell_id(45.0, 9.0) == c for c in cells)  # la zona spenta non si cerca


# ── Ordine di ricerca e riposo ───────────────────────────────
def test_prima_le_celle_mai_cercate_poi_le_piu_vecchie_e_salta_quelle_a_riposo():
    cells = {"1_1": ZoneRef("A"), "1_2": ZoneRef("A"), "1_3": ZoneRef("A")}
    memory = {
        ("1_1", "B&B"): CellMemory("1_1", "B&B", 1, NOW - timedelta(days=2)),
        ("1_2", "B&B"): CellMemory("1_2", "B&B", 1, NOW - timedelta(days=9)),
        ("1_3", "B&B"): CellMemory("1_3", "B&B", 3, NOW - timedelta(days=40), 2, rest_until=NOW + timedelta(days=5)),
    }
    targets = plan(cells, ["B&B", "casa vacanze"], memory, NOW, 10, random.Random(1))
    keys = [(t.cell, t.query) for t in targets]
    assert set(keys[:3]) == {("1_1", "casa vacanze"), ("1_2", "casa vacanze"), ("1_3", "casa vacanze")}
    assert keys[3:] == [("1_2", "B&B"), ("1_1", "B&B")]  # la più vecchia prima
    assert ("1_3", "B&B") not in keys  # a riposo
    assert len(plan(cells, ["B&B", "casa vacanze"], memory, NOW, 2)) == 2


def test_le_zone_si_alternano():
    cells = {f"1_{j}": ZoneRef("Grande") for j in range(20)} | {"9_9": ZoneRef("Piccola")}
    targets = plan(cells, ["B&B"], {}, NOW, 2, random.Random(3))
    assert {t.zone for t in targets} == {"Grande", "Piccola"}


def test_regola_del_riposo():
    first = after_search(None, "1_1", "B&B", results=12, new=4, now=NOW)
    assert (first.searches, first.empty_streak, first.rest_until) == (1, 0, None)
    second = after_search(first, "1_1", "B&B", results=12, new=0, now=NOW)
    assert second.empty_streak == 1 and second.rest_until is None
    third = after_search(second, "1_1", "B&B", results=12, new=0, now=NOW)
    assert third.rest_until == NOW + timedelta(days=30)
    fourth = after_search(third, "1_1", "B&B", results=12, new=0, now=NOW)
    assert fourth.rest_until == NOW + timedelta(days=90)
    back = after_search(fourth, "1_1", "B&B", results=12, new=1, now=NOW)
    assert back.empty_streak == 0 and back.rest_until is None and back.searches == 5


# ── Normalizzazione e impronte ───────────────────────────────
@pytest.mark.parametrize(
    "raw",
    ["+39 333 123 4567", "0039 3331234567", "333-1234567", "(+39) 333.123.4567", "39 333 1234567"],
)
def test_stesso_cellulare_scritto_in_modi_diversi(raw):
    assert normalize_phone(raw) == "+393331234567"


def test_numeri_fissi_esteri_e_non_validi():
    assert normalize_phone("0573 123456") == normalize_phone("+39 0573 123456") == "+390573123456"
    assert normalize_phone("+41 91 123 45 67") == "+41911234567"
    assert normalize_phone("123") is None and normalize_phone("") is None and normalize_phone(None) is None


def test_email_cin_nome_e_indirizzo():
    assert normalize_email(" Info@CasaSole.IT ") == normalize_email("mailto:info@casasole.it") == "info@casasole.it"
    assert normalize_email("non-una-email") is None
    assert normalize_cin("it047014c2-abcdefgh") == "IT047014C2ABCDEFGH" and normalize_cin("IT04") is None
    a = normalize_name_address("Casa Vacanze «Il Sole» & Neve", "Via dell'Abetone 12, 51024 Abetone PT, Italia")
    b = normalize_name_address("casa vacanze il sole e neve", "via dell abetone 12 51024 abetone pt")
    assert a == b and a is not None
    assert normalize_name_address("Solo nome", None) is None


def test_impronte_uguali_per_la_stessa_struttura_e_diverse_per_altre():
    one = Candidate(name="Baita Neve", address="Via Brennero 1, Abetone", google_place_id="g1", phone="333 1234567")
    same = Candidate(name="BAITA NEVE", address="via brennero 1 abetone", google_place_id="g2", phone="+393331234567")
    other = Candidate(name="Rifugio Lago", address="Via Lago 3, Abetone", google_place_id="g3", phone="333 7654321")
    assert set(fingerprints(one)) & set(fingerprints(same))
    assert not set(fingerprints(one)) & set(fingerprints(other))
    assert all(len(h) == 64 and "333" not in h for _, h in fingerprints(one))  # nessun dato in chiaro


# ── Servizio: la memoria storica in azione ───────────────────
@pytest.fixture
def repo() -> InMemoryRepository:
    repository = InMemoryRepository()
    repository.province = {"047": cells_in_circle(*ABETONE, 6)}
    repository.change_settings(
        zones=[{"tipo": "provincia", "codice": "047", "nome": "Pistoia", "attiva": True}],
        search_queries=["casa vacanze", "B&B"],
    )
    return repository


def _places(*names: str) -> list[Candidate]:
    return [
        Candidate(name=n, address=f"Via {n} 1, Abetone", google_place_id=f"g-{n}", phone=f"33300000{i:02d}")
        for i, n in enumerate(names)
    ]


async def test_una_struttura_gia_trovata_non_torna_come_nuova(repo):
    radar = RadarService(repo, random.Random(7))
    target = (await radar.next_targets(1, NOW))[0]
    assert target.provincia == "047" and target.zone == "Pistoia"

    first = await radar.record_results(target, _places("Baita", "Rifugio", "Chalet"), NOW)
    assert len(first.new_ids) == 3 and first.already_known == 0

    again = await radar.record_results(target, _places("Baita", "Rifugio", "Chalet", "Nuova"), NOW + timedelta(days=1))
    assert len(again.new_ids) == 1 and again.already_known == 3
    assert len(repo.properties) == 4
    assert repo.properties[first.new_ids[0]]["times_seen"] == 2


async def test_riconosciuta_anche_da_un_altra_scheda_con_lo_stesso_telefono(repo):
    radar = RadarService(repo)
    target = (await radar.next_targets(1, NOW))[0]
    await radar.record_results(target, [Candidate(name="Baita", google_place_id="g-1", phone="333 1112222")], NOW)
    other_listing = Candidate(name="Baita Abetone (nuovo annuncio)", google_place_id="g-99", phone="+39 333 111 2222")
    outcome = await radar.record_results(target, [other_listing], NOW)
    assert outcome.new_ids == [] and outcome.already_known == 1


async def test_impronte_nuove_si_aggiungono_alla_struttura_gia_nota(repo):
    radar = RadarService(repo)
    target = (await radar.next_targets(1, NOW))[0]
    first = await radar.record_results(target, [Candidate(name="Baita", google_place_id="g-1")], NOW)
    await radar.record_results(target, [Candidate(name="Baita", google_place_id="g-1", email="baita@example.it")], NOW)
    by_email_only = await radar.record_results(target, [Candidate(name="Altro nome", email="BAITA@example.it")], NOW)
    assert by_email_only.new_ids == [] and by_email_only.already_known == 1
    assert len(repo.properties) == 1 and first.new_ids


async def test_doppione_nella_stessa_ricerca_e_chi_ha_detto_no(repo):
    repo.opt_out.append(("+393339998888", None))
    radar = RadarService(repo)
    target = (await radar.next_targets(1, NOW))[0]
    places = [
        Candidate(name="Chalet", google_place_id="g-c"),
        Candidate(name="Chalet", google_place_id="g-c"),
        Candidate(name="Non contattare", google_place_id="g-x", phone="333 999 8888"),
        Candidate(name=""),
    ]
    outcome = await radar.record_results(target, places, NOW)
    assert len(outcome.new_ids) == 1 and outcome.already_known == 1
    assert outcome.opted_out == 1 and outcome.unidentifiable == 1


async def test_la_memoria_delle_celle_guida_il_radar(repo):
    radar = RadarService(repo, random.Random(2))
    all_targets = await radar.next_targets(1000, NOW)
    assert len(all_targets) == len(repo.province["047"]) * 2
    first = all_targets[0]
    await radar.record_results(first, [], NOW)
    await radar.record_results(first, [], NOW + timedelta(hours=1))  # due ricerche vuote: la cella riposa
    memory = repo.cell_memory[(first.cell, first.query)]
    assert memory.searches == 2 and memory.rest_until == NOW + timedelta(hours=1, days=30)
    later = await radar.next_targets(1000, NOW + timedelta(days=1))
    assert (first.cell, first.query) not in {(t.cell, t.query) for t in later}
    assert len(later) == len(all_targets) - 1
    after_rest = await radar.next_targets(1000, NOW + timedelta(days=31, hours=2))
    assert (after_rest[-1].cell, after_rest[-1].query) == (first.cell, first.query)  # torna, ma per ultima


async def test_zona_cerchio_prende_la_provincia_dalle_celle(repo):
    repo.change_settings(zones=[{"nome": "Abetone", "lat": ABETONE[0], "lng": ABETONE[1], "raggio_km": 2}])
    targets = await RadarService(repo).next_targets(3, NOW)
    assert targets and all(t.provincia == "047" and t.zone == "Abetone" for t in targets)


async def test_nessuna_zona_nessuna_ricerca(repo):
    repo.change_settings(zones=[replace_zone(z) for z in repo.settings.zones])
    assert await RadarService(repo).next_targets(5, NOW) == []


def replace_zone(zone: dict) -> dict:
    return {**zone, "attiva": False}


def test_bounds_del_target():
    target = plan({"10_20": ZoneRef("A")}, ["B&B"], {}, NOW, 1)[0]
    assert target.bounds == cell_bounds("10_20")
    assert replace(target, provincia="047").provincia == "047"
