"""Interfaccia di accesso ai dati, comune al database vero e a quello di prova."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from app.domain.dedupe import Candidate
from app.domain.models import LeadFinder, Property, Settings, State
from app.domain.radar import CellMemory


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

    # Radar: province e memoria delle ricerche
    async def province_cells(self, codes: list[str]) -> dict[str, list[str]]: ...
    async def province_for_cells(self, cells: list[str]) -> dict[str, str]: ...
    async def get_cell_memory(self, cells: list[str], queries: list[str]) -> dict[tuple[str, str], CellMemory]: ...
    async def save_cell_memory(self, memory: CellMemory, results: int, new: int) -> None: ...

    # Memoria delle strutture
    async def find_fingerprints(self, prints: list[tuple[str, str]]) -> dict[tuple[str, str], str | None]: ...
    async def touch_property(self, property_id: str | None, prints: list[tuple[str, str]]) -> None: ...
    async def is_opted_out(self, phone: str | None, email: str | None) -> bool: ...
    async def insert_property(
        self,
        candidate: Candidate,
        prints: list[tuple[str, str]],
        *,
        cell: str,
        provincia: str | None,
        zone: str,
        query: str,
    ) -> str | None: ...
    async def purge_expired(self) -> int: ...

    # Strutture
    async def get_property(self, property_id: str) -> Property | None: ...
    async def properties_by_status(self, status: str, limit: int) -> list[Property]: ...
    async def update_property(self, property_id: str, **fields: Any) -> None: ...
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
    ) -> None: ...
    async def proposal_candidates(self, min_score: int, limit: int) -> list[Property]: ...
    async def open_assignments(self) -> dict[str, int]: ...
    async def add_opt_out(self, phone: str | None, email: str | None, reason: str, member_id: str | None) -> None: ...
    async def insert_manual_property(
        self, name: str, listing_urls: dict[str, str], prints: list[tuple[str, str]], cin: str | None, member_id: str
    ) -> str | None: ...

    # Costi
    async def month_costs(self, since: datetime) -> tuple[Decimal, Decimal]: ...
    async def month_google_requests(self, since: datetime) -> int: ...
    async def start_search_run(self, *, zone: str, query: str, cell: str | None, provincia: str | None) -> str: ...
    async def recent_details_runs(self, limit: int) -> list[int]:
        """Recensioni con testo delle ultime letture di schede singole (dalla più recente)."""
        ...

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
    ) -> None: ...
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
    ) -> None: ...
