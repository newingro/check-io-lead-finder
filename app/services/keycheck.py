"""Verifica delle chiavi senza spendere.

- Anthropic: si legge la scheda del modello (API dei modelli). Claude non scrive niente,
  quindi non si consumano token.
- Google: si manda una ricerca volutamente vuota. Google controlla prima la chiave, il
  progetto e la fatturazione, poi la rifiuta perché manca il testo: nessuna ricerca eseguita.

Il risultato va su Telegram al titolare e nel registro (audit_log, azione «verifica_chiavi»).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.integrations.google_places import TEXT_SEARCH_URL


@dataclass(frozen=True)
class KeyStatus:
    name: str
    ok: bool | None  # None = chiave non impostata
    message: str


GOOGLE_REASONS = {
    "API_KEY_INVALID": "la chiave non è valida: ricopiala da Google Cloud → Credenziali",
    "SERVICE_DISABLED": "«Places API (New)» non è attiva nel progetto: API e servizi → Libreria → Abilita",
    "API_KEY_SERVICE_BLOCKED": "la chiave è limitata ad altre API: aggiungi «Places API (New)» nelle limitazioni della chiave",
    "BILLING_DISABLED": "la fatturazione del progetto non è attiva: Google Cloud → Fatturazione",
    "API_KEY_HTTP_REFERRER_BLOCKED": "la chiave è limitata ai siti web: in «Limitazioni delle applicazioni» scegli «Nessuna»",
    "API_KEY_IP_ADDRESS_BLOCKED": "la chiave è limitata ad alcuni indirizzi IP: in «Limitazioni delle applicazioni» scegli «Nessuna»",
    "API_KEY_ANDROID_APP_BLOCKED": "la chiave è limitata alle app Android: in «Limitazioni delle applicazioni» scegli «Nessuna»",
    "API_KEY_IOS_APP_BLOCKED": "la chiave è limitata alle app iOS: in «Limitazioni delle applicazioni» scegli «Nessuna»",
}


def _google_reason(body: dict[str, Any]) -> str | None:
    for detail in (body.get("error") or {}).get("details") or []:
        reason = detail.get("reason")
        if reason:
            return str(reason)
    return None


async def check_google(api_key: str | None, http: httpx.AsyncClient) -> KeyStatus:
    if not api_key:
        return KeyStatus("Google Maps", None, "chiave non impostata (GOOGLE_MAPS_API_KEY)")
    try:
        response = await http.post(
            TEXT_SEARCH_URL,
            json={"textQuery": ""},
            headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": "places.id"},
        )
    except httpx.HTTPError as exc:
        return KeyStatus("Google Maps", False, f"Google non raggiungibile ({exc.__class__.__name__})")
    if response.status_code == 200:
        return KeyStatus("Google Maps", True, "chiave valida e Places API (New) attiva")
    try:
        body = response.json()
    except ValueError:
        body = {}
    reason = _google_reason(body)
    if reason in GOOGLE_REASONS:
        return KeyStatus("Google Maps", False, GOOGLE_REASONS[reason])
    status = (body.get("error") or {}).get("status")
    if response.status_code == 400 and status == "INVALID_ARGUMENT":
        # La ricerca vuota è stata rifiutata dopo i controlli di chiave, progetto e fatturazione.
        return KeyStatus("Google Maps", True, "chiave valida e Places API (New) attiva")
    message = str((body.get("error") or {}).get("message") or "")[:200]
    return KeyStatus("Google Maps", False, f"Google ha risposto {response.status_code}: {message or 'errore'}")


async def check_anthropic(client: Any | None, model: str) -> KeyStatus:
    if client is None:
        return KeyStatus("Anthropic (Claude)", None, "chiave non impostata (ANTHROPIC_API_KEY)")
    import anthropic

    try:
        info = await client.models.retrieve(model)
    except anthropic.AuthenticationError:
        return KeyStatus("Anthropic (Claude)", False, "la chiave non è valida: creane una nuova su console.anthropic.com")
    except anthropic.PermissionDeniedError:
        return KeyStatus("Anthropic (Claude)", False, "la chiave non ha i permessi per usare l'API")
    except anthropic.NotFoundError:
        return KeyStatus("Anthropic (Claude)", False, f"il modello {model} non è disponibile per questa chiave")
    except anthropic.APIError as exc:
        return KeyStatus("Anthropic (Claude)", False, f"Anthropic non raggiungibile ({exc.__class__.__name__})")
    name = getattr(info, "display_name", None) or model
    return KeyStatus("Anthropic (Claude)", True, f"chiave valida, modello {name} disponibile")


def google_mode(price_set: bool, monthly_requests: int) -> str:
    if monthly_requests > 0:
        return f"🔎 Ricerca Google: al massimo {monthly_requests} richieste al mese (poi si ferma da sola)."
    if price_set:
        return "🔎 Ricerca Google: conto della spesa col prezzo impostato e tetto in euro del gestionale."
    return (
        "➖ Ricerca Google spenta: nel gestionale (Impostazioni) imposta il massimo di richieste Google al mese, "
        "cioè le gratuite. Nessuna spesa su Google."
    )


def format_statuses(statuses: list[KeyStatus], google_note: str) -> str:
    icon = {True: "✅", False: "❌", None: "➖"}
    lines = ["🔑 Verifica delle chiavi (nessuna spesa)"]
    lines += [f"{icon[s.ok]} {s.name}: {s.message}" for s in statuses]
    lines.append(google_note)
    return "\n".join(lines)
