"""Scheda Telegram di una struttura: testo (HTML) e pulsanti, a seconda dello stato."""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.domain.models import Property

THEME_LABELS = {
    "pulizia": "pulizia",
    "check-in": "check-in",
    "chiavi": "chiavi",
    "comunicazione": "comunicazione",
    "rumore": "rumore",
    "wifi": "wifi",
    "biancheria": "biancheria",
    "clima": "aria condizionata/riscaldamento",
    "foto_diverse": "foto diverse dalla realtà",
    "altro": "altro",
}
STATUS_LINES = {
    "approvato": "✅ Approvata: apri WhatsApp o copia l'email, invia tu, poi segna «Inviato».",
    "contattato": "📤 Contattata",
    "scartato": "❌ Scartata",
    "perso": "🚫 Non va contattata",
}
WA_URL_LIMIT = 2000


def e(value: Any) -> str:
    return escape(str(value), quote=True)


def whatsapp_url(prop: Property) -> str | None:
    if not prop.phone_normalized:
        return None
    digits = prop.phone_normalized.lstrip("+")
    text = str((prop.messages or {}).get("whatsapp") or "")
    url = f"https://wa.me/{digits}?text={quote(text)}" if text else f"https://wa.me/{digits}"
    return url if len(url) <= WA_URL_LIMIT else f"https://wa.me/{digits}"


def card_text(prop: Property, mode: str, assignee: str | None = None, status_note: str | None = None) -> str:
    analysis = prop.analysis or {}
    reviews = analysis.get("recensioni") or {}
    kind = (analysis.get("profilo") or {}).get("tipo") or prop.property_type
    lines = [f"🏠 <b>{e(prop.name)}</b>" + (f" · {e(kind)}" if kind and kind != "non_noto" else "")]
    if prop.address:
        lines.append(f"📍 {e(prop.address)}")
    google = prop.google_rating
    if google.get("voto"):
        lines.append(f"⭐ {e(google['voto'])} su Google ({e(google.get('recensioni') or 0)} recensioni)")
    contacts = []
    if prop.phone:
        contacts.append(f"📞 {e(prop.phone)}")
    if prop.email:
        contacts.append(f"✉️ {e(prop.email)}")
    if prop.website:
        contacts.append(f'🌐 <a href="{e(prop.website)}">sito</a>')
    if prop.listing_urls.get("google_maps"):
        contacts.append(f'<a href="{e(prop.listing_urls["google_maps"])}">Google Maps</a>')
    if contacts:
        lines.append(" · ".join(contacts))

    lines += ["", f"<b>Punteggio {e(prop.score if prop.score is not None else '—')}/100</b>"]
    lines += [e(reason) for reason in prop.score_reasons[:5]]
    themes = [
        f"{THEME_LABELS.get(t.get('tema'), t.get('tema'))} {t.get('volte')}/{t.get('su_quante')}"
        for t in reviews.get("temi_negativi") or []
        if t.get("volte")
    ]
    if themes:
        lines.append("Problemi nelle recensioni lette: " + e(", ".join(themes)))
    if analysis.get("sintesi"):
        lines += ["", f"<i>{e(analysis['sintesi'])}</i>"]

    messages = prop.messages or {}
    if messages:
        lines.append("")
        if mode == "telefonate" or not prop.phone_normalized:
            if mode == "telefonate" and (messages.get("telefono") or {}).get("apertura"):
                lines += ["📞 <b>Apertura della telefonata</b>", f"<blockquote>{e(messages['telefono']['apertura'])}</blockquote>"]
            elif (messages.get("email") or {}).get("oggetto"):
                lines += [f"✉️ <b>Email</b> — {e(messages['email']['oggetto'])}", "Premi «📧 Email» per il testo completo."]
        else:
            text = str(messages.get("whatsapp") or "")[:1500]
            lines += ["💬 <b>Messaggio WhatsApp</b>" + (" (modificato)" if prop.message_edited else ""), f"<blockquote>{e(text)}</blockquote>"]
        problems = messages.get("da_ricontrollare") or []
        if problems:
            lines.append("⚠️ Da ricontrollare: " + e("; ".join(problems[:4])))
        footer = f"Versione {e(messages.get('variante', '?'))}"
        if assignee:
            footer += f" · per {e(assignee)}"
        lines.append(f"<i>{footer}</i>")

    note = status_note or STATUS_LINES.get(prop.status)
    if note:
        lines += ["", e(note)]
    return "\n".join(lines)[:4000]


def _btn(label: str, action: str, prop: Property) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=f"c:{action}:{prop.id}")


def card_keyboard(prop: Property) -> InlineKeyboardMarkup | None:
    if prop.status == "proposto":
        return InlineKeyboardMarkup(
            [
                [_btn("✅ Approva", "ok", prop), _btn("✏️ Modifica", "ed", prop), _btn("❌ Scarta", "no", prop)],
                [_btn("📧 Email", "em", prop), _btn("📞 Telefonata", "tel", prop), _btn("📝 Recensioni", "rv", prop)],
                [_btn("🏢 Già gestita da altri", "pm", prop), _btn("🚫 Non contattare", "oo", prop)],
            ]
        )
    if prop.status == "approvato":
        rows = []
        url = whatsapp_url(prop)
        if url:
            rows.append([InlineKeyboardButton("💬 Apri WhatsApp", url=url), _btn("✅ Inviato su WhatsApp", "sw", prop)])
        if prop.email:
            rows.append([_btn("📧 Testo email", "em", prop), _btn("✅ Inviata email", "se", prop)])
        rows.append([_btn("📞 Telefonata", "tel", prop), _btn("✏️ Modifica", "ed", prop), _btn("❌ Scarta", "no", prop)])
        rows.append([_btn("📝 Recensioni", "rv", prop), _btn("🚫 Non contattare", "oo", prop)])
        return InlineKeyboardMarkup(rows)
    if prop.status == "contattato":
        return InlineKeyboardMarkup([[_btn("📞 Telefonata", "tel", prop), _btn("🚫 Non contattare", "oo", prop)]])
    return None


def edit_choice_keyboard(prop: Property) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("💬 Testo WhatsApp", "ew", prop), _btn("✉️ Testo email", "ee", prop)]])


def email_text(prop: Property) -> str:
    email = (prop.messages or {}).get("email") or {}
    to = f"A: {e(prop.email)}\n" if prop.email else "Email della struttura non trovata: cercala sul sito o chiedila al telefono.\n"
    return (
        f"✉️ <b>Email per {e(prop.name)}</b>\n{to}"
        f"Oggetto: <code>{e(email.get('oggetto', ''))}</code>\n\n"
        f"<pre>{e(email.get('corpo', ''))}</pre>\n\nTocca il testo per copiarlo, poi incollalo nella tua email."
    )


OBJECTION_LABELS = {
    "ci_penso_io": "«Ci penso io»",
    "ho_gia_provato_agenzia": "«Ho già provato un'agenzia»",
    "non_voglio_dare_le_chiavi": "«Non voglio dare le chiavi»",
    "quanto_costa": "«Quanto costa?»",
}


def phone_text(prop: Property) -> str:
    phone = (prop.messages or {}).get("telefono") or {}
    lines = [f"📞 <b>Telefonata a {e(prop.name)}</b>" + (f" — {e(prop.phone)}" if prop.phone else "")]
    if phone.get("apertura"):
        lines += ["", "<b>Apertura</b>", e(phone["apertura"])]
    if phone.get("domande"):
        lines += ["", "<b>Domande</b>"] + [f"• {e(q)}" for q in phone["domande"]]
    if phone.get("obiezioni"):
        lines += ["", "<b>Obiezioni</b>"]
        for item in phone["obiezioni"]:
            lines.append(f"{OBJECTION_LABELS.get(item.get('obiezione'), e(item.get('obiezione')))}: {e(item.get('risposta', ''))}")
    lines += ["", "Ricorda: rispetta il Registro delle opposizioni e chi chiede di non essere richiamato."]
    return "\n".join(lines)[:4000]
