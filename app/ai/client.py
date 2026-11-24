"""Chiamate a Claude con risposta in JSON strutturato, costo registrato e tetto di spesa mensile.

- Modello predefinito: claude-opus-5-5 (si cambia con la variabile CLAUDE_MODEL).
- Ogni chiamata finisce in ai_usage con i token e il costo in euro.
- Prima di ogni chiamata si controlla la spesa del mese: oltre il tetto non si chiama.
- Se Claude rifiuta una richiesta per i suoi controlli di sicurezza, il server di Anthropic
  la ripete in automatico su un modello di riserva («fallbacks: default»).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import anthropic

from app.db.repository import Repository

log = logging.getLogger(__name__)

# Prezzi in dollari per milione di token (ingresso, uscita), listino Anthropic al 3/11/2026.
PRICES_USD_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-5-5": (Decimal("4"), Decimal("20")),
    "claude-opus-5": (Decimal("5"), Decimal("25")),
    "claude-opus-4-8": (Decimal("5"), Decimal("25")),
    "claude-opus-4-7": (Decimal("5"), Decimal("25")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10")),
    "claude-sonnet-5": (Decimal("2"), Decimal("10")),
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "claude-fable-5-2": (Decimal("8"), Decimal("40")),
}
# Modello sconosciuto (per esempio una riserva nuova): si conta col prezzo più alto, per prudenza.
FALLBACK_PRICE = max(PRICES_USD_PER_MTOK.values())
CACHE_WRITE_FACTOR = Decimal("1.25")

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIError(Exception):
    """La risposta di Claude non è utilizzabile."""


class BudgetExceeded(AIError):
    """Tetto di spesa mensile raggiunto."""


@dataclass(frozen=True)
class AIResult:
    data: dict[str, Any]
    model: str
    cost_eur: Decimal
    input_tokens: int
    output_tokens: int


def month_start(now: datetime | None = None) -> datetime:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def cost_eur(model: str, usage: Any, eur_per_usd: Decimal) -> Decimal:
    price_in, price_out = PRICES_USD_PER_MTOK.get(model, FALLBACK_PRICE)
    tokens_in = Decimal(getattr(usage, "input_tokens", 0) or 0)
    cache_write = Decimal(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    cache_read = Decimal(getattr(usage, "cache_read_input_tokens", 0) or 0)
    tokens_out = Decimal(getattr(usage, "output_tokens", 0) or 0)
    usd = (
        tokens_in * price_in
        + cache_write * price_in * CACHE_WRITE_FACTOR
        + cache_read * price_in  # per prudenza al prezzo pieno (la cache non è attiva)
        + tokens_out * price_out
    ) / Decimal(1_000_000)
    return (usd * eur_per_usd).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)


class ClaudeJSON:
    def __init__(
        self,
        repo: Repository,
        client: Any,
        *,
        model: str,
        effort: str,
        eur_per_usd: Decimal,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repo = repo
        self.client = client
        self.model = model
        self.effort = effort
        self.eur_per_usd = eur_per_usd
        self.clock = clock or (lambda: datetime.now(UTC))
        self.use_fallbacks = True

    async def check_budget(self) -> None:
        settings = await self.repo.get_settings()
        _, spent = await self.repo.month_costs(month_start(self.clock()))
        if spent >= Decimal(settings.monthly_ai_budget_eur):
            raise BudgetExceeded(
                f"Tetto di spesa AI del mese raggiunto ({spent:.2f} € su {Decimal(settings.monthly_ai_budget_eur):.2f} €)."
            )

    async def ask(
        self,
        *,
        purpose: str,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        property_id: str | None = None,
        max_tokens: int = 16000,
    ) -> AIResult:
        await self.check_budget()
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
        }
        try:
            if self.use_fallbacks:
                try:
                    response = await self.client.beta.messages.create(
                        **request, betas=[FALLBACK_BETA], fallbacks="default"
                    )
                except anthropic.BadRequestError as exc:
                    if "fallback" not in str(exc).lower():
                        raise
                    log.warning("Riserva automatica non accettata: si prosegue senza (%s)", exc.__class__.__name__)
                    self.use_fallbacks = False
                    response = await self.client.beta.messages.create(**request)
            else:
                response = await self.client.beta.messages.create(**request)
        except anthropic.APIError as exc:
            if "credit balance" in str(exc).lower():
                raise AIError("Credito Anthropic esaurito: ricarica su console.anthropic.com → Billing.") from exc
            raise AIError(f"Claude non raggiungibile o richiesta rifiutata ({exc.__class__.__name__}).") from exc
        served = getattr(response, "model", None) or self.model
        cost = cost_eur(served, response.usage, self.eur_per_usd)
        await self.repo.record_ai_usage(
            purpose=purpose,
            model=served,
            input_tokens=int(getattr(response.usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(response.usage, "output_tokens", 0) or 0),
            cost_eur=cost,
            property_id=property_id,
            request_id=getattr(response, "_request_id", None),
        )
        if response.stop_reason == "refusal":
            raise AIError("Claude non ha risposto a questa richiesta (rifiuto di sicurezza).")
        if response.stop_reason == "max_tokens":
            raise AIError("Risposta troppo lunga, interrotta.")
        text = next((block.text for block in response.content if getattr(block, "type", None) == "text"), None)
        if not text:
            raise AIError("Risposta vuota.")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AIError("Risposta non in formato JSON.") from exc
        return AIResult(
            data=data,
            model=served,
            cost_eur=cost,
            input_tokens=int(response.usage.input_tokens or 0),
            output_tokens=int(response.usage.output_tokens or 0),
        )


AskFunction = Callable[..., Awaitable[AIResult]]
