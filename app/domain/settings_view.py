"""Impostazioni e stato in italiano semplice, e confronto tra versioni."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from .models import Settings, State


def _zones(value: list[dict[str, Any]]) -> str:
    active = [z for z in value if z.get("attiva", True)]
    if not active:
        return "nessuna (da impostare dal gestionale)"
    return ", ".join(
        f"{z.get('nome', '?')}" + (f" ({z['raggio_km']} km)" if z.get("raggio_km") else "") for z in active
    )


def _list(value: list[str]) -> str:
    return ", ".join(value) if value else "nessuno"


def _euro(value: Decimal | float | int) -> str:
    return f"{Decimal(value):.2f} €".replace(".", ",")


def _days(value: int) -> str:
    return f"{value} giorn{'o' if value == 1 else 'i'}"


SETTINGS_FIELDS: list[tuple[str, str, Callable[[Any], str]]] = [
    ("zones", "Zone", _zones),
    ("property_types", "Tipi di struttura", _list),
    ("search_queries", "Ricerche", _list),
    ("min_score", "Punteggio minimo", str),
    ("cards_per_run", "Schede per giro", str),
    ("run_days", "Giorni dei giri", _list),
    ("run_times", "Orari dei giri", _list),
    ("followup_days", "Follow-up dopo", _days),
    ("max_followups", "Follow-up massimi", str),
    ("archive_after_days", "Archivio dopo", _days),
    ("max_call_attempts", "Tentativi di chiamata", str),
    ("call_retry_minutes", "Richiamo dopo (minuti)", str),
    ("monthly_ai_budget_eur", "Tetto mensile AI", _euro),
    ("monthly_search_budget_eur", "Tetto mensile ricerche", _euro),
    ("data_retention_months", "Conservazione dati (mesi)", str),
]


def format_settings(settings: Settings) -> str:
    lines = [f"• {label}: {fmt(getattr(settings, name))}" for name, label, fmt in SETTINGS_FIELDS]
    return "\n".join(lines)


def format_state(state: State) -> str:
    status = "⏸ in pausa" if state.paused else "▶️ attivi"
    return f"• Giri: {status}\n• Modalità: {state.mode}"


def diff_settings(old: Settings, new: Settings) -> list[str]:
    changes: list[str] = []
    for name, label, fmt in SETTINGS_FIELDS:
        before, after = getattr(old, name), getattr(new, name)
        if before != after:
            changes.append(f"• {label}: {fmt(before)} → {fmt(after)}")
    return changes


def diff_state(old: State, new: State) -> list[str]:
    changes: list[str] = []
    if old.paused != new.paused:
        changes.append("• Giri: " + ("messi in pausa ⏸" if new.paused else "ripresi ▶️"))
    if old.mode != new.mode:
        changes.append(f"• Modalità: {old.mode} → {new.mode}")
    return changes
