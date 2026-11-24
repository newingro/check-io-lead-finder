"""Controlli automatici sui messaggi prima che arrivino al commerciale.

Non sostituiscono la lettura di una persona (l'invio resta sempre manuale), ma fermano
gli errori più gravi: numeri non presenti nei dati, percentuali o prezzi, frasi vietate,
mancanza di chi siamo / come ci ha trovato / come dire no, lunghezze sbagliate.
"""

from __future__ import annotations

import re
from typing import Any

BANNED = [
    "360",
    "massimizz",
    "garantit",
    "garantisc",
    "commission",
    "provvigion",
    "percentual",
    "ultimi posti",
    "solo per oggi",
    "offerta limitata",
    "affrettat",
    "non perda questa",
    "occasione unica",
]
OPT_OUT = re.compile(
    r"(non\s+(la|ti|vi)\s+(ri)?contatter|non\s+(le|ti|vi)\s+scriver|(ri)?contattat[oa]\s+più|"
    r"preferisce\s+non|non\s+desidera|no,?\s+grazie)",
    re.IGNORECASE,
)
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
ONLY_B = re.compile(r"\b10\s*minuti\b", re.IGNORECASE)  # la chiacchierata è della versione B
ONLY_A = re.compile(r"analisi\s+gratuit", re.IGNORECASE)  # l'analisi gratuita è della versione A
READ_REVIEWS = re.compile(r"\b(ho|abbiamo)\s+lett[oe]\b[^.\n]{0,40}\brecension", re.IGNORECASE)
# "10 minuti", "24/7" e il numero ufficiale di CHECK-iO (+39 352 255 4502), che va nella firma delle email.
ALWAYS_ALLOWED = {"10", "24", "7", "39", "352", "255", "4502"}


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in NUMBER.findall(text)}


def allowed_numbers(*sources: Any) -> set[str]:
    """Numeri che compaiono nei dati della struttura e nell'analisi: solo questi si possono citare."""
    found: set[str] = set(ALWAYS_ALLOWED)

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, bool) or value is None:
            return
        elif isinstance(value, (int, float)):
            text = f"{value}"
            found.add(text)
            if isinstance(value, float) and value.is_integer():
                found.add(str(int(value)))
        elif isinstance(value, str):
            found.update(_numbers(value))

    for source in sources:
        walk(source)
    return found


def _written_checks(label: str, text: str, sender: str, allowed: set[str], min_lines: int, max_lines: int) -> list[str]:
    problems: list[str] = []
    lower = text.lower()
    lines = _lines(text)
    if not min_lines <= len(lines) <= max_lines:
        problems.append(f"{label}: {len(lines)} righe (servono {min_lines}-{max_lines})")
    if "check-io" not in lower:
        problems.append(f"{label}: manca chi siamo (CHECK-iO)")
    if "google" not in lower:
        problems.append(f"{label}: manca come l'abbiamo trovato (Google Maps)")
    if not OPT_OUT.search(text):
        problems.append(f"{label}: manca come dire no")
    first_name = sender.split()[0].lower() if sender.strip() else ""
    if first_name and first_name not in lower:
        problems.append(f"{label}: manca il nome di chi scrive")
    if "%" in text or "€" in text or "euro" in lower:
        problems.append(f"{label}: contiene percentuali o prezzi")
    for word in BANNED:
        if word in lower:
            problems.append(f"{label}: frase vietata «{word}»")
    unknown = sorted(n for n in _numbers(text) if n not in allowed)
    if unknown:
        problems.append(f"{label}: numeri non presenti nei dati ({', '.join(unknown)})")
    return problems


def _variant_checks(label: str, text: str, variant: str | None, reviews_read: int | None) -> list[str]:
    problems: list[str] = []
    if variant == "A" and ONLY_B.search(text):
        problems.append(f"{label}: versione A (analisi gratuita): non proporre i 10 minuti al telefono")
    if variant == "B" and ONLY_A.search(text):
        problems.append(f"{label}: versione B (chiacchierata di 10 minuti): non proporre l'analisi gratuita")
    if reviews_read == 0 and READ_REVIEWS.search(text):
        problems.append(f"{label}: nessuna recensione letta: non dire di averle lette")
    return problems


def check_messages(
    messages: dict[str, Any], *, sender: str, allowed: set[str], variant: str | None = None,
    reviews_read: int | None = None,
) -> list[str]:
    problems: list[str] = []
    whatsapp = str(messages.get("whatsapp") or "")
    problems += _written_checks("WhatsApp", whatsapp, sender, allowed, 3, 8)
    problems += _variant_checks("WhatsApp", whatsapp, variant, reviews_read)
    email = messages.get("email") or {}
    subject = str(email.get("oggetto") or "")
    body = str(email.get("corpo") or "")
    problems += _variant_checks("Email", subject + "\n" + body, variant, reviews_read)
    if not subject.strip() or len(subject) > 90:
        problems.append("Email: oggetto mancante o troppo lungo")
    problems += _written_checks("Email", body, sender, allowed, 5, 16)
    phone = messages.get("telefono") or {}
    if not str(phone.get("apertura") or "").strip():
        problems.append("Telefonata: manca la frase d'apertura")
    if len(phone.get("domande") or []) < 2:
        problems.append("Telefonata: servono 2 domande")
    objections = {o.get("obiezione") for o in phone.get("obiezioni") or []}
    if len(objections) < 4:
        problems.append("Telefonata: mancano risposte alle obiezioni tipiche")
    return problems
