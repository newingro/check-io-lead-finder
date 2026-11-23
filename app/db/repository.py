"""Interfaccia di accesso ai dati, comune al database vero e a quello di prova."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.domain.models import LeadFinder, Settings, State


class AlreadyLinkedError(Exception):
    """L'account Telegram è già collegato a un'altra persona."""


class CodeAlreadyUsedError(Exception):
    """Il codice è stato usato nel frattempo da qualcun altro."""


@dataclass(frozen=True)
class LinkTarget:
    """Esito della ricerca di un codice di collegamento."""

    code_id: str
    lead_finder: LeadFinder
    expires_at: datetime
    used_at: datetime | None


class Repository(Protocol):
    # Persone
    async def get_member_by_telegram(self, telegram_user_id: int) -> LeadFinder | None: ...
    async def get_member_by_name(self, name: str) -> LeadFinder | None: ...
    async def list_members(self) -> list[LeadFinder]: ...
    async def count_linked_owners(self) -> int: ...
    async def create_member(self, name: str, role: str, shifts: dict[str, Any]) -> LeadFinder: ...
    async def update_member_chat(self, member_id: str, chat_id: int, username: str | None) -> None: ...

    # Codici di collegamento
    async def create_link_code(
        self, member_id: str, code_hash: str, expires_at: datetime, created_by: str | None
    ) -> None: ...
    async def find_link_code(self, code_hash: str) -> LinkTarget | None: ...
    async def complete_link(
        self, code_id: str, member_id: str, telegram_user_id: int, chat_id: int, username: str | None
    ) -> LeadFinder: ...
    async def link_member_directly(
        self, member_id: str, telegram_user_id: int, chat_id: int, username: str | None
    ) -> LeadFinder: ...

    # Impostazioni e stato
    async def get_settings(self) -> Settings: ...
    async def get_state(self) -> State: ...
    async def update_state(self, *, paused: bool | None, mode: str | None, updated_by: str) -> State: ...

    # Registro
    async def add_audit(
        self, actor_id: str | None, actor_label: str, source: str, action: str, details: dict[str, Any]
    ) -> None: ...
