"""Database in memoria: usato nelle prove automatiche, senza rete."""

from __future__ import annotations

import uuid
from dataclasses import fields as dataclass_fields
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.domain.dedupe import Candidate, normalize_email, normalize_phone
from app.domain.models import OPEN_STATUSES, ROLE_OWNER, LeadFinder, Property, Settings, State
from app.domain.radar import CellMemory

from .repository import AlreadyLinkedError, CodeAlreadyUsedError, LinkTarget


def default_settings() -> Settings:
    return Settings(
        zones=[],
        property_types=["appartamento", "stanza", "b&b", "casa vacanze", "affittacamere", "guest house"],
        search_queries=["casa vacanze", "appartamenti vacanze", "B&B", "affittacamere", "guest house"],
        min_score=60,
        cards_per_run=5,
        run_times=["10:00", "12:30", "15:00"],
        run_days=["lun", "mar", "mer", "gio", "ven"],
        followup_days=5,
        max_followups=2,
        archive_after_days=30,
        max_call_attempts=3,
        call_retry_minutes=120,
        monthly_ai_budget_eur=Decimal("30.00"),
        monthly_search_budget_eur=Decimal("30.00"),
        data_retention_months=12,
        version=1,
    )


class InMemoryRepository:
    def __init__(self) -> None:
        self.members: dict[str, LeadFinder] = {}
        self.codes: dict[str, dict[str, Any]] = {}
        self.settings: Settings = default_settings()
        self.state: State = State(paused=True, mode="misto", version=1)
        self.audit: list[dict[str, Any]] = []
        self.province: dict[str, list[str]] = {}
        self.cell_memory: dict[tuple[str, str], CellMemory] = {}
        self.cell_totals: dict[tuple[str, str], tuple[int, int]] = {}
        self.fingerprints: dict[tuple[str, str], str | None] = {}
        self.properties: dict[str, dict[str, Any]] = {}
        self.opt_out: list[tuple[str | None, str | None]] = []
        self.events: list[dict[str, Any]] = []
        self.search_runs: dict[str, dict[str, Any]] = {}
        self.ai_usage: list[dict[str, Any]] = []

    # Persone
    async def get_member_by_telegram(self, telegram_user_id: int) -> LeadFinder | None:
        return next((m for m in self.members.values() if m.telegram_user_id == telegram_user_id), None)

    async def get_member_by_name(self, name: str) -> LeadFinder | None:
        key = name.strip().casefold()
        return next((m for m in self.members.values() if m.name.casefold() == key), None)

    async def list_members(self) -> list[LeadFinder]:
        return sorted(self.members.values(), key=lambda m: (m.role != ROLE_OWNER, m.name.casefold()))

    async def count_linked_owners(self) -> int:
        return sum(1 for m in self.members.values() if m.is_owner and m.is_linked and m.is_active)

    async def create_member(self, name: str, role: str, shifts: dict[str, Any]) -> LeadFinder:
        member = LeadFinder(id=str(uuid.uuid4()), name=name.strip(), role=role, shifts=shifts)
        self.members[member.id] = member
        return member

    async def update_member_chat(self, member_id: str, chat_id: int, username: str | None) -> None:
        self.members[member_id] = replace(self.members[member_id], telegram_chat_id=chat_id, telegram_username=username)

    # Codici
    async def create_link_code(
        self, member_id: str, code_hash: str, expires_at: datetime, created_by: str | None
    ) -> None:
        for code in self.codes.values():  # un solo codice valido per persona
            if code["member_id"] == member_id and code["used_at"] is None:
                code["used_at"] = datetime.now(UTC)
        code_id = str(uuid.uuid4())
        self.codes[code_hash] = {"id": code_id, "member_id": member_id, "expires_at": expires_at, "used_at": None}

    async def find_link_code(self, code_hash: str) -> LinkTarget | None:
        code = self.codes.get(code_hash)
        if code is None:
            return None
        return LinkTarget(
            code_id=code["id"],
            lead_finder=self.members[code["member_id"]],
            expires_at=code["expires_at"],
            used_at=code["used_at"],
        )

    async def complete_link(
        self, code_id: str, member_id: str, telegram_user_id: int, chat_id: int, username: str | None
    ) -> LeadFinder:
        code = next(c for c in self.codes.values() if c["id"] == code_id)
        if code["used_at"] is not None:
            raise CodeAlreadyUsedError
        member = await self.link_member_directly(member_id, telegram_user_id, chat_id, username)
        code["used_at"] = datetime.now(UTC)
        return member

    async def link_member_directly(
        self, member_id: str, telegram_user_id: int, chat_id: int, username: str | None
    ) -> LeadFinder:
        other = await self.get_member_by_telegram(telegram_user_id)
        if other is not None and other.id != member_id:
            raise AlreadyLinkedError
        member = replace(
            self.members[member_id],
            telegram_user_id=telegram_user_id,
            telegram_chat_id=chat_id,
            telegram_username=username,
            linked_at=datetime.now(UTC),
            is_active=True,
        )
        self.members[member_id] = member
        return member

    # Impostazioni e stato
    async def get_settings(self) -> Settings:
        return self.settings

    async def get_state(self) -> State:
        return self.state

    async def update_state(self, *, paused: bool | None, mode: str | None, updated_by: str) -> State:
        new_paused = self.state.paused if paused is None else paused
        new_mode = self.state.mode if mode is None else mode
        if (new_paused, new_mode) != (self.state.paused, self.state.mode):
            self.state = State(
                paused=new_paused,
                mode=new_mode,
                version=self.state.version + 1,
                updated_by=updated_by,
                updated_at=datetime.now(UTC),
            )
        return self.state

    def change_settings(self, **changes: Any) -> None:
        """Simula una modifica fatta dal gestionale."""
        self.settings = replace(self.settings, version=self.settings.version + 1, **changes)

    # Registro
    async def add_audit(
        self, actor_id: str | None, actor_label: str, source: str, action: str, details: dict[str, Any]
    ) -> None:
        self.audit.append(
            {"actor_id": actor_id, "actor_label": actor_label, "source": source, "action": action, "details": details}
        )

    # Radar
    async def province_cells(self, codes: list[str]) -> dict[str, list[str]]:
        return {code: list(self.province[code]) for code in codes if code in self.province}

    async def province_for_cells(self, cells: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for code in sorted(self.province):
            for cell in self.province[code]:
                if cell in cells:
                    result.setdefault(cell, code)
        return result

    async def get_cell_memory(self, cells: list[str], queries: list[str]) -> dict[tuple[str, str], CellMemory]:
        return {key: mem for key, mem in self.cell_memory.items() if key[0] in cells and key[1] in queries}

    async def save_cell_memory(self, memory: CellMemory, results: int, new: int) -> None:
        key = (memory.cell, memory.query)
        total_results, total_new = self.cell_totals.get(key, (0, 0))
        self.cell_totals[key] = (total_results + results, total_new + new)
        self.cell_memory[key] = memory

    # Memoria delle strutture
    async def find_fingerprints(self, prints: list[tuple[str, str]]) -> dict[tuple[str, str], str | None]:
        return {p: self.fingerprints[p] for p in prints if p in self.fingerprints}

    async def touch_property(self, property_id: str | None, prints: list[tuple[str, str]]) -> None:
        for p in prints:
            self.fingerprints.setdefault(p, property_id)
        if property_id and property_id in self.properties:
            self.properties[property_id]["times_seen"] += 1

    async def is_opted_out(self, phone: str | None, email: str | None) -> bool:
        return any((phone and phone == p) or (email and email == e) for p, e in self.opt_out)

    async def insert_property(
        self,
        candidate: Candidate,
        prints: list[tuple[str, str]],
        *,
        cell: str,
        provincia: str | None,
        zone: str,
        query: str,
    ) -> str | None:
        if any(p in self.fingerprints for p in prints):
            return None
        property_id = str(uuid.uuid4())
        self.properties[property_id] = {
            "id": property_id,
            "name": candidate.name,
            "property_type": candidate.property_type,
            "address": candidate.address,
            "latitude": candidate.latitude,
            "longitude": candidate.longitude,
            "google_place_id": candidate.google_place_id,
            "phone": candidate.phone,
            "phone_normalized": normalize_phone(candidate.phone),
            "email": candidate.email,
            "email_normalized": normalize_email(candidate.email),
            "website": candidate.website,
            "cin": candidate.cin,
            "ratings": dict(candidate.ratings),
            "listing_urls": dict(candidate.listing_urls),
            "cell": cell,
            "provincia": provincia,
            "zone": zone,
            "query": query,
            "search_query": query,
            "status": "nuovo",
            "times_seen": 1,
            "created_at": datetime.now(UTC),
        }
        for p in prints:
            self.fingerprints[p] = property_id
        return property_id

    async def purge_expired(self) -> int:
        return 0

    # Strutture
    def _property(self, row: dict[str, Any]) -> Property:
        names = {f.name for f in dataclass_fields(Property)}
        return Property(**{k: v for k, v in row.items() if k in names})

    async def get_property(self, property_id: str) -> Property | None:
        row = self.properties.get(property_id)
        return self._property(row) if row else None

    async def properties_by_status(self, status: str, limit: int) -> list[Property]:
        rows = [r for r in self.properties.values() if r.get("status") == status]
        rows.sort(key=lambda r: r.get("created_at") or datetime.min.replace(tzinfo=UTC))
        return [self._property(r) for r in rows[:limit]]

    async def update_property(self, property_id: str, **fields: Any) -> None:
        self.properties[property_id].update(fields)

    async def add_property_event(
        self,
        property_id: str,
        *,
        actor_id: str | None,
        actor_label: str,
        source: str,
        event_type: str,
        from_status: str | None = None,
        to_status: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(
            {
                "property_id": property_id, "actor_id": actor_id, "actor_label": actor_label, "source": source,
                "event_type": event_type, "from_status": from_status, "to_status": to_status, "details": details or {},
            }
        )

    async def proposal_candidates(self, min_score: int, limit: int) -> list[Property]:
        rows = [
            r for r in self.properties.values()
            if r.get("status") == "analizzato" and not r.get("assigned_to") and (r.get("score") or 0) >= min_score
        ]
        rows.sort(key=lambda r: -(r.get("score") or 0))
        return [self._property(r) for r in rows[:limit]]

    async def open_assignments(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.properties.values():
            if r.get("assigned_to") and r.get("status") in OPEN_STATUSES:
                counts[r["assigned_to"]] = counts.get(r["assigned_to"], 0) + 1
        return counts

    async def add_opt_out(self, phone: str | None, email: str | None, reason: str, member_id: str | None) -> None:
        if phone or email:
            self.opt_out.append((phone, email))

    async def insert_manual_property(
        self, name: str, listing_urls: dict[str, str], prints: list[tuple[str, str]], cin: str | None, member_id: str
    ) -> str | None:
        if any(p in self.fingerprints for p in prints):
            return None
        property_id = str(uuid.uuid4())
        self.properties[property_id] = {
            "id": property_id, "name": name, "listing_urls": dict(listing_urls), "cin": cin,
            "source": "link_incollato", "assigned_to": member_id, "status": "nuovo", "times_seen": 1,
            "created_at": datetime.now(UTC),
        }
        for p in prints:
            self.fingerprints[p] = property_id
        return property_id

    # Costi
    async def month_costs(self, since: datetime) -> tuple[Decimal, Decimal]:
        search = sum((r["cost_eur"] for r in self.search_runs.values() if r["started_at"] >= since), Decimal(0))
        ai = sum((u["cost_eur"] for u in self.ai_usage if u["created_at"] >= since), Decimal(0))
        return Decimal(search), Decimal(ai)

    async def month_google_requests(self, since: datetime) -> int:
        return sum(int(r.get("pages") or 0) for r in self.search_runs.values() if r["started_at"] >= since)

    async def start_search_run(self, *, zone: str, query: str, cell: str | None, provincia: str | None) -> str:
        run_id = str(uuid.uuid4())
        self.search_runs[run_id] = {
            "zone": zone, "query": query, "cell": cell, "provincia": provincia, "status": "in_corso",
            "started_at": datetime.now(UTC), "cost_eur": Decimal(0),
        }
        return run_id

    async def finish_search_run(
        self,
        run_id: str,
        *,
        status: str,
        results: int,
        new: int,
        known: int,
        excluded: int,
        pages: int,
        cost_eur: Decimal,
        error: str | None = None,
        reviews_raw: int | None = None,
        reviews_text: int | None = None,
    ) -> None:
        self.search_runs[run_id].update(
            status=status, results=results, new=new, known=known, excluded=excluded, pages=pages,
            cost_eur=cost_eur, error=error, reviews_raw=reviews_raw, reviews_text=reviews_text,
        )

    async def record_ai_usage(
        self,
        *,
        purpose: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_eur: Decimal,
        property_id: str | None,
        request_id: str | None,
    ) -> None:
        self.ai_usage.append(
            {
                "purpose": purpose, "model": model, "input_tokens": input_tokens, "output_tokens": output_tokens,
                "cost_eur": cost_eur, "property_id": property_id, "request_id": request_id,
                "created_at": datetime.now(UTC),
            }
        )
