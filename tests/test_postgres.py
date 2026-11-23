"""Prove sul database Postgres vero (stesso schema di Supabase).

Si eseguono solo se è impostata TEST_DATABASE_ADMIN_URL, per esempio:
TEST_DATABASE_ADMIN_URL=postgresql://postgres@127.0.0.1:54329/postgres
Il database di prova viene creato e cancellato ogni volta.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from app.db.postgres import PostgresRepository, create_pool
from app.db.repository import AlreadyLinkedError
from app.domain.codes import hash_code
from app.domain.models import ROLE_OWNER, ROLE_SALES
from app.services.control import ControlService
from app.services.linking import LinkingService, LinkOutcome
from app.services.settings_watch import SettingsWatcher

ADMIN_URL = os.environ.get("TEST_DATABASE_ADMIN_URL")
MIGRATIONS = sorted((Path(__file__).parent.parent / "supabase" / "migrations").glob("*.sql"))
SUPABASE_STUB = Path(__file__).parent / "sql" / "supabase_stub.sql"
RLS_TEST = Path(__file__).parent.parent / "supabase" / "tests" / "rls_test.sql"

pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="TEST_DATABASE_ADMIN_URL non impostata")


@pytest.fixture
async def repo():
    name = f"checkio_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'create database "{name}"')
    url = ADMIN_URL.rsplit("/", 1)[0] + f"/{name}"
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(SUPABASE_STUB.read_text())
            for migration in MIGRATIONS:
                conn.execute(migration.read_text())
        pool = create_pool(url)
        await pool.open(wait=True)
        try:
            yield PostgresRepository(pool), url
        finally:
            await pool.close()
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'drop database "{name}" with (force)')


async def test_schema_impostazioni_e_stato_iniziali(repo):
    repository, _ = repo
    settings = await repository.get_settings()
    state = await repository.get_state()
    assert settings.min_score == 60 and settings.zones == [] and settings.version == 1
    assert state.paused is True and state.mode == "misto"


async def test_flusso_collegamento_completo(repo):
    repository, _ = repo
    linking = LinkingService(repository, owner_setup_code="codice-avvio-123456")
    result = await linking.redeem(
        "codice-avvio-123456", telegram_user_id=1, chat_id=1, username="tit", display_name="Titolare"
    )
    assert result.outcome is LinkOutcome.OWNER_CREATED and result.member.role == ROLE_OWNER
    again = await linking.redeem(
        "codice-avvio-123456", telegram_user_id=2, chat_id=2, username=None, display_name="Altro"
    )
    assert again.outcome is LinkOutcome.USED

    issued = await linking.issue_code(issuer=result.member, name="Matteo")
    assert issued.created and issued.member.role == ROLE_SALES
    linked = await linking.redeem(issued.code, telegram_user_id=2, chat_id=2, username="matteo", display_name="M")
    assert linked.outcome is LinkOutcome.LINKED and linked.member.telegram_user_id == 2
    reused = await linking.redeem(issued.code, telegram_user_id=3, chat_id=3, username=None, display_name="X")
    assert reused.outcome is LinkOutcome.USED

    members = await repository.list_members()
    assert [m.name for m in members] == ["Titolare", "Matteo"]
    assert members[1].shifts["lun"] == [["09:00", "17:00"]]


async def test_codici_scaduti_impronta_e_unico_account(repo):
    repository, url = repo
    owner = await repository.create_member("Titolare", ROLE_OWNER, {})
    giulia = await repository.create_member("Giulia", ROLE_SALES, {})
    await repository.link_member_directly(owner.id, 10, 10, None)
    await repository.create_link_code(giulia.id, hash_code("ABCD-EFGH"), datetime.now(UTC) - timedelta(1), owner.id)
    linking = LinkingService(repository, owner_setup_code=None)
    expired = await linking.redeem("abcd efgh", telegram_user_id=11, chat_id=11, username=None, display_name="G")
    assert expired.outcome is LinkOutcome.EXPIRED
    # nel database c'è solo l'impronta del codice, mai il codice in chiaro
    with psycopg.connect(url) as conn:
        stored = conn.execute("select code_hash from link_codes").fetchone()[0]
    assert stored == hash_code("ABCD-EFGH") and "ABCD" not in stored
    with pytest.raises(AlreadyLinkedError):
        await repository.link_member_directly(giulia.id, 10, 10, None)


async def test_stato_e_versione_rilevati_dal_controllo(repo):
    repository, url = repo
    owner = await repository.create_member("Titolare", ROLE_OWNER, {})
    watcher = SettingsWatcher(repository)
    await watcher.load()
    control = ControlService(repository)
    state, changed = await control.set_paused(owner, False)
    assert changed and state.paused is False and state.version == 2 and state.updated_by == "Titolare"
    _, changed = await control.set_paused(owner, False)
    assert changed is False
    watcher.acknowledge_state(state)
    # modifica fatta da fuori (gestionale / editor Supabase)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("update finder_settings set min_score = 80, updated_by = 'gestionale' where id = 1")
        conn.execute("update finder_settings set min_score = 80 where id = 1")  # nessun cambiamento reale
    messages = await watcher.check()
    assert len(messages) == 1 and "Punteggio minimo: 60 → 80" in messages[0] and "da gestionale" in messages[0]
    assert await watcher.check() == []
    await repository.add_audit(owner.id, owner.name, "telegram", "prova", {"ok": True})
    with psycopg.connect(url) as conn:
        assert conn.execute("select count(*) from audit_log").fetchone()[0] >= 2


async def test_sicurezza_per_righe_attiva_su_tutte_le_tabelle(repo):
    _, url = repo
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "select tablename from pg_tables where schemaname = 'public' and not rowsecurity"
        ).fetchall()
    assert rows == []


async def test_regole_di_accesso_del_gestionale(repo):
    """Esegue supabase/tests/rls_test.sql: ogni riga deve risultare superata."""
    _, url = repo
    with psycopg.connect(url, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute(RLS_TEST.read_text())
        results = None
        while True:
            if cur.description is not None:
                results = cur.fetchall()
            if not cur.nextset():
                break
    assert results and len(results) == 40
    failed = [name for name, ok in results if not ok]
    assert failed == []


async def test_il_bot_aggiorna_lo_stato_senza_account_web(repo):
    """Le modifiche del bot (senza utente web) non vengono attribuite al gestionale."""
    repository, url = repo
    state = await repository.update_state(paused=False, mode=None, updated_by="Bot Test")
    assert state.updated_by == "Bot Test"
    with psycopg.connect(url) as conn:
        assert conn.execute("select count(*) from audit_log where source = 'gestionale'").fetchone()[0] == 0


async def test_radar_e_memoria_storica_sul_database(repo):
    """Province vere, celle, impronte e pulizia: una struttura vista non torna mai come nuova."""
    import random
    from datetime import UTC, datetime, timedelta

    from app.domain.dedupe import Candidate
    from app.domain.radar import cell_id
    from app.services.radar import RadarService

    repository, url = repo
    now = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
    cells = await repository.province_cells(["047"])
    assert cell_id(44.1425, 10.6633) in cells["047"]  # l'Abetone è in provincia di Pistoia
    with psycopg.connect(url, autocommit=True) as conn:
        assert conn.execute("select count(*) from province").fetchone()[0] == 110
        conn.execute(
            """update finder_settings set zones = '[{"tipo":"provincia","codice":"047","nome":"Pistoia","attiva":true}]',
               search_queries = '{casa vacanze,B&B}' where id = 1"""
        )

    radar = RadarService(repository, random.Random(1))
    targets = await radar.next_targets(3, now)
    assert len(targets) == 3 and all(t.provincia == "047" and t.zone == "Pistoia" for t in targets)
    target = targets[0]

    baita = Candidate(
        name="Baita Neve", address="Via Brennero 1, Abetone", google_place_id="g-baita",
        phone="333 1234567", email="info@baita.it", ratings={"google": {"voto": 4.6, "recensioni": 80}},
    )
    first = await radar.record_results(target, [baita, Candidate(name="Rifugio", google_place_id="g-rifugio")], now)
    assert len(first.new_ids) == 2

    same_phone_other_listing = Candidate(name="Baita (nuovo annuncio)", google_place_id="g-altro", phone="+39 333 123 4567")
    again = await radar.record_results(target, [same_phone_other_listing], now + timedelta(hours=1))
    assert again.new_ids == [] and again.already_known == 1

    with psycopg.connect(url, autocommit=True) as conn:
        assert conn.execute("select count(*) from properties").fetchone()[0] == 2
        row = conn.execute(
            "select provincia, cell, search_query, times_seen, phone_normalized from properties where google_place_id = 'g-baita'"
        ).fetchone()
        assert row == ("047", target.cell, target.query, 2, "+393331234567")
        assert conn.execute("select count(*) from property_events where event_type = 'trovata'").fetchone()[0] == 2
        assert conn.execute(
            "select count(*) from property_fingerprints where kind = 'google' and hash ~ '^[0-9a-f]{64}$'"
        ).fetchone()[0] == 3  # anche la nuova scheda Google è ora legata alla Baita
        cell_row = conn.execute(
            "select searches, results_total, new_total, empty_streak, rest_until from search_cells where cell = %s and query = %s",
            (target.cell, target.query),
        ).fetchone()
        assert cell_row == (2, 3, 2, 1, None)

        # Conservazione: dati vecchi cancellati, impronte rimaste
        conn.execute("set session_replication_role = replica")  # senza trigger, per invecchiare le righe
        conn.execute("update properties set updated_at = now() - interval '2 years', last_seen_at = now() - interval '2 years'")
        conn.execute("set session_replication_role = origin")
    assert await repository.purge_expired() == 2
    with psycopg.connect(url) as conn:
        assert conn.execute("select count(*) from properties").fetchone()[0] == 0
        assert conn.execute("select count(*) from property_fingerprints where property_id is null").fetchone()[0] >= 5

    after_purge = await radar.record_results(targets[1], [baita], now + timedelta(days=800))
    assert after_purge.new_ids == [] and after_purge.already_known == 1


async def test_celle_delle_province_identiche_tra_database_e_mappa(repo):
    """Le celle scritte in forma compatta nella migrazione sono le stesse della mappa del gestionale."""
    import json

    _, url = repo
    data_dir = Path(__file__).parent.parent / "admin" / "src" / "data" / "italia" / "regioni"
    expected = {}
    for file in data_dir.glob("*.json"):
        for prov in json.loads(file.read_text())["province"]:
            expected[prov["codice"]] = prov["celle"]
    with psycopg.connect(url) as conn:
        rows = dict(conn.execute("select codice, celle from province").fetchall())
    assert len(expected) == len(rows) == 110
    assert sum(len(c) for c in rows.values()) == 14578
    assert {code: list(cells) for code, cells in rows.items()} == expected
