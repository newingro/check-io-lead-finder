"""Fase 3 — analisi di una struttura con Claude: profilo, recensioni, segnali, esclusioni e punteggio."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.ai.client import AIError, BudgetExceeded, ClaudeJSON
from app.ai.prompts import ANALYSIS_SCHEMA, analysis_system, as_prompt
from app.db.repository import Repository
from app.domain.dedupe import is_mobile
from app.domain.models import Property, short_term_proof

log = logging.getLogger(__name__)


def _clamp(value: Any) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return 0


def analysis_payload(
    prop: Property,
    reviews: list[dict[str, Any]],
    pasted_text: str | None = None,
    pasted_link: str | None = None,
    pasted_kind: str = "annuncio",
) -> dict[str, Any]:
    site = prop.website_check or {}
    google = prop.google_rating
    payload: dict[str, Any] = {
        "nome": prop.name,
        "tipo_secondo_google": prop.property_type or "non noto",
        "indirizzo": prop.address or "non noto",
        "zona_di_ricerca": prop.zone or "non nota",
        "sito_proprio": prop.website or "nessuno",
        "dal_sito": {
            "letto": bool(site.get("letto")),
            "email_pubblicata": bool(site.get("email")),
            "portali_collegati": sorted((site.get("portali") or {}).keys()),
            "cin_trovato": bool(site.get("cin")),
            "whatsapp_sul_sito": bool(site.get("whatsapp")),
        },
        "altri_annunci_noti": sorted(k for k in prop.listing_urls if k != "google_maps"),
        "scheda_google": {
            "voto": google.get("voto"),
            "numero_recensioni": google.get("recensioni"),
        },
        "recensioni_google_lette": reviews,
        "testi_recensioni_disponibili": bool(reviews) or bool(pasted_text and pasted_kind == "recensioni"),
        "nota": "Google fornisce al massimo 5 recensioni, scelte da Google, e spesso nessun testo. "
        "I nomi degli autori sono stati rimossi.",
    }
    if pasted_text and pasted_kind == "recensioni":
        payload["recensioni_copiate_dal_commerciale"] = pasted_text[:12000]
    elif pasted_text:
        payload["testo_incollato_dal_commerciale"] = {"link": pasted_link or "non indicato", "testo": pasted_text[:12000]}
    return payload


class AnalysisService:
    def __init__(self, repo: Repository, ai: ClaudeJSON) -> None:
        self.repo = repo
        self.ai = ai

    async def discard(self, prop: Property, reason: str, label: str, actor: str = "bot") -> None:
        await self.repo.update_property(prop.id, status="scartato", discard_reason=reason)
        await self.repo.add_property_event(
            prop.id, actor_id=None, actor_label=actor, source="bot", event_type="esclusa",
            from_status=prop.status, to_status="scartato", details={"motivo": reason, "spiegazione": label},
        )

    async def analyze(
        self,
        prop: Property,
        reviews: list[dict[str, Any]],
        *,
        pasted_text: str | None = None,
        pasted_link: str | None = None,
        pasted_kind: str = "annuncio",
        require_contacts: bool = True,
    ) -> Property:
        """Analizza e salva. Restituisce la struttura aggiornata. Può sollevare BudgetExceeded."""
        if require_contacts and not prop.phone_normalized and not prop.email_normalized:
            await self.discard(prop, "senza_contatti", "Nessun telefono o email pubblici: non si può contattare.")
            return await self.repo.get_property(prop.id) or prop
        if require_contacts and not is_mobile(prop.phone_normalized):
            # per ora si lavora solo su WhatsApp: niente analisi (e niente spesa) per fissi o sola email
            await self.discard(prop, "senza_cellulare", "Nessun cellulare pubblico (solo fisso o email): niente WhatsApp.")
            return await self.repo.get_property(prop.id) or prop
        if require_contacts and not short_term_proof(prop.cin, prop.listing_urls):
            # si lavora solo su chi affitta davvero sulle piattaforme: annuncio su Booking/Airbnb… o CIN
            await self.discard(
                prop, "senza_affitto_breve", "Nessun segno di affitto breve (né annunci su Booking/Airbnb né CIN)."
            )
            return await self.repo.get_property(prop.id) or prop
        try:
            result = await self.ai.ask(
                purpose="analisi",
                system=analysis_system(),
                prompt=as_prompt("Dati della struttura da analizzare:", analysis_payload(prop, reviews, pasted_text, pasted_link, pasted_kind)),
                schema=ANALYSIS_SCHEMA,
                property_id=prop.id,
            )
        except BudgetExceeded:
            raise
        except AIError as exc:
            await self.repo.update_property(prop.id, status="errore")
            await self.repo.add_property_event(
                prop.id, actor_id=None, actor_label="bot", source="bot", event_type="errore_analisi",
                from_status=prop.status, to_status="errore", details={"errore": str(exc)},
            )
            return await self.repo.get_property(prop.id) or prop

        analysis = result.data
        exclusion = analysis.get("esclusione") or {}
        score = 0 if exclusion.get("escludi") else _clamp(analysis.get("punteggio"))
        owner = (analysis.get("profilo") or {}).get("gestore_probabile")
        fields: dict[str, Any] = {
            "analysis": analysis,
            "score": score,
            "score_reasons": [str(m) for m in analysis.get("motivi") or []][:8],
            "owner_type": owner if owner in ("privato", "professionale") else None,
            "analyzed_at": datetime.now(UTC),
        }
        name_from_text = str(analysis.get("nome_dal_testo") or "").strip()
        if pasted_text and name_from_text and prop.name.startswith("Annuncio"):
            fields["name"] = name_from_text[:120]
        if exclusion.get("escludi"):
            fields.update(status="scartato", discard_reason=exclusion.get("motivo") or "fuori_target")
        else:
            fields["status"] = "analizzato"
        await self.repo.update_property(prop.id, **fields)
        await self.repo.add_property_event(
            prop.id, actor_id=None, actor_label="bot", source="bot",
            event_type="esclusa" if exclusion.get("escludi") else "analizzata",
            from_status=prop.status, to_status=fields["status"],
            details={"punteggio": score, "costo_eur": str(result.cost_eur), "modello": result.model,
                     **({"motivo": exclusion.get("motivo")} if exclusion.get("escludi") else {})},
        )
        return await self.repo.get_property(prop.id) or prop
