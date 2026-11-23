"""Configurazione letta dalle variabili d'ambiente del server.

Nessun segreto è scritto nel codice: token e connessioni si inseriscono
nelle variabili del server (Railway → Variables).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
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
