"""Fase 4 — messaggi personalizzati (WhatsApp, email, scheda telefonata) in versione A o B.

Versione A: propone un'analisi gratuita della struttura.
Versione B: propone una chiacchierata di 10 minuti.
La versione si registra per capire quale funziona meglio. Dopo la scrittura, i controlli
automatici (app/ai/guard.py) verificano le regole; se qualcosa non va, Claude riscrive una
volta con l'elenco dei problemi; se resta qualcosa, la scheda lo segnala al commerciale.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

from app.ai.client import AIError, ClaudeJSON
from app.ai.guard import allowed_numbers, check_messages
from app.ai.prompts import MESSAGE_SCHEMA, as_prompt, message_system
from app.db.repository import Repository
from app.domain.models import Property


def message_payload(prop: Property) -> dict[str, Any]:
    analysis = prop.analysis or {}
    reviews = analysis.get("recensioni") or {}
    return {
        "struttura": {
            "nome": prop.name,
            "tipo": (analysis.get("profilo") or {}).get("tipo") or prop.property_type or "non noto",
            "zona": prop.zone,
            "indirizzo": prop.address,
            "scheda_google": prop.google_rating,
        },
        "analisi": {
            "sintesi": analysis.get("sintesi"),
            "temi_negativi": reviews.get("temi_negativi") or [],
            "temi_positivi": reviews.get("temi_positivi") or [],
            "recensioni_lette": reviews.get("lette"),
            "segnali_opportunita": analysis.get("segnali_opportunita") or [],
            "gestore_probabile": (analysis.get("profilo") or {}).get("gestore_probabile"),
        },
        "canali_disponibili": {
            "telefono": bool(prop.phone_normalized),
            "email": bool(prop.email_normalized),
        },
    }


class MessageService:
    def __init__(self, repo: Repository, ai: ClaudeJSON, rng: random.Random | None = None) -> None:
        self.repo = repo
        self.ai = ai
        self.rng = rng or random.Random()

    def pick_variant(self) -> str:
        return self.rng.choice(["A", "B"])

    async def write(self, prop: Property, sender: str, variant: str | None = None) -> dict[str, Any]:
        """Scrive e salva i messaggi. Restituisce il contenuto salvato in properties.messages."""
        variant = variant or prop.message_variant or self.pick_variant()
        payload = message_payload(prop)
        allowed = allowed_numbers(payload, prop.analysis or {})
        prompt = as_prompt("Struttura e analisi:", payload)
        result = await self.ai.ask(
            purpose="messaggi", system=message_system(variant, sender), prompt=prompt,
            schema=MESSAGE_SCHEMA, property_id=prop.id,
        )
        messages = result.data
        problems = check_messages(messages, sender=sender, allowed=allowed)
        cost = result.cost_eur
        if problems:
            retry_prompt = (
                prompt + "\n\nLa versione precedente non rispettava queste regole, correggi:\n- "
                + "\n- ".join(problems)
                + "\n\nVersione precedente:\n" + as_prompt("", messages)
            )
            try:
                retry = await self.ai.ask(
                    purpose="messaggi_correzione", system=message_system(variant, sender), prompt=retry_prompt,
                    schema=MESSAGE_SCHEMA, property_id=prop.id,
                )
                cost += retry.cost_eur
                retry_problems = check_messages(retry.data, sender=sender, allowed=allowed)
                if len(retry_problems) <= len(problems):
                    messages, problems = retry.data, retry_problems
            except AIError:
                pass
        saved = {
            **messages,
            "variante": variant,
            "mittente": sender,
            "da_ricontrollare": problems,
            "scritto_il": datetime.now(UTC).isoformat(),
        }
        await self.repo.update_property(prop.id, messages=saved, message_variant=variant, message_edited=False)
        await self.repo.add_property_event(
            prop.id, actor_id=None, actor_label="bot", source="bot", event_type="messaggi_scritti",
            details={"variante": variant, "costo_eur": str(cost), "da_ricontrollare": problems},
        )
        return saved
