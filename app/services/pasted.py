"""Annuncio incollato a mano (Booking, Airbnb, Trivago…): si trova la stessa struttura nei dati pubblici.

Il bot non apre i portali: lavora solo sul testo incollato dal commerciale. Da quel testo Claude ricava
nome e località; una ricerca Google (una richiesta, dentro il tetto del mese) trova la scheda pubblica
della struttura, da cui si prende il telefono. La scheda Telegram parte solo se c'è un cellulare.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from difflib import SequenceMatcher

import httpx

from app.ai.client import ClaudeJSON, month_start
from app.ai.prompts import EXTRACT_SCHEMA, EXTRACT_SYSTEM, as_prompt
from app.db.repository import Repository
from app.domain.dedupe import _plain, fingerprints, is_mobile, normalize_phone
from app.domain.radar import cell_id
from app.integrations.google_places import FoundPlace, PlacesClient, PlacesError, platform_of

PASTED_ZONE = "annuncio incollato"

# Parole che non distinguono una struttura da un'altra.
GENERIC_WORDS = {
    "a", "al", "alla", "and", "apartment", "apartments", "appartamenti", "appartamento", "b", "bb", "bed",
    "breakfast", "camera", "camere", "casa", "case", "da", "dei", "del", "della", "di", "e", "guest", "guesthouse",
    "holiday", "home", "house", "il", "in", "la", "le", "lo", "loft", "room", "rooms", "studio", "suite", "suites",
    "the", "vacanza", "vacanze", "affittacamere", "residence", "villa", "flat", "near", "vicino", "centro",
}


def _tokens(text: str, exclude: set[str]) -> set[str]:
    return {t for t in _plain(text).split() if len(t) > 1 and t not in GENERIC_WORDS and t not in exclude}


def name_similarity(a: str, b: str, comune: str = "") -> float:
    """Quanto si somigliano due nomi di struttura (0-1). Le parole generiche e il comune non contano."""
    town = set(_plain(comune).split())
    ta, tb = _tokens(a, town), _tokens(b, town)
    overlap = len(ta & tb) / min(len(ta), len(tb)) if ta and tb else 0.0
    ratio = SequenceMatcher(None, _plain(a), _plain(b)).ratio()
    return max(overlap, ratio)


def best_match(places: list[FoundPlace], name: str, comune: str) -> FoundPlace | None:
    """La struttura giusta tra i risultati: nome molto simile, oppure simile e nello stesso comune."""
    town = _plain(comune)
    best: tuple[float, FoundPlace] | None = None
    for place in places:
        if place.exclusion:
            continue
        score = name_similarity(name, place.candidate.name, comune)
        same_town = bool(town) and town in _plain(place.candidate.address or "")
        if (score >= 0.75 or (score >= 0.5 and same_town)) and (best is None or score > best[0]):
            best = (score, place)
    return best[1] if best else None


@dataclass(frozen=True)
class Located:
    outcome: str  # trovata | gia_in_memoria | non_contattare | senza_cellulare | non_trovata | spenta | limite | errore
    message: str = ""
    property_id: str | None = None
    name: str = ""


class PastedListingService:
    def __init__(
        self,
        repo: Repository,
        places: PlacesClient | None,
        ai: ClaudeJSON,
        *,
        search_price_usd_per_1000: Decimal | None,
        eur_per_usd: Decimal,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repo = repo
        self.places = places
        self.ai = ai
        self.price = search_price_usd_per_1000
        self.eur_per_usd = eur_per_usd
        self.clock = clock or (lambda: datetime.now(UTC))

    async def _google_allowed(self) -> Located | None:
        settings = await self.repo.get_settings()
        limit = settings.google_monthly_requests
        if self.places is None or (limit <= 0 and self.price is None):
            return Located("spenta", "Ricerca nei dati pubblici spenta: non posso cercare il cellulare.")
        used = await self.repo.month_google_requests(month_start(self.clock()))
        if limit > 0 and used >= limit:
            return Located("limite", f"Richieste Google del mese finite ({used} su {limit}): riprova il mese prossimo.")
        return None

    async def locate(
        self, text: str, link: str | None, cin: str | None, listing_prints: list[tuple[str, str]]
    ) -> Located:
        """Trova la struttura dell'annuncio nei dati pubblici e, se ha un cellulare, la salva in memoria."""
        blocked = await self._google_allowed()
        if blocked:
            return blocked
        extracted = (await self.ai.ask(
            purpose="estrazione", system=EXTRACT_SYSTEM, prompt=as_prompt("Testo incollato:", {"testo": text[:6000]}),
            schema=EXTRACT_SCHEMA,
        )).data
        name = str(extracted.get("nome") or "").strip()
        comune = str(extracted.get("comune") or "").strip()
        if not name:
            return Located("non_trovata", "Nel testo non trovo il nome della struttura: incollalo insieme all'annuncio.")
        query = " ".join(x for x in (name, str(extracted.get("indirizzo") or "").strip(), comune) if x)

        run_id = await self.repo.start_search_run(zone=PASTED_ZONE, query=f"annuncio: {name}"[:200], cell=None, provincia=None)
        try:
            result = await self.places.find(query)  # type: ignore[union-attr]
        except (PlacesError, httpx.HTTPError) as exc:
            await self.repo.finish_search_run(
                run_id, status="errore", results=0, new=0, known=0, excluded=0, pages=1, cost_eur=Decimal(0),
                error=str(exc)[:500],
            )
            return Located("errore", "Google non risponde in questo momento: riprova tra poco.")
        cost = (self.price or Decimal(0)) / Decimal(1000) * self.eur_per_usd
        await self.repo.finish_search_run(
            run_id, status="completata", results=len(result.places), new=0, known=0, excluded=0, pages=1,
            cost_eur=cost, reviews_raw=result.reviews_raw, reviews_text=result.reviews_text,
        )
        where = f" a {comune}" if comune else ""
        match = best_match(result.places, name, comune)
        if match is None:
            return Located(
                "non_trovata", f"Non trovo «{name}»{where} nei dati pubblici: senza cellulare non preparo la scheda.",
                name=name,
            )

        found = match.candidate
        urls = dict(found.listing_urls)
        portal = platform_of(link)
        if link and portal:
            urls[portal] = link
        candidate = dataclasses.replace(found, listing_urls=urls, cin=found.cin or cin)
        prints = fingerprints(candidate) + [p for p in listing_prints if p not in fingerprints(candidate)]
        known = await self.repo.find_fingerprints(prints)
        if known:
            owner = next((pid for pid in known.values() if pid), None)
            await self.repo.touch_property(owner, prints)
            return Located("gia_in_memoria", f"«{found.name}» è già in memoria: non la ripropongo.", owner, found.name)
        phone = normalize_phone(found.phone)
        if await self.repo.is_opted_out(phone, None):
            await self.repo.touch_property(None, prints)
            return Located("non_contattare", f"«{found.name}» ha chiesto di non essere contattata.", name=found.name)
        if not is_mobile(phone):
            await self.repo.touch_property(None, prints)  # ricordata, così il radar non la ripropone
            what = "solo un numero fisso" if phone else "nessun telefono"
            return Located(
                "senza_cellulare", f"Ho trovato «{found.name}» ({found.address or comune}) ma ha {what}: niente WhatsApp, "
                "niente scheda.", name=found.name,
            )
        cell = cell_id(found.latitude, found.longitude) if found.latitude is not None and found.longitude is not None else ""
        provincia = (await self.repo.province_for_cells([cell])).get(cell) if cell else None
        property_id = await self.repo.insert_property(
            candidate, prints, cell=cell or None, provincia=provincia, zone=PASTED_ZONE, query="/analizza"  # type: ignore[arg-type]
        )
        if property_id is None:
            return Located("gia_in_memoria", f"«{found.name}» è già in memoria: non la ripropongo.", name=found.name)
        return Located("trovata", property_id=property_id, name=found.name)
