"""Servizio del radar: decide dove cercare e ricorda cosa ha già trovato.

La ricerca vera (Google Places) arriva nella fase 2: qui ci sono la scelta delle celle
e la memoria storica, già pronte e provate. Il flusso di ogni giro sarà:
    targets = await radar.next_targets(n)
    for target in targets:
        candidates = <ricerca nella cella target.bounds con la parola target.query>
        outcome = await radar.record_results(target, candidates)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from app.db.repository import Repository
from app.domain.dedupe import Candidate, fingerprints, normalize_email, normalize_phone
from app.domain.radar import Target, after_search, plan, province_codes, zone_cells


@dataclass(frozen=True)
class SearchOutcome:
    target: Target
    results: int
    new_ids: list[str] = field(default_factory=list)
    already_known: int = 0
    opted_out: int = 0
    unidentifiable: int = 0


class RadarService:
    def __init__(self, repo: Repository, rng: random.Random | None = None) -> None:
        self.repo = repo
        self.rng = rng or random.Random()

    async def next_targets(self, limit: int, now: datetime | None = None) -> list[Target]:
        """Le prossime `limit` ricerche da fare, secondo le zone attive e la memoria."""
        now = now or datetime.now(UTC)
        settings = await self.repo.get_settings()
        province_cells = await self.repo.province_cells(province_codes(settings.zones))
        cells = zone_cells(settings.zones, province_cells)
        if not cells:
            return []
        memory = await self.repo.get_cell_memory(list(cells), list(settings.search_queries))
        targets = plan(cells, settings.search_queries, memory, now, limit, self.rng)
        missing = [t.cell for t in targets if t.provincia is None]
        if missing:
            provinces = await self.repo.province_for_cells(missing)
            targets = [t if t.provincia else replace(t, provincia=provinces.get(t.cell)) for t in targets]
        return targets

    async def record_results(
        self, target: Target, candidates: list[Candidate], now: datetime | None = None
    ) -> SearchOutcome:
        """Salva solo le strutture mai viste prima e aggiorna la memoria della cella."""
        now = now or datetime.now(UTC)
        seen_now: set[tuple[str, str]] = set()
        new_ids: list[str] = []
        known = opted_out = unidentifiable = 0
        for candidate in candidates:
            prints = fingerprints(candidate)
            if not prints:
                unidentifiable += 1
                continue
            if seen_now.intersection(prints):  # la stessa struttura due volte nella stessa ricerca
                known += 1
                continue
            seen_now.update(prints)
            found = await self.repo.find_fingerprints(prints)
            if found:
                property_id = next((pid for pid in found.values() if pid), None)
                await self.repo.touch_property(property_id, prints)
                known += 1
                continue
            if await self.repo.is_opted_out(normalize_phone(candidate.phone), normalize_email(candidate.email)):
                opted_out += 1
                continue
            property_id = await self.repo.insert_property(
                candidate, prints, cell=target.cell, provincia=target.provincia, zone=target.zone, query=target.query
            )
            if property_id:
                new_ids.append(property_id)
            else:
                known += 1
        previous = (await self.repo.get_cell_memory([target.cell], [target.query])).get((target.cell, target.query))
        memory = after_search(previous, target.cell, target.query, len(candidates), len(new_ids), now)
        await self.repo.save_cell_memory(memory, results=len(candidates), new=len(new_ids))
        return SearchOutcome(target, len(candidates), new_ids, known, opted_out, unidentifiable)
