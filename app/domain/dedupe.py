"""Memoria delle strutture: riconosce una struttura già trovata, anche se arriva in modo diverso.

Ogni struttura lascia delle impronte (SHA-256 del valore normalizzato):
  • google          — l'identificativo della scheda Google
  • cin             — il Codice Identificativo Nazionale
  • telefono        — il numero in formato internazionale
  • email           — l'indirizzo in minuscolo
  • nome_indirizzo  — nome + indirizzo senza accenti, punteggiatura e maiuscole
Basta un'impronta in comune per considerarla già vista. Le impronte non contengono il dato
in chiaro e restano anche quando i dati della struttura vengono cancellati.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlparse
from dataclasses import dataclass, field
from typing import Any

KINDS = ("google", "cin", "telefono", "email", "nome_indirizzo", "annuncio")

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Candidate:
    """Una struttura come arriva da una ricerca."""

    name: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    google_place_id: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    cin: str | None = None
    property_type: str | None = None
    ratings: dict[str, Any] = field(default_factory=dict)
    listing_urls: dict[str, str] = field(default_factory=dict)


MOBILE_IT = re.compile(r"^\+393\d{8,9}$")


def is_mobile(phone_normalized: str | None) -> bool:
    """Cellulare italiano (+39 3…): l'unico su cui si può scrivere su WhatsApp. I fissi iniziano con +39 0."""
    return bool(phone_normalized and MOBILE_IT.match(phone_normalized))


def normalize_phone(raw: str | None) -> str | None:
    """Numero in formato +39…; None se non sembra un numero di telefono."""
    if not raw:
        return None
    text = raw.strip()
    digits = re.sub(r"\D", "", text)
    if text.startswith("+"):
        international = digits
    elif digits.startswith("00"):
        international = digits[2:]
    elif digits.startswith("39") and len(digits) >= 11:
        international = digits  # prefisso 39 scritto senza «+»
    elif digits.startswith(("0", "3")):
        international = "39" + digits  # numero italiano scritto senza prefisso
    else:
        international = digits
    if international.startswith("39"):
        national = international[2:]
        if not (6 <= len(national) <= 11 and national[0] in "03"):
            return None
    elif not 8 <= len(international) <= 15:
        return None
    return "+" + international


def normalize_email(raw: str | None) -> str | None:
    if not raw:
        return None
    email = raw.strip().lower()
    if email.startswith("mailto:"):
        email = email[7:]
    return email if _EMAIL.match(email) else None


def normalize_cin(raw: str | None) -> str | None:
    if not raw:
        return None
    cin = re.sub(r"[^0-9A-Za-z]", "", raw).upper()
    return cin if len(cin) >= 10 else None


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = text.replace("&", " e ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def normalize_name_address(name: str | None, address: str | None) -> str | None:
    """Nome + indirizzo (senza la parte «Italia» finale). Serve solo se ci sono entrambi."""
    if not name or not address:
        return None
    plain_name = _plain(name)
    plain_address = _plain(re.sub(r",?\s*(italia|italy)\s*$", "", address.strip(), flags=re.IGNORECASE))
    if len(plain_name) < 2 or len(plain_address) < 5:
        return None
    return f"{plain_name}|{plain_address}"


def _hash(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}:{value}".encode()).hexdigest()


def fingerprints(candidate: Candidate) -> list[tuple[str, str]]:
    """Le impronte di una struttura, nell'ordine di affidabilità."""
    values = {
        "google": (candidate.google_place_id or "").strip() or None,
        "cin": normalize_cin(candidate.cin),
        "telefono": normalize_phone(candidate.phone),
        "email": normalize_email(candidate.email),
        "nome_indirizzo": normalize_name_address(candidate.name, candidate.address),
    }
    return [(kind, _hash(kind, value)) for kind, value in values.items() if value]


def normalize_listing_url(url: str | None) -> str | None:
    """Link di un annuncio senza parametri: «booking.com/hotel/it/casa-sole.it.html»."""
    if not url:
        return None
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    path = parsed.path.rstrip("/").lower()
    if not host or not path:
        return None
    return f"{host}{path}"


def listing_fingerprints(url: str | None, cin: str | None) -> list[tuple[str, str]]:
    """Impronte di un annuncio incollato a mano: link normalizzato e, se c'è, CIN."""
    prints = []
    link = normalize_listing_url(url)
    if link:
        prints.append(("annuncio", _hash("annuncio", link)))
    code = normalize_cin(cin)
    if code:
        prints.append(("cin", _hash("cin", code)))
    return prints
