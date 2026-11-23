"""Codici temporanei per collegare il Telegram di una persona.

Il codice si mostra una sola volta; nel database resta solo la sua
impronta (hash), quindi chi leggesse il database non potrebbe usarlo.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# Niente caratteri che si confondono (0/O, 1/I/L).
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


def generate_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_code(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def hash_code(value: str) -> str:
    return hashlib.sha256(normalize_code(value).encode()).hexdigest()


def matches_secret(candidate: str, secret: str | None) -> bool:
    """Confronto a tempo costante con il codice di primo avvio."""
    if not secret:
        return False
    return hmac.compare_digest(candidate.strip().encode(), secret.strip().encode())
