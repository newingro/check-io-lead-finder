"""Database in memoria: usato nelle prove automatiche, senza rete."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.domain.models import ROLE_OWNER, LeadFinder, Settings, State

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
