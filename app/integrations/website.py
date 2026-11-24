"""Controllo del sito della struttura (solo il sito proprio, mai i portali).

Si leggono al massimo due pagine (home e contatti) per trovare: email pubblicata per le
prenotazioni dirette, codice CIN, link ai portali (Booking, Airbnb…) e WhatsApp.
I siti di Booking, Airbnb, Trivago & co. non vengono mai aperti (lo vietano i loro termini).
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.integrations.google_places import platform_of

USER_AGENT = "CHECK-iO-LeadFinder/1.0 (+https://check-io.it)"
MAX_BYTES = 400_000

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CIN = re.compile(r"\bIT\s?\d{6}\s?[A-Z]\d\s?[A-Z0-9]{8}\b", re.IGNORECASE)
_HREF = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.IGNORECASE)
_CONTACT_WORDS = ("contatt", "contact", "dove-siamo", "where", "info")
_IGNORED_EMAIL_PARTS = ("example.", "sentry", "wixpress", "@2x", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", "domain.")


def safe_url(url: str | None) -> bool:
    """Solo http/https verso nomi pubblici: niente indirizzi interni o IP privati."""
    if not url:
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host or host == "localhost" or "." not in host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return not host.endswith((".local", ".internal", ".lan"))
    return ip.is_global


async def _get(http: httpx.AsyncClient, url: str) -> tuple[str, str]:
    async with http.stream("GET", url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}) as response:
        response.raise_for_status()
        if "html" not in response.headers.get("content-type", "html"):
            return str(response.url), ""
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            chunks.append(chunk)
            size += len(chunk)
            if size >= MAX_BYTES:
                break
        return str(response.url), b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")


def extract(html: str, base_url: str) -> dict[str, Any]:
    links = [urljoin(base_url, h.strip()) for h in _HREF.findall(html)]
    emails = {m.lower().rstrip(".") for m in _EMAIL.findall(html)}
    emails |= {link[7:].split("?")[0].lower() for link in links if link.lower().startswith("mailto:")}
    emails = sorted(e for e in emails if "@" in e and not any(part in e for part in _IGNORED_EMAIL_PARTS))
    portals: dict[str, str] = {}
    whatsapp = False
    for link in links:
        name = platform_of(link)
        if name and name not in portals:
            portals[name] = link.split("?")[0]
        if "wa.me/" in link or "api.whatsapp.com" in link:
            whatsapp = True
    cins = sorted({re.sub(r"\s", "", c).upper() for c in _CIN.findall(html)})
    host = urlparse(base_url).hostname
    contact_page = next(
        (
            link for link in links
            if urlparse(link).hostname == host and any(w in link.lower() for w in _CONTACT_WORDS)
        ),
        None,
    )
    return {"email": emails, "cin": cins, "portali": portals, "whatsapp": whatsapp, "contatti": contact_page}


async def check_website(url: str | None, http: httpx.AsyncClient) -> dict[str, Any]:
    """Risultato: email, cin, portali, whatsapp, pagine lette, eventuale errore."""
    result: dict[str, Any] = {"letto": False, "pagine": 0, "email": [], "cin": [], "portali": {}, "whatsapp": False}
    if not url:
        result["errore"] = "nessun sito"
        return result
    if platform_of(url):
        result["errore"] = "è un annuncio su un portale: non si apre"
        return result
    if not safe_url(url):
        result["errore"] = "indirizzo non valido"
        return result
    try:
        final_url, html = await _get(http, url)
        found = extract(html, final_url)
        pages = 1
        contact = found.pop("contatti")
        if contact and contact != final_url and safe_url(contact):
            try:
                _, html2 = await _get(http, contact)
                more = extract(html2, contact)
                more.pop("contatti")
                found["email"] = sorted(set(found["email"]) | set(more["email"]))
                found["cin"] = sorted(set(found["cin"]) | set(more["cin"]))
                found["portali"] = {**more["portali"], **found["portali"]}
                found["whatsapp"] = found["whatsapp"] or more["whatsapp"]
                pages += 1
            except httpx.HTTPError:
                pass
        result.update(found, letto=True, pagine=pages)
    except httpx.HTTPError as exc:
        result["errore"] = f"sito non raggiungibile ({exc.__class__.__name__})"
    return result
