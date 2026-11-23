"""Modelli dei dati usati dal bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

ROLE_OWNER = "titolare"
ROLE_SALES = "commerciale"
ROLES = (ROLE_OWNER, ROLE_SALES)

MODES = ("telefonate", "messaggi", "misto")


@dataclass(frozen=True)
class LeadFinder:
    id: str
    name: str
    role: str
    telegram_user_id: int | None = None
    telegram_chat_id: int | None = None
    telegram_username: str | None = None
    shifts: dict[str, list[list[str]]] = field(default_factory=dict)
    receives_cards: bool = True
    receives_daily_summary: bool = False
    is_active: bool = True
    linked_at: datetime | None = None

    @property
    def is_owner(self) -> bool:
        return self.role == ROLE_OWNER

    @property
    def is_linked(self) -> bool:
        return self.telegram_user_id is not None


@dataclass(frozen=True)
class Settings:
    zones: list[dict[str, Any]]
    property_types: list[str]
    search_queries: list[str]
    min_score: int
    cards_per_run: int
    run_times: list[str]
    run_days: list[str]
    followup_days: int
    max_followups: int
    archive_after_days: int
    max_call_attempts: int
    call_retry_minutes: int
    monthly_ai_budget_eur: Decimal
    monthly_search_budget_eur: Decimal
    data_retention_months: int
    version: int
    updated_by: str | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class State:
    paused: bool
    mode: str
    version: int
    updated_by: str | None = None
    updated_at: datetime | None = None
