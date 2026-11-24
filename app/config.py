"""Configurazione letta dalle variabili d'ambiente del server.

Nessun segreto è scritto nel codice: token e connessioni si inseriscono
nelle variabili del server (Railway → Variables).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo


class ConfigError(RuntimeError):
    """Configurazione mancante o non valida."""


@dataclass(frozen=True)
class Config:
    telegram_token: str
    database_url: str
    owner_setup_code: str | None
    timezone: ZoneInfo
    settings_poll_seconds: int
    link_code_ttl_minutes: int
    log_level: str
    # Fasi 2-4 (facoltative: senza queste chiavi il bot funziona ma non cerca e non analizza)
    google_maps_api_key: str | None = None
    google_search_usd_per_1000: Decimal | None = None
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "medium"
    eur_per_usd: Decimal = Decimal(1)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        env = dict(os.environ if env is None else env)
        missing = [name for name in ("TELEGRAM_BOT_TOKEN", "DATABASE_URL") if not env.get(name)]
        if missing:
            raise ConfigError(f"Variabili mancanti: {', '.join(missing)}")

        setup_code = (env.get("OWNER_SETUP_CODE") or "").strip() or None
        if setup_code is not None and len(setup_code) < 12:
            raise ConfigError("OWNER_SETUP_CODE deve avere almeno 12 caratteri.")

        try:
            timezone = ZoneInfo(env.get("TIMEZONE", "Europe/Rome"))
        except Exception as exc:  # noqa: BLE001
            raise ConfigError("TIMEZONE non valido (esempio: Europe/Rome).") from exc

        return cls(
            telegram_token=env["TELEGRAM_BOT_TOKEN"].strip(),
            database_url=env["DATABASE_URL"].strip(),
            owner_setup_code=setup_code,
            timezone=timezone,
            settings_poll_seconds=_int(env, "SETTINGS_POLL_SECONDS", 300, minimum=30),
            link_code_ttl_minutes=_int(env, "LINK_CODE_TTL_MINUTES", 15, minimum=1),
            log_level=env.get("LOG_LEVEL", "INFO").upper(),
            google_maps_api_key=(env.get("GOOGLE_MAPS_API_KEY") or "").strip() or None,
            google_search_usd_per_1000=_decimal(env, "GOOGLE_TEXT_SEARCH_USD_PER_1000"),
            anthropic_api_key=(env.get("ANTHROPIC_API_KEY") or "").strip() or None,
            claude_model=(env.get("CLAUDE_MODEL") or "claude-opus-5-5").strip(),
            claude_effort=_choice(env, "CLAUDE_EFFORT", "medium", ("low", "medium", "high", "xhigh", "max")),
            eur_per_usd=_decimal(env, "EUR_PER_USD") or Decimal(1),
        )


def _int(env: dict[str, str], name: str, default: int, *, minimum: int) -> int:
    raw = env.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} deve essere un numero intero.") from exc
    if value < minimum:
        raise ConfigError(f"{name} deve essere almeno {minimum}.")
    return value


def _decimal(env: dict[str, str], name: str) -> Decimal | None:
    raw = (env.get(name) or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ConfigError(f"{name} deve essere un numero (esempio: 12.5).") from exc
    if value <= 0:
        raise ConfigError(f"{name} deve essere maggiore di zero.")
    return value


def _choice(env: dict[str, str], name: str, default: str, allowed: tuple[str, ...]) -> str:
    value = (env.get(name) or default).strip().lower()
    if value not in allowed:
        raise ConfigError(f"{name} deve essere uno tra: {', '.join(allowed)}.")
    return value
