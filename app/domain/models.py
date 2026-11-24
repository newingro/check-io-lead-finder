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
    searches_per_run: int = 4


@dataclass(frozen=True)
class State:
    paused: bool
    mode: str
    version: int
    updated_by: str | None = None
    updated_at: datetime | None = None


# ── Strutture ────────────────────────────────────────────────
STATUSES = (
    "nuovo", "analizzato", "proposto", "approvato", "scartato", "contattato", "followup",
    "richiamare", "risposto", "trattativa", "cliente", "perso", "errore",
)
OPEN_STATUSES = ("proposto", "approvato")


@dataclass
class Property:
    """Una struttura come la usa il bot (righe della tabella properties)."""

    id: str
    name: str
    status: str = "nuovo"
    property_type: str | None = None
    address: str | None = None
    zone: str | None = None
    provincia: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    phone: str | None = None
    phone_normalized: str | None = None
    email: str | None = None
    email_normalized: str | None = None
    website: str | None = None
    cin: str | None = None
    google_place_id: str | None = None
    ratings: dict[str, Any] = field(default_factory=dict)
    listing_urls: dict[str, str] = field(default_factory=dict)
    owner_type: str | None = None
    analysis: dict[str, Any] | None = None
    score: int | None = None
    score_reasons: list[str] = field(default_factory=list)
    assigned_to: str | None = None
    messages: dict[str, Any] = field(default_factory=dict)
    message_variant: str | None = None
    channel: str | None = None
    website_check: dict[str, Any] | None = None
    discard_reason: str | None = None
    source: str = "google_places"
    search_query: str | None = None
    times_seen: int = 1
    telegram_chat_id: int | None = None
    telegram_message_id: int | None = None
    message_edited: bool = False
    created_at: datetime | None = None
    contacted_at: datetime | None = None

    @property
    def google_rating(self) -> dict[str, Any]:
        return self.ratings.get("google") or {}
