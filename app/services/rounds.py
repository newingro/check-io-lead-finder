"""Il giro completo del Lead Finder (fasi 2, 3 e 4).

1. Ricerca: il radar sceglie le celle, Google Places cerca, la memoria scarta le già viste.
2. Sito: per le strutture nuove si legge il sito proprio (email, CIN, portali).
3. Analisi: Claude analizza le strutture nuove (con le recensioni appena lette).
4. Schede: le migliori (punteggio ≥ minimo) vanno a chi è di turno, con i messaggi pronti.
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
    notes: list[str] = field(default_factory=list)


def euro(value: Decimal) -> str:
    return f"{value:.2f} €".replace(".", ",")


def format_report(r: RoundReport, timezone: ZoneInfo) -> str:
    when = r.started_at.astimezone(timezone).strftime("%H:%M")
    lines = [f"🛰 Giro delle {when} ({r.trigger})"]
    lines.append(f"🔎 Ricerche Google: {r.searches} ({r.pages} pagine) · strutture trovate {r.results}")
    if r.results:
        lines.append(f"   nuove {r.new} · già in memoria {r.known} · escluse {r.excluded}")
    lines.append(f"🧠 Analizzate {r.analyzed} · scartate {r.discarded}" + (f" · errori {r.ai_errors}" if r.ai_errors else ""))
    lines.append(f"📨 Schede inviate {r.proposed}" + (f" · in attesa di qualcuno di turno {r.waiting}" if r.waiting else ""))
    lines.append(f"💶 Spesa del giro: ricerche {euro(r.search_cost)} · AI {euro(r.ai_cost)}")
    lines.append(
        f"   Mese: ricerche {euro(r.month_search)} su {euro(r.search_budget)} · AI {euro(r.month_ai)} su {euro(r.ai_budget)}"
    )
    lines += [f"⚠️ {note}" for note in r.notes]
    return "\n".join(lines)


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

        # 1. Ricerca
        if self.places is None:
            report.notes.append("Ricerca su Google spenta: manca GOOGLE_MAPS_API_KEY nelle variabili di Railway.")
        elif self.price is None:
            report.notes.append(
                "Ricerca su Google spenta: manca GOOGLE_TEXT_SEARCH_USD_PER_1000 (prezzo di Google, per il conto della spesa)."
            )
        elif settings.searches_per_run <= 0:
            report.notes.append("Ricerche per giro impostate a 0 nel gestionale.")
        else:
            targets = await self.radar.next_targets(settings.searches_per_run, now)
            if not targets:
                report.notes.append("Nessuna zona attiva da cercare: impostala dal gestionale (Zone).")
            failures = 0
            for target in targets:
                if month_search + self.page_cost * MAX_PAGES > report.search_budget:
                    report.notes.append("Tetto di spesa del mese per le ricerche raggiunto: ricerche ferme.")
                    break
                run_id = await self.repo.start_search_run(
                    zone=target.zone, query=target.query, cell=target.cell, provincia=target.provincia
                )
                try:
                    result = await self.places.search(target.query, target.bounds)
                except (PlacesError, httpx.HTTPError) as exc:
                    failures += 1
                    await self.repo.finish_search_run(
                        run_id, status="errore", results=0, new=0, known=0, excluded=0, pages=1,
                        cost_eur=Decimal(0), error=str(exc)[:500],
                    )
                    if failures >= 2:
                        report.notes.append(f"Google non risponde correttamente: {str(exc)[:200]}")
                        break
                    continue
                cost = self.page_cost * result.pages
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
                    pages=result.pages, cost_eur=cost,
                )

        # 2. Sito delle strutture nuove
        if reviews and self.http is not None:
            semaphore = asyncio.Semaphore(4)

            async def check(property_id: str) -> None:
                async with semaphore:
                    await self.check_site(property_id)

            await asyncio.gather(*(check(pid) for pid in reviews))

        # 3. Analisi
        if self.analysis is None:
            report.notes.append("Analisi AI spenta: manca ANTHROPIC_API_KEY nelle variabili di Railway.")
        else:
            limit = max(settings.cards_per_run * 3, len(reviews), 10)
            queue = await self.repo.properties_by_status("nuovo", limit)
            queue.sort(key=lambda p: p.id not in reviews)  # prima quelle appena trovate
            for prop in queue:
                prop_reviews = reviews.get(prop.id)
                if prop_reviews is None and prop.google_place_id and self.places and self.price:
                    prop_reviews, cost = await self.fetch_reviews(prop)
                    month_search += cost
                    report.search_cost += cost
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
            await self.propose(report, settings.min_score, settings.cards_per_run, state.mode, now)

        _, month_ai = await self.repo.month_costs(since)
        report.month_search = month_search
        report.month_ai = month_ai
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

    async def fetch_reviews(self, prop: Property) -> tuple[list[dict], Decimal]:
        """Strutture rimaste in coda da un giro precedente: si rileggono le recensioni (una richiesta pagata)."""
        run_id = await self.repo.start_search_run(zone=prop.zone or "", query="dettagli scheda", cell=None, provincia=None)
        try:
            found = await self.places.details(prop.google_place_id)  # type: ignore[union-attr, arg-type]
        except (PlacesError, httpx.HTTPError) as exc:
            await self.repo.finish_search_run(
                run_id, status="errore", results=0, new=0, known=0, excluded=0, pages=1, cost_eur=Decimal(0),
                error=str(exc)[:500],
            )
            return [], Decimal(0)
        cost = self.page_cost
        await self.repo.finish_search_run(
            run_id, status="completata", results=1, new=0, known=1, excluded=0, pages=1, cost_eur=cost
        )
        return found.reviews, cost

    async def eligible_members(self, now: datetime) -> list[LeadFinder]:
        local = now.astimezone(self.timezone)
        return [
            m for m in await self.repo.list_members()
            if m.is_active and m.telegram_chat_id and m.receives_cards and on_shift(m.shifts, local)
        ]

    async def propose(self, report: RoundReport, min_score: int, limit: int, mode: str, now: datetime) -> None:
        candidates = [p for p in await self.repo.proposal_candidates(min_score, limit * 3) if contactable(p, mode)]
        candidates = candidates[:limit]
        if not candidates:
            return
        members = await self.eligible_members(now)
        if not members:
            report.waiting = len(candidates)
            report.notes.append("Nessuno di turno adesso: le schede partono al prossimo giro con qualcuno di turno.")
            return
        load = await self.repo.open_assignments()
        for prop in candidates:
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
