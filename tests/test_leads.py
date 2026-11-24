"""Prove delle fasi 2-4 con dati finti (nessuna rete, nessuna spesa):
ricerca Google, sito, costi e tetti di spesa, analisi, messaggi, giro completo, schede e pulsanti."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote

import httpx
import pytest

from app.ai.client import AIError, BudgetExceeded, ClaudeJSON, cost_eur
from app.ai.guard import allowed_numbers, check_messages
from app.ai.prompts import ANALYSIS_SCHEMA, MESSAGE_SCHEMA, analysis_system, message_system
from app.bot import cards, handlers, leads
from app.config import Config, ConfigError
from app.db.memory import InMemoryRepository
from app.domain.dedupe import listing_fingerprints, normalize_listing_url
from app.domain.models import Property
from app.domain.radar import cells_in_circle
from app.domain.shifts import on_shift
from app.integrations.google_places import PlacesClient, PlacesError, SearchResult, parse_place
from app.integrations.website import check_website, safe_url
from app.services.analysis import AnalysisService
from app.services.messages import MessageService
from app.services.radar import RadarService
from app.services.rounds import RoundService, contactable

from .fakes import FakeMessage, World

NOW = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
ABETONE = (44.1425, 10.6633)
SENDER = "Matteo D'Amico"
ALL_DAY = {d: [["00:00", "23:59"]] for d in ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]}


# ── Dati finti ───────────────────────────────────────────────
def google_place(pid: str, name: str, phone: str | None = "+39 333 123 4567", primary: str = "bed_and_breakfast",
                 status: str = "OPERATIONAL", website: str | None = None) -> dict[str, Any]:
    return {
        "id": pid,
        "displayName": {"text": name},
        "formattedAddress": f"Via {name} 1, 51024 Abetone PT, Italia",
        "location": {"latitude": 44.14, "longitude": 10.66},
        "types": [primary, "lodging"],
        "primaryType": primary,
        "businessStatus": status,
        "internationalPhoneNumber": phone,
        "websiteUri": website,
        "googleMapsUri": f"https://maps.google.com/?cid={pid}",
        "rating": 4.2,
        "userRatingCount": 37,
        "reviews": [
            {
                "rating": 3,
                "publishTime": "2026-09-14T10:00:00Z",
                "text": {"text": "Posizione ottima ma check-in in ritardo di un'ora."},
                "authorAttribution": {"displayName": "Mario Rossi", "uri": "https://maps.google.com/contrib/1"},
            }
        ],
    }


def analysis_data(score: int = 80, exclude: bool = False) -> dict[str, Any]:
    return {
        "nome_dal_testo": "",
        "profilo": {"tipo": "b&b", "zona": "Abetone", "camere_o_posti": "non noto", "canali_noti": ["google"],
                    "ha_sito": False, "gestore_probabile": "privato"},
        "recensioni": {"voto_medio": 4.2, "numero_totale": 37, "lette": 5, "andamento": "non_valutabile",
                       "andamento_spiegazione": "date insufficienti",
                       "temi_negativi": [{"tema": "check-in", "volte": 2, "su_quante": 5, "sintesi": "attese all'arrivo"}],
                       "temi_positivi": ["posizione"], "risposte_proprietario": "non_valutabile"},
        "annuncio": {"disponibile": False, "foto": "non noto", "descrizione": "non noto", "servizi": "non noto",
                     "self_checkin": "non_noto", "cin_visibile": "non_noto"},
        "segnali_opportunita": [{"segnale": "check-in criticato", "base": "2 recensioni su 5 lette"}],
        "esclusione": {"escludi": exclude, "motivo": "gestita_da_altri" if exclude else "nessuno",
                       "spiegazione": "host aziendale" if exclude else ""},
        "punteggio": score,
        "motivi": ["+ check-in criticato in 2 recensioni su 5 lette", "+ nessun sito proprio"],
        "dati_mancanti": ["camere"],
        "sintesi": "Struttura ben posizionata, qualche problema all'arrivo degli ospiti.",
    }


GOOD_WHATSAPP = (
    "Buongiorno, sono Matteo di CHECK-iO: ci occupiamo di gestione di affitti brevi (check-io.it).\n"
    "Ho trovato la sua struttura su Google Maps: gli ospiti lodano la posizione, ma 2 delle 5 recensioni che ho letto "
    "parlano di attese al check-in.\n"
    "Con noi il check-in si fa in self check-in o con una persona sul posto anche la sera.\n"
    "Le farebbe piacere ricevere un'analisi gratuita della sua struttura?\n"
    "Se preferisce non essere ricontattato basta scrivermelo e non la ricontatterò. Matteo"
)
GOOD_EMAIL_BODY = (
    "Buongiorno,\n"
    "sono Matteo di CHECK-iO, ci occupiamo di gestione di affitti brevi (check-io.it).\n"
    "Ho trovato la sua struttura su Google Maps e ho letto le recensioni pubbliche.\n"
    "Gli ospiti apprezzano la posizione; 2 recensioni su 5 parlano di attese al check-in.\n"
    "Gestiamo check-in, pulizie, assistenza agli ospiti 24/7 e adempimenti come Alloggiati Web e tassa di soggiorno.\n"
    "Le farebbe piacere un'analisi gratuita della sua struttura?\n"
    "Se preferisce non essere ricontattato, mi basta una risposta e non la ricontatterò.\n"
    "Matteo D'Amico — CHECK-iO, check-io.it"
)


def good_messages() -> dict[str, Any]:
    return {
        "dettaglio_usato": "2 recensioni su 5 parlano di attese al check-in",
        "whatsapp": GOOD_WHATSAPP,
        "email": {"oggetto": "La sua struttura all'Abetone", "corpo": GOOD_EMAIL_BODY},
        "telefono": {
            "apertura": "Buongiorno, sono Matteo di CHECK-iO, la chiamo per la sua struttura all'Abetone.",
            "domande": ["Come gestisce oggi gli arrivi serali?", "Chi si occupa delle pulizie?"],
            "obiezioni": [
                {"obiezione": "ci_penso_io", "risposta": "Capisco, molti proprietari partono così."},
                {"obiezione": "ho_gia_provato_agenzia", "risposta": "Ci racconti cosa non ha funzionato."},
                {"obiezione": "non_voglio_dare_le_chiavi", "risposta": "Esiste il self check-in."},
                {"obiezione": "quanto_costa", "risposta": "Commissione indicativa tra 10 e 15%, definita per immobile."},
            ],
        },
    }


class FakeAnthropic:
    """Finto client Claude: risponde secondo lo schema richiesto e registra le richieste."""

    def __init__(self, analysis: dict | None = None, messages: list[dict] | None = None, stop_reason: str = "end_turn"):
        self.analysis = analysis or analysis_data()
        self.messages_queue = list(messages or [])
        self.stop_reason = stop_reason
        self.requests: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        schema = kwargs["output_config"]["format"]["schema"]
        if "segnali_opportunita" in schema["properties"]:
            data = self.analysis
        else:
            data = self.messages_queue.pop(0) if self.messages_queue else good_messages()
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(data, ensure_ascii=False))],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=500, cache_creation_input_tokens=0, cache_read_input_tokens=0),
            stop_reason=self.stop_reason,
            model=kwargs["model"],
            _request_id="req_prova",
        )


class FakePlaces:
    def __init__(self, places: list[dict[str, Any]], pages: int = 1, fail: bool = False):
        self.places = places
        self.pages = pages
        self.fail = fail
        self.calls: list[tuple[str, tuple]] = []

    async def search(self, query: str, bounds: tuple, max_pages: int = 3) -> SearchResult:
        self.calls.append((query, bounds))
        self.max_pages_seen = max_pages
        if self.fail:
            raise PlacesError("Google ha risposto 403: API key not valid")
        return SearchResult([parse_place(p) for p in self.places], min(self.pages, max_pages))

    async def details(self, place_id: str):
        return parse_place(next(p for p in self.places if p["id"] == place_id))


class FakeNotifier:
    def __init__(self) -> None:
        self.cards: list[tuple[str, Property]] = []
        self.summaries: list[str] = []

    async def send_card(self, member, prop):
        self.cards.append((member.name, prop))
        return (member.telegram_chat_id, 100 + len(self.cards))

    async def notify_owners(self, text: str) -> None:
        self.summaries.append(text)


async def make_repo(**settings: Any) -> tuple[InMemoryRepository, Any]:
    repo = InMemoryRepository()
    repo.province = {"047": cells_in_circle(*ABETONE, 3)}
    defaults = dict(
        zones=[{"tipo": "provincia", "codice": "047", "nome": "Pistoia", "attiva": True}],
        search_queries=["casa vacanze"],
        searches_per_run=1,
        cards_per_run=5,
        min_score=60,
    )
    repo.change_settings(**{**defaults, **settings})
    member = await repo.create_member(SENDER, "titolare", ALL_DAY)
    member = await repo.link_member_directly(member.id, 1001, 1001, "matteo")
    return repo, member


def make_round(repo, places, anthropic=None, price: Decimal | None = Decimal("40"), notifier=None, pages_per_search=1):
    notifier = notifier or FakeNotifier()
    analysis = messages = None
    if anthropic is not None:
        ai = ClaudeJSON(repo, anthropic, model="claude-opus-5-5", effort="medium", eur_per_usd=Decimal(1), clock=lambda: NOW)
        analysis, messages = AnalysisService(repo, ai), MessageService(repo, ai)
    service = RoundService(
        repo, RadarService(repo), notifier, analysis=analysis, messages=messages, places=places, http=None,
        search_price_usd_per_1000=price, eur_per_usd=Decimal(1), timezone=__import__("zoneinfo").ZoneInfo("Europe/Rome"),
        clock=lambda: NOW, pages_per_search=pages_per_search,
    )
    return service, notifier


# ── Google Places ────────────────────────────────────────────
async def test_ricerca_google_nella_cella_con_pagine_e_senza_nomi_degli_ospiti():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        if "pageToken" not in body:
            return httpx.Response(200, json={"places": [google_place("g1", "Baita")], "nextPageToken": "t2"})
        return httpx.Response(200, json={"places": [google_place("g2", "Hotel Neve", primary="hotel")]})

    client = PlacesClient("chiave-finta", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = await client.search("casa vacanze", (44.1, 10.6, 44.145, 10.6625))
    assert result.pages == 2 and len(result.places) == 2
    first = json.loads(seen[0].content)
    assert first["locationRestriction"]["rectangle"]["low"] == {"latitude": 44.1, "longitude": 10.6}
    assert first["pageSize"] == 20 and first["languageCode"] == "it"
    assert "places.reviews" in seen[0].headers["X-Goog-FieldMask"] and seen[0].headers["X-Goog-Api-Key"] == "chiave-finta"
    baita, hotel = result.places
    assert baita.exclusion is None and hotel.exclusion == "hotel"
    assert baita.candidate.property_type == "b&b" and baita.candidate.ratings["google"] == {"voto": 4.2, "recensioni": 37}
    assert baita.reviews == [{"voto": 3, "mese": "2026-09", "testo": "Posizione ottima ma check-in in ritardo di un'ora."}]
    assert "Mario Rossi" not in json.dumps(baita.reviews)


async def test_google_errori_chiuse_e_annunci_al_posto_del_sito():
    closed = parse_place(google_place("g3", "Chiusa", status="CLOSED_PERMANENTLY"))
    assert closed.exclusion == "chiusa"
    booking = parse_place(google_place("g4", "Casa", website="https://www.booking.com/hotel/it/casa.html"))
    assert booking.candidate.website is None and booking.candidate.listing_urls["booking"].startswith("https://www.booking")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "API key not valid"}})

    client = PlacesClient("segreta", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(PlacesError) as err:
        await client.search("b&b", (44, 10, 44.04, 10.06))
    assert "403" in str(err.value) and "segreta" not in str(err.value)


# ── Sito della struttura ─────────────────────────────────────
async def test_sito_email_cin_portali_e_pagina_contatti():
    pages = {
        "https://baita.example.it/": '<a href="/contatti">Contatti</a> <a href="https://www.airbnb.it/rooms/123?x=1">Airbnb</a>',
        "https://baita.example.it/contatti": 'Scrivici: <a href="mailto:info@baita-neve.it">info@baita-neve.it</a> '
        "CIN IT047023C2ABCDEFGH <a href='https://wa.me/393331234567'>WhatsApp</a> logo@2x.png",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        html = pages.get(str(request.url))
        return httpx.Response(200, text=html, headers={"content-type": "text/html"}) if html else httpx.Response(404)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    site = await check_website("https://baita.example.it/", http)
    assert site["letto"] and site["pagine"] == 2
    assert site["email"] == ["info@baita-neve.it"]
    assert site["cin"] == ["IT047023C2ABCDEFGH"]
    assert site["portali"] == {"airbnb": "https://www.airbnb.it/rooms/123"}
    assert site["whatsapp"] is True


async def test_i_portali_e_gli_indirizzi_interni_non_si_aprono():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - non deve essere chiamato
        raise AssertionError("non doveva aprire il sito")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert "portale" in (await check_website("https://www.booking.com/hotel/it/x.html", http))["errore"]
    assert (await check_website("http://127.0.0.1/admin", http))["errore"] == "indirizzo non valido"
    assert not safe_url("http://localhost/") and not safe_url("ftp://sito.it") and safe_url("https://sito.it/")


# ── Claude: costi, tetto di spesa, risposte ──────────────────
async def test_costo_registrato_e_richiesta_con_json_strutturato():
    repo, _ = await make_repo()
    fake = FakeAnthropic()
    ai = ClaudeJSON(repo, fake, model="claude-opus-5-5", effort="medium", eur_per_usd=Decimal("0.9"), clock=lambda: NOW)
    result = await ai.ask(purpose="analisi", system="s", prompt="p", schema=ANALYSIS_SCHEMA, property_id="x")
    # 1000 token in × 4 $ + 500 token out × 20 $ = 0,014 $ → × 0,9 = 0,0126 €
    assert result.cost_eur == Decimal("0.01260")
    assert repo.ai_usage[0]["cost_eur"] == Decimal("0.01260") and repo.ai_usage[0]["request_id"] == "req_prova"
    request = fake.requests[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}}
    assert request["fallbacks"] == "default" and request["betas"] == ["server-side-fallback-2026-07-01"]
    assert "temperature" not in request and "thinking" not in request


async def test_tetto_di_spesa_ai_blocca_prima_di_chiamare():
    repo, _ = await make_repo(monthly_ai_budget_eur=Decimal("0.01"))
    fake = FakeAnthropic()
    ai = ClaudeJSON(repo, fake, model="claude-opus-5-5", effort="medium", eur_per_usd=Decimal(1), clock=lambda: NOW)
    await ai.ask(purpose="analisi", system="s", prompt="p", schema=ANALYSIS_SCHEMA)  # 0,014 € > tetto
    with pytest.raises(BudgetExceeded):
        await ai.ask(purpose="analisi", system="s", prompt="p", schema=ANALYSIS_SCHEMA)
    assert len(fake.requests) == 1


async def test_rifiuto_di_claude_e_modello_sconosciuto():
    repo, _ = await make_repo()
    ai = ClaudeJSON(repo, FakeAnthropic(stop_reason="refusal"), model="claude-opus-5-5", effort="medium",
                    eur_per_usd=Decimal(1), clock=lambda: NOW)
    with pytest.raises(AIError):
        await ai.ask(purpose="analisi", system="s", prompt="p", schema=ANALYSIS_SCHEMA)
    assert len(repo.ai_usage) == 1  # la spesa si registra comunque
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=0)
    assert cost_eur("modello-nuovo", usage, Decimal(1)) == Decimal("8.00000")  # prezzo più alto, per prudenza


def test_istruzioni_contengono_i_fatti_confermati_e_le_regole():
    system = analysis_system()
    assert "niente di inventato" in system and "Octorate" in system and "al massimo 5 recensioni" in system
    msg = message_system("B", SENDER)
    assert "chiacchierata di 10 minuti" in msg and SENDER in msg and "Vietato" in msg
    assert "come dire no" in msg and "Google Maps" in msg
    for schema in (ANALYSIS_SCHEMA, MESSAGE_SCHEMA):
        stack = [schema]
        while stack:  # ogni oggetto ha additionalProperties false e tutti i campi obbligatori
            node = stack.pop()
            if node.get("type") == "object":
                assert node["additionalProperties"] is False and set(node["required"]) == set(node["properties"])
                stack.extend(node["properties"].values())
            stack.extend(node.get("anyOf", []))
            if "items" in node:
                stack.append(node["items"])


# ── Controlli sui messaggi ───────────────────────────────────
def test_controlli_messaggio_buono_e_cattivo():
    allowed = allowed_numbers(analysis_data(), {"scheda_google": {"voto": 4.2, "recensioni": 37}})
    assert check_messages(good_messages(), sender=SENDER, allowed=allowed) == []
    bad = good_messages()
    bad["whatsapp"] = "Salve! Con noi guadagni il 30% in più, garantito. Commissione 15%.\nChiamaci."
    problems = check_messages(bad, sender=SENDER, allowed=allowed)
    joined = " ".join(problems)
    for expected in ("righe", "CHECK-iO", "Google", "come dire no", "nome di chi scrive", "percentuali",
                     "garantit", "commission", "30"):
        assert expected in joined, expected


# ── Analisi ──────────────────────────────────────────────────
async def _new_property(repo, phone="+39 333 123 4567") -> Property:
    from app.domain.dedupe import Candidate, fingerprints

    candidate = Candidate(name="Baita", address="Via Baita 1, Abetone", google_place_id="g1", phone=phone,
                          ratings={"google": {"voto": 4.2, "recensioni": 37}})
    pid = await repo.insert_property(candidate, fingerprints(candidate), cell="980_170", provincia="047",
                                     zone="Pistoia", query="b&b")
    return await repo.get_property(pid)


async def test_analisi_senza_contatti_scartata_senza_spendere():
    repo, _ = await make_repo()
    fake = FakeAnthropic()
    ai = ClaudeJSON(repo, fake, model="claude-opus-5-5", effort="medium", eur_per_usd=Decimal(1), clock=lambda: NOW)
    prop = await _new_property(repo, phone=None)
    result = await AnalysisService(repo, ai).analyze(prop, [])
    assert result.status == "scartato" and result.discard_reason == "senza_contatti" and fake.requests == []


async def test_analisi_esclusione_gestita_da_altri():
    repo, _ = await make_repo()
    ai = ClaudeJSON(repo, FakeAnthropic(analysis=analysis_data(exclude=True)), model="claude-opus-5-5",
                    effort="medium", eur_per_usd=Decimal(1), clock=lambda: NOW)
    result = await AnalysisService(repo, ai).analyze(await _new_property(repo), [])
    assert result.status == "scartato" and result.discard_reason == "gestita_da_altri" and result.score == 0
    assert any(e["event_type"] == "esclusa" for e in repo.events)


async def test_analisi_buona_salva_punteggio_motivi_e_tipo_di_gestore():
    repo, _ = await make_repo()
    fake = FakeAnthropic(analysis=analysis_data(score=140))
    ai = ClaudeJSON(repo, fake, model="claude-opus-5-5", effort="medium", eur_per_usd=Decimal(1), clock=lambda: NOW)
    reviews = [{"voto": 3, "mese": "2026-09", "testo": "check-in in ritardo"}]
    result = await AnalysisService(repo, ai).analyze(await _new_property(repo), reviews)
    assert result.status == "analizzato" and result.score == 100 and result.owner_type == "privato"
    assert result.score_reasons[0].startswith("+ check-in")
    prompt = fake.requests[0]["messages"][0]["content"]
    assert "check-in in ritardo" in prompt and "al massimo 5 recensioni" in prompt
    assert any(e["event_type"] == "analizzata" for e in repo.events)


# ── Messaggi ─────────────────────────────────────────────────
async def test_messaggi_corretti_al_secondo_tentativo_e_versione_registrata():
    repo, _ = await make_repo()
    bad = good_messages()
    bad["whatsapp"] = "Ciao! Ti garantiamo il 30% in più."
    fake = FakeAnthropic(messages=[bad, good_messages()])
    ai = ClaudeJSON(repo, fake, model="claude-opus-5-5", effort="medium", eur_per_usd=Decimal(1), clock=lambda: NOW)
    prop = await AnalysisService(repo, ai).analyze(await _new_property(repo), [])
    service = MessageService(repo, ai)
    saved = await service.write(prop, SENDER, variant="A")
    assert saved["whatsapp"] == GOOD_WHATSAPP and saved["da_ricontrollare"] == []
    assert saved["variante"] == "A" and saved["mittente"] == SENDER
    retry_prompt = fake.requests[-1]["messages"][0]["content"]
    assert "non rispettava queste regole" in retry_prompt and "percentuali" in retry_prompt
    assert "analisi gratuita" in fake.requests[-1]["system"]
    stored = await repo.get_property(prop.id)
    assert stored.message_variant == "A" and stored.messages["whatsapp"] == GOOD_WHATSAPP


# ── Giro completo ────────────────────────────────────────────
async def test_giro_completo_ricerca_analisi_schede_e_riepilogo():
    repo, member = await make_repo()
    places = FakePlaces([
        google_place("g1", "Baita"),
        google_place("g2", "Rifugio", phone="+39 0573 123456"),
        google_place("g3", "Hotel Neve", phone="+39 0573 999999", primary="hotel"),
    ])
    fake = FakeAnthropic()
    service, notifier = make_round(repo, places, fake)
    report = await service.run("prova")
    assert report.searches == 1 and report.pages == 1 and report.results == 3
    assert report.new == 2 and report.excluded == 1 and report.analyzed == 2 and report.proposed == 2
    assert report.search_cost == Decimal("0.04")  # 1 pagina × 40 $ / 1000
    assert len(notifier.cards) == 2 and all(name == SENDER for name, _ in notifier.cards)
    statuses = {r["name"]: r["status"] for r in repo.properties.values()}
    assert statuses == {"Baita": "proposto", "Rifugio": "proposto"}
    assert all(r["telegram_message_id"] for r in repo.properties.values())
    assert "Mario Rossi" not in json.dumps([r["messages"] for r in fake.requests])
    run = next(iter(repo.search_runs.values()))
    assert run["status"] == "completata" and run["cost_eur"] == Decimal("0.04") and run["excluded"] == 1
    summary = notifier.summaries[0]
    assert "Ricerche Google: 1" in summary and "nuove 2" in summary and "Schede inviate 2" in summary
    assert "0,04 €" in summary

    # Secondo giro con gli stessi risultati: niente di nuovo, l'hotel resta escluso, nessuna nuova scheda
    report2 = await service.run("prova")
    assert report2.new == 0 and report2.known == 2 and report2.proposed == 0 and len(notifier.cards) == 2


async def test_giro_senza_prezzo_senza_chiavi_e_tetto_ricerche():
    repo, _ = await make_repo()
    service, notifier = make_round(repo, FakePlaces([google_place("g1", "Baita")]), None, price=None)
    report = await service.run("prova")
    assert report.searches == 0 and any("richieste Google al mese" in n for n in report.notes)
    assert any("ANTHROPIC_API_KEY" in n for n in report.notes)

    repo2, _ = await make_repo(monthly_search_budget_eur=Decimal("0.03"))
    places = FakePlaces([google_place("g1", "Baita")])
    service2, _ = make_round(repo2, places, FakeAnthropic())
    report2 = await service2.run("prova")  # una richiesta costa 0,04 € > 0,03 € di tetto
    assert places.calls == [] and any("Tetto di spesa" in n for n in report2.notes)


async def test_giro_errore_google_e_nessuno_di_turno():
    repo, member = await make_repo()
    service, _ = make_round(repo, FakePlaces([], fail=True), FakeAnthropic())
    report = await service.run("prova")
    run = next(iter(repo.search_runs.values()))
    assert run["status"] == "errore" and "403" in run["error"] and report.searches == 0

    repo2, member2 = await make_repo()
    repo2.members[member2.id] = repo2.members[member2.id].__class__(
        **{**repo2.members[member2.id].__dict__, "shifts": {}}
    )
    service2, notifier2 = make_round(repo2, FakePlaces([google_place("g1", "Baita")]), FakeAnthropic())
    report2 = await service2.run("prova")
    assert report2.proposed == 0 and report2.waiting == 1 and notifier2.cards == []
    assert any("Nessuno di turno" in n for n in report2.notes)


async def test_un_solo_giro_alla_volta():
    repo, _ = await make_repo()
    service, _ = make_round(repo, FakePlaces([]), None)
    async with service.lock:
        assert await service.run("prova") is None


def test_turni_e_canali():
    rome = __import__("zoneinfo").ZoneInfo("Europe/Rome")
    monday_10 = datetime(2026, 11, 23, 10, 0, tzinfo=rome)
    assert on_shift({"lun": [["09:00", "17:00"]]}, monday_10)
    assert not on_shift({"lun": [["09:00", "17:00"]]}, monday_10.replace(hour=17))
    assert not on_shift({"mar": [["09:00", "17:00"]]}, monday_10)
    p = Property(id="x", name="X", phone_normalized=None, email_normalized="a@b.it")
    assert contactable(p, "messaggi") and not contactable(p, "telefonate")


# ── Scheda Telegram ──────────────────────────────────────────
def _card_property(status: str = "proposto") -> Property:
    return Property(
        id="30000000-0000-4000-8000-000000000001", name="Baita <Neve> & Co", status=status,
        address="Via Baita 1", phone="+39 333 123 4567", phone_normalized="+393331234567", email="info@baita.it",
        email_normalized="info@baita.it", ratings={"google": {"voto": 4.2, "recensioni": 37}},
        listing_urls={"google_maps": "https://maps.google.com/?cid=1"}, analysis=analysis_data(), score=80,
        score_reasons=["+ check-in criticato in 2 recensioni su 5 lette"],
        messages={**good_messages(), "variante": "A", "da_ricontrollare": []}, message_variant="A",
    )


def test_scheda_testo_e_pulsanti():
    prop = _card_property()
    text = cards.card_text(prop, "misto", SENDER)
    assert "Baita &lt;Neve&gt; &amp; Co" in text and "Punteggio 80/100" in text and "check-in 2/5" in text
    assert "Messaggio WhatsApp" in text and "Versione A" in text and len(text) <= 4000
    labels = [b.text for row in cards.card_keyboard(prop).inline_keyboard for b in row]
    assert labels == ["✅ Approva", "✏️ Modifica", "❌ Scarta", "📧 Email", "📞 Telefonata",
                      "🏢 Già gestita da altri", "🚫 Non contattare"]
    approved = _card_property("approvato")
    buttons = [b for row in cards.card_keyboard(approved).inline_keyboard for b in row]
    wa = next(b for b in buttons if b.url)
    assert wa.url.startswith("https://wa.me/393331234567?text=") and "Buongiorno" in unquote(wa.url)
    assert "Telefonata in modalità" not in cards.card_text(prop, "telefonate")
    assert "Apertura della telefonata" in cards.card_text(prop, "telefonate")
    assert "Commissione" in cards.phone_text(prop) and "Registro delle opposizioni" in cards.phone_text(prop)
    assert "Oggetto:" in cards.email_text(prop)
    assert all(len(b.callback_data or "") <= 64 for b in buttons)


# ── Pulsanti e modifiche su Telegram ─────────────────────────
class FakeQuery:
    def __init__(self, data: str, chat_id: int) -> None:
        self.data = data
        self.message = SimpleNamespace(chat_id=chat_id)
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        self.answers.append((text, show_alert))


async def _world_with_card() -> tuple[World, str, Any]:
    world = World()
    owner = await world.repo.create_member(SENDER, "titolare", ALL_DAY)
    owner = await world.repo.link_member_directly(owner.id, 1001, 1001, "matteo")
    other = await world.repo.create_member("Luca", "commerciale", ALL_DAY)
    other = await world.repo.link_member_directly(other.id, 2002, 2002, "luca")
    prop = await _new_property(world.repo)
    await world.repo.update_property(
        prop.id, status="proposto", assigned_to=owner.id, analysis=analysis_data(), score=80,
        messages={**good_messages(), "variante": "A", "da_ricontrollare": []}, telegram_chat_id=1001,
        telegram_message_id=7,
    )
    return world, prop.id, other


async def press(world: World, user_id: int, data: str, user_data: dict | None = None) -> FakeQuery:
    query = FakeQuery(data, user_id)
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=user_id, username=f"u{user_id}", first_name="X"),
        effective_chat=SimpleNamespace(id=user_id, type="private"),
        effective_message=FakeMessage(),
    )
    context = SimpleNamespace(application=world.app, bot=world.bot, args=[], user_data=user_data if user_data is not None else {})
    await handlers.card_button(update, context)
    return query


async def test_pulsanti_approva_inviato_e_permessi():
    world, pid, other = await _world_with_card()
    query = await press(world, 2002, f"c:ok:{pid}")  # un altro commerciale non può
    assert query.answers[0][1] is True and (await world.repo.get_property(pid)).status == "proposto"
    await press(world, 1001, f"c:ok:{pid}")
    assert (await world.repo.get_property(pid)).status == "approvato"
    assert world.bot.edited and world.bot.edited[-1]["message_id"] == 7
    await press(world, 1001, f"c:sw:{pid}")
    prop = await world.repo.get_property(pid)
    assert prop.status == "contattato" and prop.channel == "whatsapp" and prop.contacted_at is not None
    events = [e["event_type"] for e in world.repo.events if e["property_id"] == pid]
    assert events[-2:] == ["approvata", "inviato"]
    closed = await press(world, 1001, f"c:no:{pid}")
    assert "già chiusa" in (closed.answers[0][0] or "")


async def test_pulsanti_non_contattare_e_gia_gestita():
    world, pid, _ = await _world_with_card()
    await press(world, 1001, f"c:oo:{pid}")
    prop = await world.repo.get_property(pid)
    assert prop.status == "perso" and prop.discard_reason == "opt_out"
    assert ("+393331234567", None) in world.repo.opt_out
    world2, pid2, _ = await _world_with_card()
    await press(world2, 1001, f"c:pm:{pid2}")
    assert (await world2.repo.get_property(pid2)).discard_reason == "gestita_da_altri"


async def test_modifica_del_testo_whatsapp():
    world, pid, _ = await _world_with_card()
    user_data: dict = {}
    await press(world, 1001, f"c:ew:{pid}", user_data)
    assert user_data["edit"] == {"property_id": pid, "channel": "whatsapp"}
    message = FakeMessage()
    message.text = "Testo nuovo scritto da me"
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1001, username="matteo", first_name="M"),
        effective_chat=SimpleNamespace(id=1001, type="private"),
        effective_message=message,
    )
    context = SimpleNamespace(application=world.app, bot=world.bot, args=[], user_data=user_data)
    await handlers.plain_text(update, context)
    prop = await world.repo.get_property(pid)
    assert prop.messages["whatsapp"] == "Testo nuovo scritto da me" and prop.message_edited
    assert "Testo salvato" in message.replies[0] and "edit" not in user_data
    assert "(modificato)" in world.bot.edited[-1]["text"]


async def test_email_e_telefonata_inviate_come_messaggi():
    world, pid, _ = await _world_with_card()
    await press(world, 1001, f"c:em:{pid}")
    await press(world, 1001, f"c:tel:{pid}")
    texts = [t for _, t in world.bot.sent[-2:]]
    assert "Oggetto:" in texts[0] and "<pre>" in texts[0]
    assert "Obiezioni" in texts[1]


# ── Giri programmati ─────────────────────────────────────────
async def test_il_giro_parte_all_ora_giusta_una_volta_e_non_in_pausa(monkeypatch):
    world = World()
    world.repo.state = world.repo.state.__class__(paused=False, mode="misto", version=2)
    started: list[str] = []

    class Rounds:
        lock = SimpleNamespace(locked=lambda: False)

        async def run(self, trigger: str) -> None:
            started.append(trigger)

    created = []
    world.app.bot_data["rounds"] = Rounds()
    world.app.create_task = lambda coro, name=None: created.append(coro)
    rome = __import__("zoneinfo").ZoneInfo("Europe/Rome")
    fixed = datetime(2026, 11, 23, 10, 0, 5, tzinfo=rome)  # lunedì 10:00

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(leads, "datetime", FixedDatetime)
    context = SimpleNamespace(application=world.app, bot=world.bot)
    await leads.tick(context)
    await leads.tick(context)  # stesso minuto: non riparte
    assert len(created) == 1
    for coro in created:
        await coro
    assert started == ["programmato"]

    world.repo.state = world.repo.state.__class__(paused=True, mode="misto", version=3)
    world.app.bot_data.pop("last_round")
    await leads.tick(context)
    assert len(created) == 1  # in pausa non parte


# ── Annunci incollati e configurazione ───────────────────────
def test_impronte_degli_annunci_incollati():
    a = normalize_listing_url("https://www.booking.com/hotel/it/casa-sole.it.html?aid=1&label=x")
    b = normalize_listing_url("https://booking.com/hotel/it/casa-sole.it.html/")
    assert a == b == "booking.com/hotel/it/casa-sole.it.html"
    prints = listing_fingerprints("https://www.airbnb.it/rooms/123", "it047023c2abcdefgh")
    assert [k for k, _ in prints] == ["annuncio", "cin"]


async def test_analizza_chiede_il_testo_se_manca():
    world = World()
    owner = await world.repo.create_member(SENDER, "titolare", ALL_DAY)
    await world.repo.link_member_directly(owner.id, 1001, 1001, "matteo")
    world.app.bot_data["analysis"] = object()
    message = FakeMessage()
    message.text = "/analizza https://www.booking.com/hotel/it/x.html"
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1001, username="matteo", first_name="M"),
        effective_chat=SimpleNamespace(id=1001, type="private"),
        effective_message=message,
    )
    await handlers.analizza(update, SimpleNamespace(application=world.app, bot=world.bot, args=[]))
    assert "non apre Booking" in message.replies[0] and world.repo.properties == {}


def test_configurazione_chiavi_facoltative():
    base = {"TELEGRAM_BOT_TOKEN": "t", "DATABASE_URL": "postgresql://x"}
    config = Config.from_env(base)
    assert config.google_maps_api_key is None and config.anthropic_api_key is None
    assert config.claude_model == "claude-opus-5-5" and config.eur_per_usd == Decimal(1)
    full = Config.from_env({**base, "GOOGLE_MAPS_API_KEY": "g", "GOOGLE_TEXT_SEARCH_USD_PER_1000": "40,5",
                            "ANTHROPIC_API_KEY": "a", "EUR_PER_USD": "0.9", "CLAUDE_EFFORT": "low"})
    assert full.google_search_usd_per_1000 == Decimal("40.5") and full.eur_per_usd == Decimal("0.9")
    assert full.claude_effort == "low"
    with pytest.raises(ConfigError):
        Config.from_env({**base, "GOOGLE_TEXT_SEARCH_USD_PER_1000": "gratis"})
    with pytest.raises(ConfigError):
        Config.from_env({**base, "CLAUDE_EFFORT": "altissimo"})



async def test_errori_di_claude_e_riserva_non_accettata():
    import anthropic

    repo, _ = await make_repo()
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    class Flaky(FakeAnthropic):
        async def create(self, **kwargs):
            if "fallbacks" in kwargs:
                self.requests.append(kwargs)
                raise anthropic.BadRequestError(
                    "fallbacks: not supported", response=httpx.Response(400, request=request), body=None
                )
            return await super().create(**kwargs)

    flaky = Flaky()
    ai = ClaudeJSON(repo, flaky, model="claude-opus-5-5", effort="medium", eur_per_usd=Decimal(1), clock=lambda: NOW)
    result = await ai.ask(purpose="analisi", system="s", prompt="p", schema=ANALYSIS_SCHEMA)
    assert result.data["punteggio"] == 80 and ai.use_fallbacks is False and "fallbacks" not in flaky.requests[-1]

    class Down(FakeAnthropic):
        async def create(self, **kwargs):
            raise anthropic.APIConnectionError(request=request)

    ai_down = ClaudeJSON(repo, Down(), model="claude-opus-5-5", effort="medium", eur_per_usd=Decimal(1), clock=lambda: NOW)
    with pytest.raises(AIError):
        await ai_down.ask(purpose="analisi", system="s", prompt="p", schema=ANALYSIS_SCHEMA)
    prop = await AnalysisService(repo, ai_down).analyze(await _new_property(repo), [])
    assert prop.status == "errore"


async def test_errore_imprevisto_nel_giro_finisce_nel_riepilogo():
    repo, _ = await make_repo()

    class Broken(FakePlaces):
        async def search(self, query, bounds, max_pages=3):
            raise RuntimeError("guasto")

    service, notifier = make_round(repo, Broken([]), None)
    report = await service.run("prova")
    assert any("errore imprevisto" in n for n in report.notes) and "errore imprevisto" in notifier.summaries[0]


# ── Verifica delle chiavi senza spendere ─────────────────────
def _google_error(code: int, status: str, reason: str | None = None, message: str = "errore") -> httpx.Response:
    details = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}] if reason else []
    return httpx.Response(code, json={"error": {"code": code, "message": message, "status": status, "details": details}})


@pytest.mark.parametrize(
    ("response", "ok", "expected"),
    [
        (_google_error(400, "INVALID_ARGUMENT", None, "Empty text_query."), True, "chiave valida"),
        (_google_error(400, "INVALID_ARGUMENT", "API_KEY_INVALID"), False, "non è valida"),
        (_google_error(403, "PERMISSION_DENIED", "SERVICE_DISABLED"), False, "Abilita"),
        (_google_error(403, "PERMISSION_DENIED", "BILLING_DISABLED"), False, "fatturazione"),
        (_google_error(403, "PERMISSION_DENIED", "API_KEY_SERVICE_BLOCKED"), False, "limitata ad altre API"),
        (_google_error(403, "PERMISSION_DENIED", "API_KEY_HTTP_REFERRER_BLOCKED"), False, "Nessuna"),
    ],
)
async def test_verifica_chiave_google(response, ok, expected):
    from app.services.keycheck import check_google

    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return response

    status = await check_google("chiave", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert status.ok is ok and expected in status.message
    body = json.loads(sent[0].content)
    assert body == {"textQuery": ""} and sent[0].headers["X-Goog-FieldMask"] == "places.id"  # nessuna ricerca vera


async def test_verifica_chiave_anthropic_e_registro():
    import anthropic

    from app.services.keycheck import check_anthropic, check_google, format_statuses, google_mode

    request = httpx.Request("GET", "https://api.anthropic.com/v1/models/claude-opus-5-5")

    class Models:
        def __init__(self, error=None):
            self.error = error
            self.calls = []

        async def retrieve(self, model_id):
            self.calls.append(model_id)
            if self.error:
                raise self.error
            return SimpleNamespace(id=model_id, display_name="Claude Opus 5.5")

    good = SimpleNamespace(models=Models())
    status = await check_anthropic(good, "claude-opus-5-5")
    assert status.ok and "Claude Opus 5.5" in status.message and good.models.calls == ["claude-opus-5-5"]
    bad = SimpleNamespace(models=Models(anthropic.AuthenticationError(
        "invalid x-api-key", response=httpx.Response(401, request=request), body=None)))
    assert "non è valida" in (await check_anthropic(bad, "claude-opus-5-5")).message
    missing = SimpleNamespace(models=Models(anthropic.NotFoundError(
        "not found", response=httpx.Response(404, request=request), body=None)))
    assert "non è disponibile" in (await check_anthropic(missing, "claude-opus-5-5")).message
    assert (await check_anthropic(None, "claude-opus-5-5")).ok is None
    assert (await check_google(None, httpx.AsyncClient())).ok is None

    world = World()
    owner = await world.repo.create_member(SENDER, "titolare", ALL_DAY)
    await world.repo.link_member_directly(owner.id, 1001, 1001, "matteo")

    def handler(request: httpx.Request) -> httpx.Response:
        return _google_error(400, "INVALID_ARGUMENT", None, "Empty text_query.")

    world.app.bot_data.update(
        config=Config.from_env({"TELEGRAM_BOT_TOKEN": "t", "DATABASE_URL": "postgresql://x", "GOOGLE_MAPS_API_KEY": "g"}),
        anthropic=good,
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    replies = await world.send(handlers.verifica, user_id=1001)
    assert "✅ Anthropic (Claude): chiave valida" in replies[1] and "✅ Google Maps: chiave valida" in replies[1]
    assert "Ricerca Google spenta" in replies[1]
    audit = world.repo.audit[-1]
    assert audit["action"] == "verifica_chiavi" and audit["details"]["Google Maps"]["ok"] is True
    assert audit["details"]["prezzo_google_impostato"] is False
    assert "al massimo 200 richieste" in format_statuses([], google_mode(False, 200))
    assert "spenta" in google_mode(False, 0) and "prezzo impostato" in google_mode(True, 0)


async def test_credito_anthropic_esaurito_messaggio_chiaro():
    import anthropic

    repo, _ = await make_repo()
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    class NoCredit(FakeAnthropic):
        async def create(self, **kwargs):
            raise anthropic.BadRequestError(
                "Your credit balance is too low to access the Anthropic API.",
                response=httpx.Response(400, request=request), body=None,
            )

    ai = ClaudeJSON(repo, NoCredit(), model="claude-opus-5-5", effort="medium", eur_per_usd=Decimal(1), clock=lambda: NOW)
    with pytest.raises(AIError) as err:
        await ai.ask(purpose="analisi", system="s", prompt="p", schema=ANALYSIS_SCHEMA)
    assert "Credito Anthropic esaurito" in str(err.value)



# ── Google gratis: limite di richieste al mese ───────────────
async def test_google_gratis_senza_prezzo_conta_le_richieste_e_si_ferma():
    repo, _ = await make_repo(google_monthly_requests=4, searches_per_run=3, search_queries=["casa vacanze", "b&b"])
    places = FakePlaces([google_place("g1", "Baita")], pages=2)
    service, notifier = make_round(repo, places, FakeAnthropic(), price=None, pages_per_search=3)
    report = await service.run("prova")
    # 1ª ricerca: 2 pagine (2/4) · 2ª: al massimo 2 pagine (4/4) · 3ª: ferma
    assert report.searches == 2 and report.pages == 4 and places.max_pages_seen == 2
    assert report.search_cost == Decimal(0) and report.google_requests == 4 and report.google_limit == 4
    assert any("Raggiunte le 4 richieste Google" in n for n in report.notes)
    assert "Richieste Google del mese: 4 su 4 (gratuite)" in notifier.summaries[0]
    assert await repo.month_google_requests(NOW - timedelta(days=1)) == 4

    report2 = await service.run("prova")  # mese già esaurito: nessuna richiesta
    assert report2.searches == 0 and len(places.calls) == 2


async def test_google_gratis_ultima_ricerca_limitata_alle_richieste_rimaste():
    repo, _ = await make_repo(google_monthly_requests=1)
    places = FakePlaces([google_place("g1", "Baita")], pages=3)
    service, _ = make_round(repo, places, FakeAnthropic(), price=None, pages_per_search=3)
    report = await service.run("prova")
    assert places.max_pages_seen == 1 and report.pages == 1 and report.google_requests == 1



async def test_una_ricerca_una_sola_richiesta_a_google():
    repo, _ = await make_repo(google_monthly_requests=1400, searches_per_run=15,
                              search_queries=["casa vacanze", "b&b", "affittacamere"])
    repo.province = {"047": cells_in_circle(*ABETONE, 10)}
    places = FakePlaces([google_place("g1", "Baita")], pages=3)
    service, notifier = make_round(repo, places, FakeAnthropic(), price=None)
    report = await service.run("prova")
    assert report.searches == 15 and report.pages == 15 and places.max_pages_seen == 1
    assert report.google_requests == 15 and "15 su 1400" in notifier.summaries[0]
