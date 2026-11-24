"""Il giro completo del Lead Finder (fasi 2, 3 e 4).

1. Ricerca: il radar sceglie le celle, Google Places cerca, la memoria scarta le già viste.
2. Sito: per le strutture nuove si legge il sito proprio (email, CIN, portali).
3. Analisi: Claude analizza le strutture nuove (con le recensioni, se Google le manda).
4. Schede: le migliori (punteggio ≥ minimo) vanno a chi è di turno, con i messaggi pronti.
   Se la scheda singola di Google manda le recensioni (lo dicono le ultime letture), prima di
   mandarle si leggono le recensioni delle candidate e si rifà l'analisi: una richiesta ciascuna.
5. Riepilogo al titolare, con la spesa del giro e del mese.

Tetti di spesa: prima di ogni ricerca e di ogni chiamata AI si controlla la spesa del mese.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx

from app.ai.client import AIError, BudgetExceeded, month_start
from app.db.repository import Repository
from app.domain.dedupe import Candidate, fingerprints, normalize_email
from app.domain.models import LeadFinder, Property
from app.domain.shifts import on_shift
from app.integrations.google_places import MAX_PAGES, FoundPlace, PlacesClient, PlacesError
from app.integrations.website import check_website
from app.services.analysis import AnalysisService
from app.services.messages import MessageService
from app.services.radar import RadarService

log = logging.getLogger(__name__)

# Una ricerca = una sola richiesta a Google (fino a 20 strutture per cella): spesa prevedibile.
PAGES_PER_SEARCH = 1
DETAILS_QUERY = "dettagli scheda"  # lettura della scheda singola durante un giro
TEST_QUERY = "prova recensioni"  # prova da una richiesta (all'avvio o con /verifica recensioni)
DETAILS_WINDOW = 5  # se nelle ultime 5 letture nessuna ha portato recensioni, non si legge più


class Notifier(Protocol):
    async def send_card(self, member: LeadFinder, prop: Property) -> tuple[int, int] | None: ...
    async def notify_owners(self, text: str) -> None: ...


@dataclass
class RoundReport:
    trigger: str
    started_at: datetime
    searches: int = 0
    pages: int = 0
    results: int = 0
    new: int = 0
    known: int = 0
    excluded: int = 0
    analyzed: int = 0
    discarded: int = 0
    ai_errors: int = 0
    proposed: int = 0
    waiting: int = 0
    search_cost: Decimal = Decimal(0)
    ai_cost: Decimal = Decimal(0)
    month_search: Decimal = Decimal(0)
    month_ai: Decimal = Decimal(0)
    search_budget: Decimal = Decimal(0)
    ai_budget: Decimal = Decimal(0)
    google_requests: int = 0
    google_limit: int = 0
    reviews_raw: int = 0
    reviews_text: int = 0
    details_requests: int = 0
    details_reviews: int = 0
    reanalyzed: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class GoogleBudget:
    """Richieste Google ancora disponibili nel giro: tetto gratuito del mese e/o tetto in euro."""

    limit: int
    used: int
    price_set: bool
    page_cost: Decimal
    month_search: Decimal
    search_budget: Decimal

    def can_spend(self, pages: int = 1) -> bool:
        if self.limit <= 0 and not self.price_set:
            return False
        if self.limit > 0 and self.used + pages > self.limit:
            return False
        return not (self.price_set and self.month_search + self.page_cost * pages > self.search_budget)

    def spend(self, cost: Decimal, pages: int = 1) -> None:
        self.used += pages
        self.month_search += cost


@dataclass(frozen=True)
class DetailsRead:
    reviews: list[dict]
    raw: int
    cost: Decimal
    error: str | None = None


@dataclass(frozen=True)
class DetailsTest:
    """Esito della prova da una richiesta sulla scheda singola."""

    outcome: str  # recensioni | senza_testo | nessuna | errore | spenta | limite | nessuna_struttura | giro_in_corso
    name: str = ""
    ratings: int = 0
    raw: int = 0
    text: int = 0
    used: int = 0
    limit: int = 0
    error: str = ""


def euro(value: Decimal) -> str:
    return f"{value:.2f} €".replace(".", ",")


def format_report(r: RoundReport, timezone: ZoneInfo) -> str:
    when = r.started_at.astimezone(timezone).strftime("%H:%M")
    lines = [f"🛰 Giro delle {when} ({r.trigger})"]
    lines.append(f"🔎 Ricerche Google: {r.searches} ({r.pages} pagine) · strutture trovate {r.results}")
    if r.google_limit:
        lines.append(f"   Richieste Google del mese: {r.google_requests} su {r.google_limit} (gratuite)")
    if r.results:
        lines.append(f"   nuove {r.new} · già in memoria {r.known} · escluse {r.excluded}")
        lines.append(f"   recensioni ricevute da Google: {r.reviews_text}")
    if r.details_requests:
        lines.append(
            f"   schede singole lette: {r.details_requests} · recensioni trovate {r.details_reviews}"
            f" · analisi rifatte {r.reanalyzed}"
        )
    lines.append(f"🧠 Analizzate {r.analyzed} · scartate {r.discarded}" + (f" · errori {r.ai_errors}" if r.ai_errors else ""))
    lines.append(f"📨 Schede inviate {r.proposed}" + (f" · in attesa di qualcuno di turno {r.waiting}" if r.waiting else ""))
    lines.append(f"💶 Spesa del giro: ricerche {euro(r.search_cost)} · AI {euro(r.ai_cost)}")
    lines.append(
        f"   Mese: ricerche {euro(r.month_search)} su {euro(r.search_budget)} · AI {euro(r.month_ai)} su {euro(r.ai_budget)}"
    )
    notes = list(r.notes)
    if r.results and not r.reviews_text and not r.details_reviews:
        notes.append(
            "Google non ha mandato recensioni: l'analisi si basa su voto, numero di recensioni, canali e sito. "
            "Per le strutture migliori potete incollarle voi col pulsante «📝 Aggiungi recensioni»."
        )
    lines += [f"⚠️ {note}" for note in notes]
    return "\n".join(lines)


def wants_details(prop: Property) -> bool:
    """Ha senso leggere la scheda singola: ci sono recensioni su Google ma nessun testo letto."""
    if not prop.google_place_id or not (prop.google_rating.get("recensioni") or 0):
        return False
    read = ((prop.analysis or {}).get("recensioni") or {}).get("lette")
    return not read


def contactable(prop: Property, mode: str) -> bool:
    if mode == "telefonate":
        return bool(prop.phone_normalized)
    return bool(prop.phone_normalized or prop.email_normalized)


class RoundService:
    def __init__(
        self,
        repo: Repository,
        radar: RadarService,
        notifier: Notifier,
        *,
        analysis: AnalysisService | None,
        messages: MessageService | None,
        places: PlacesClient | None,
        http: httpx.AsyncClient | None,
        search_price_usd_per_1000: Decimal | None,
        eur_per_usd: Decimal,
        timezone: ZoneInfo,
        clock: Callable[[], datetime] | None = None,
        pages_per_search: int = PAGES_PER_SEARCH,
    ) -> None:
        self.repo = repo
        self.radar = radar
        self.notifier = notifier
        self.analysis = analysis
        self.messages = messages
        self.places = places
        self.http = http
        self.price = search_price_usd_per_1000
        self.eur_per_usd = eur_per_usd
        self.timezone = timezone
        self.clock = clock or (lambda: datetime.now(UTC))
        self.lock = asyncio.Lock()
        self.pages_per_search = max(1, min(MAX_PAGES, pages_per_search))

    @property
    def page_cost(self) -> Decimal:
        return (self.price or Decimal(0)) / Decimal(1000) * self.eur_per_usd

    async def run(self, trigger: str) -> RoundReport | None:
        """Esegue un giro. None se ce n'è già uno in corso."""
        if self.lock.locked():
            return None
        async with self.lock:
            try:
                report = await self._run(trigger)
            except Exception as exc:  # noqa: BLE001 - il titolare deve saperlo, il bot resta acceso
                log.exception("Giro interrotto")
                report = RoundReport(trigger=trigger, started_at=self.clock())
                report.notes.append(f"Giro interrotto da un errore imprevisto ({exc.__class__.__name__}). Riprovo al prossimo giro.")
        try:
            await self.notifier.notify_owners(format_report(report, self.timezone))
        except Exception:  # noqa: BLE001 - il riepilogo non deve far fallire il giro
            log.exception("Riepilogo del giro non inviato")
        return report

    async def _run(self, trigger: str) -> RoundReport:
        now = self.clock()
        settings = await self.repo.get_settings()
        state = await self.repo.get_state()
        since = month_start(now)
        month_search, month_ai_before = await self.repo.month_costs(since)
        report = RoundReport(
            trigger=trigger,
            started_at=now,
            search_budget=Decimal(settings.monthly_search_budget_eur),
            ai_budget=Decimal(settings.monthly_ai_budget_eur),
        )
        reviews: dict[str, list[dict]] = {}
        limit = settings.google_monthly_requests
        google_used = await self.repo.month_google_requests(since)
        report.google_limit = limit

        # 1. Ricerca
        if self.places is None:
            report.notes.append("Ricerca su Google spenta: manca GOOGLE_MAPS_API_KEY nelle variabili di Railway.")
        elif self.price is None and settings.google_monthly_requests <= 0:
            report.notes.append(
                "Ricerca su Google spenta: nel gestionale (Impostazioni) imposta il massimo di richieste Google al mese "
                "(le gratuite)."
            )
        elif settings.searches_per_run <= 0:
            report.notes.append("Ricerche per giro impostate a 0 nel gestionale.")
        else:
            targets = await self.radar.next_targets(settings.searches_per_run, now)
            if not targets:
                report.notes.append("Nessuna zona attiva da cercare: impostala dal gestionale (Zone).")
            failures = 0
            for target in targets:
                max_pages = self.pages_per_search
                if limit > 0:
                    max_pages = min(self.pages_per_search, limit - google_used)
                    if max_pages <= 0:
                        report.notes.append(
                            f"Raggiunte le {limit} richieste Google del mese: ricerche ferme fino al mese prossimo."
                        )
                        break
                if self.price is not None and month_search + self.page_cost * max_pages > report.search_budget:
                    report.notes.append("Tetto di spesa del mese per le ricerche raggiunto: ricerche ferme.")
                    break
                run_id = await self.repo.start_search_run(
                    zone=target.zone, query=target.query, cell=target.cell, provincia=target.provincia
                )
                try:
                    result = await self.places.search(target.query, target.bounds, max_pages=max_pages)
                except (PlacesError, httpx.HTTPError) as exc:
                    failures += 1
                    google_used += 1  # per prudenza si conta anche la richiesta fallita
                    await self.repo.finish_search_run(
                        run_id, status="errore", results=0, new=0, known=0, excluded=0, pages=1,
                        cost_eur=Decimal(0), error=str(exc)[:500],
                    )
                    if failures >= 2:
                        report.notes.append(f"Google non risponde correttamente: {str(exc)[:200]}")
                        break
                    continue
                cost = self.page_cost * result.pages
                google_used += result.pages
                month_search += cost
                report.search_cost += cost
                report.searches += 1
                report.pages += result.pages
                report.results += len(result.places)
                by_place: dict[str, FoundPlace] = {
                    fp.candidate.google_place_id: fp for fp in result.places if fp.candidate.google_place_id
                }
                excluded = [fp for fp in result.places if fp.exclusion]
                for fp in excluded:  # si ricordano solo le impronte, senza salvare i dati
                    prints = fingerprints(fp.candidate)
                    if prints:
                        await self.repo.touch_property(None, prints)
                keep = [fp.candidate for fp in result.places if not fp.exclusion and fp.candidate.name]
                outcome = await self.radar.record_results(target, keep, now)
                for candidate, property_id in outcome.new_pairs:
                    found = by_place.get(candidate.google_place_id or "")
                    reviews[property_id] = found.reviews if found else []
                report.new += len(outcome.new_ids)
                report.known += outcome.already_known
                report.excluded += len(excluded) + outcome.opted_out
                await self.repo.finish_search_run(
                    run_id, status="completata", results=len(result.places), new=len(outcome.new_ids),
                    known=outcome.already_known, excluded=len(excluded) + outcome.opted_out,
                    pages=result.pages, cost_eur=cost, reviews_raw=result.reviews_raw, reviews_text=result.reviews_text,
                )
                report.reviews_raw += result.reviews_raw
                report.reviews_text += result.reviews_text

        # 2. Sito delle strutture nuove
        if reviews and self.http is not None:
            semaphore = asyncio.Semaphore(4)

            async def check(property_id: str) -> None:
                async with semaphore:
                    await self.check_site(property_id)

            await asyncio.gather(*(check(pid) for pid in reviews))

        budget = GoogleBudget(
            limit=limit, used=google_used, price_set=self.price is not None, page_cost=self.page_cost,
            month_search=month_search, search_budget=report.search_budget,
        )
        details_ok = self.places is not None and await self.details_available()

        # 3. Analisi
        if self.analysis is None:
            report.notes.append("Analisi AI spenta: manca ANTHROPIC_API_KEY nelle variabili di Railway.")
        else:
            queue_size = max(settings.cards_per_run * 3, len(reviews), 10)
            queue = await self.repo.properties_by_status("nuovo", queue_size)
            queue.sort(key=lambda p: p.id not in reviews)  # prima quelle appena trovate
            for prop in queue:
                prop_reviews = reviews.get(prop.id)
                if prop_reviews is None and details_ok and wants_details(prop) and budget.can_spend():
                    # rimasta in coda da un giro precedente: si rileggono le recensioni (una richiesta)
                    prop_reviews = await self._read_details(prop, budget, report)
                try:
                    analyzed = await self.analysis.analyze(prop, prop_reviews or [])
                except BudgetExceeded as exc:
                    report.notes.append(str(exc) + " Analisi ferme fino al mese prossimo o a un tetto più alto.")
                    break
                if analyzed.status == "analizzato":
                    report.analyzed += 1
                elif analyzed.status == "scartato":
                    report.discarded += 1
                else:
                    report.ai_errors += 1

        # 4. Schede a chi è di turno
        if self.messages is not None:
            await self.propose(
                report, settings.min_score, settings.cards_per_run, state.mode, now,
                budget=budget if details_ok else None,
            )

        _, month_ai = await self.repo.month_costs(since)
        report.month_search = budget.month_search
        report.month_ai = month_ai
        report.google_requests = budget.used
        report.ai_cost = month_ai - month_ai_before
        return report

    async def check_site(self, property_id: str) -> None:
        prop = await self.repo.get_property(property_id)
        if prop is None or not prop.website or self.http is None:
            return
        site = await check_website(prop.website, self.http)
        fields: dict = {"website_check": site}
        new_prints: list[tuple[str, str]] = []
        if site.get("email") and not prop.email:
            fields["email"] = site["email"][0]
            fields["email_normalized"] = normalize_email(site["email"][0])
            new_prints += fingerprints(Candidate(name="", email=site["email"][0]))
        if site.get("cin") and not prop.cin:
            fields["cin"] = site["cin"][0]
            new_prints += fingerprints(Candidate(name="", cin=site["cin"][0]))
        if site.get("portali"):
            fields["listing_urls"] = {**site["portali"], **prop.listing_urls}
        await self.repo.update_property(property_id, **fields)
        if new_prints:
            await self.repo.touch_property(property_id, new_prints)
        if fields.get("email_normalized") and await self.repo.is_opted_out(None, fields["email_normalized"]):
            await self.repo.update_property(property_id, status="scartato", discard_reason="opt_out")

    async def details_available(self) -> bool:
        """La scheda singola di Google manda le recensioni? Lo dicono le ultime letture registrate."""
        return any(n > 0 for n in await self.repo.recent_details_runs(DETAILS_WINDOW))

    async def _read_details(self, prop: Property, budget: GoogleBudget, report: RoundReport) -> list[dict]:
        read = await self.fetch_details(prop)
        budget.spend(read.cost)
        report.search_cost += read.cost
        report.details_requests += 1
        report.details_reviews += len(read.reviews)
        return read.reviews

    async def fetch_details(self, prop: Property, query: str = DETAILS_QUERY) -> DetailsRead:
        """Legge la scheda singola (con le recensioni): una richiesta, registrata come ricerca."""
        run_id = await self.repo.start_search_run(zone=prop.zone or "", query=query, cell=None, provincia=None)
        try:
            found = await self.places.details(prop.google_place_id)  # type: ignore[union-attr, arg-type]
        except (PlacesError, httpx.HTTPError) as exc:
            await self.repo.finish_search_run(
                run_id, status="errore", results=0, new=0, known=0, excluded=0, pages=1, cost_eur=Decimal(0),
                error=str(exc)[:500],
            )
            return DetailsRead([], 0, Decimal(0), str(exc)[:200])
        cost = self.page_cost
        await self.repo.finish_search_run(
            run_id, status="completata", results=1, new=0, known=1, excluded=0, pages=1, cost_eur=cost,
            reviews_raw=found.reviews_raw, reviews_text=len(found.reviews),
        )
        return DetailsRead(found.reviews, found.reviews_raw, cost)

    async def test_details(self) -> DetailsTest:
        """Prova da una sola richiesta: la scheda singola di Google manda le recensioni?

        Si usa la struttura in memoria con più recensioni su Google (più probabile che ne arrivino).
        """
        if self.places is None:
            return DetailsTest("spenta")
        if self.lock.locked():
            return DetailsTest("giro_in_corso")
        async with self.lock:
            settings = await self.repo.get_settings()
            limit = settings.google_monthly_requests
            used = await self.repo.month_google_requests(month_start(self.clock()))
            if limit <= 0 and self.price is None:
                return DetailsTest("spenta")
            if limit > 0 and used >= limit:
                return DetailsTest("limite", used=used, limit=limit)
            pool = [
                p for status in ("analizzato", "proposto", "approvato", "contattato")
                for p in await self.repo.properties_by_status(status, 500)
                if p.google_place_id and (p.google_rating.get("recensioni") or 0) > 0
            ]
            if not pool:
                return DetailsTest("nessuna_struttura", used=used, limit=limit)
            prop = max(pool, key=lambda p: p.google_rating.get("recensioni") or 0)
            read = await self.fetch_details(prop, TEST_QUERY)
            ratings = int(prop.google_rating.get("recensioni") or 0)
            common = {"name": prop.name, "ratings": ratings, "used": used + 1, "limit": limit}
            if read.error:
                return DetailsTest("errore", error=read.error, **common)
            if read.reviews:
                outcome = "recensioni"
            elif read.raw:
                outcome = "senza_testo"
            else:
                outcome = "nessuna"
            return DetailsTest(outcome, raw=read.raw, text=len(read.reviews), **common)

    async def eligible_members(self, now: datetime) -> list[LeadFinder]:
        local = now.astimezone(self.timezone)
        return [
            m for m in await self.repo.list_members()
            if m.is_active and m.telegram_chat_id and m.receives_cards and on_shift(m.shifts, local)
        ]

    async def propose(
        self, report: RoundReport, min_score: int, limit: int, mode: str, now: datetime,
        budget: GoogleBudget | None = None,
    ) -> None:
        """Schede a chi è di turno. Con `budget` (la scheda singola manda le recensioni) prima di scrivere
        i messaggi si leggono le recensioni della candidata e si rifà l'analisi."""
        candidates = [p for p in await self.repo.proposal_candidates(min_score, limit * 3) if contactable(p, mode)]
        if not candidates:
            return
        members = await self.eligible_members(now)
        if not members:
            report.waiting = min(len(candidates), limit)
            report.notes.append("Nessuno di turno adesso: le schede partono al prossimo giro con qualcuno di turno.")
            return
        load = await self.repo.open_assignments()
        for prop in candidates:
            if report.proposed >= limit:
                break
            if budget is not None and self.analysis is not None and wants_details(prop) and budget.can_spend():
                found = await self._read_details(prop, budget, report)
                if found:
                    try:
                        prop = await self.analysis.analyze(prop, found)
                    except BudgetExceeded as exc:
                        report.notes.append(str(exc) + " Schede ferme.")
                        break
                    report.reanalyzed += 1
                    if prop.status != "analizzato" or (prop.score or 0) < min_score:
                        continue  # con le recensioni non è più tra le migliori
                elif not await self.details_available():
                    budget = None  # Google ha smesso di mandarle: niente altre richieste
            member = min(members, key=lambda m: (load.get(m.id, 0), m.name))
            try:
                await self.messages.write(prop, member.name)  # type: ignore[union-attr]
            except BudgetExceeded as exc:
                report.notes.append(str(exc) + " Schede ferme.")
                report.waiting += 1
                break
            except AIError as exc:
                report.ai_errors += 1
                log.warning("Messaggi non scritti per %s: %s", prop.id, exc)
                continue
            await self.repo.update_property(prop.id, assigned_to=member.id, status="proposto", proposed_at=now)
            await self.repo.add_property_event(
                prop.id, actor_id=None, actor_label="bot", source="bot", event_type="proposta",
                from_status=prop.status, to_status="proposto", details={"a": member.name},
            )
            updated = await self.repo.get_property(prop.id)
            sent = await self.notifier.send_card(member, updated or prop)
            if sent:
                await self.repo.update_property(prop.id, telegram_chat_id=sent[0], telegram_message_id=sent[1])
            load[member.id] = load.get(member.id, 0) + 1
            report.proposed += 1
