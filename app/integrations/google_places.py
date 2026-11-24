"""Ricerca su Google Places API (New) — Text Search, limitata a una cella del radar.

Si usano solo dati della scheda Google (consentiti): nome, indirizzo, telefono pubblico,
sito, valutazione, numero di recensioni e fino a 5 recensioni. I nomi di chi ha scritto
le recensioni vengono scartati subito: non si salvano e non arrivano all'AI.
Il testo delle recensioni non si salva nel database: serve solo all'analisi.

Documentazione: https://developers.google.com/maps/documentation/places/web-service/text-search
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from app.domain.dedupe import Candidate

log = logging.getLogger(__name__)

TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

PLACE_FIELDS = [
    "id",
    "displayName",
    "formattedAddress",
    "location",
    "types",
    "primaryType",
    "businessStatus",
    "nationalPhoneNumber",
    "internationalPhoneNumber",
    "websiteUri",
    "googleMapsUri",
    "rating",
    "userRatingCount",
    "reviews",
]
SEARCH_FIELD_MASK = ",".join(f"places.{name}" for name in PLACE_FIELDS) + ",nextPageToken"
DETAILS_FIELD_MASK = ",".join(PLACE_FIELDS)

PAGE_SIZE = 20
MAX_PAGES = 3  # Google restituisce al massimo 60 risultati per ricerca

# Tipi Google esclusi dal target (hotel e simili).
EXCLUDED_TYPES = {
    "hotel": "hotel",
    "resort_hotel": "hotel",
    "motel": "hotel",
    "extended_stay_hotel": "hotel",
    "hostel": "ostello",
    "campground": "campeggio",
    "rv_park": "campeggio",
    "camping_cabin": "campeggio",
    "mobile_home_park": "campeggio",
}

TYPE_LABELS = {
    "bed_and_breakfast": "b&b",
    "guest_house": "guest house",
    "cottage": "casa vacanze",
    "private_guest_room": "stanza",
    "farmstay": "agriturismo",
    "inn": "affittacamere",
}

PLATFORM_HOSTS = {
    "booking.com": "booking",
    "airbnb.": "airbnb",
    "vrbo.com": "vrbo",
    "trivago.": "trivago",
    "expedia.": "expedia",
}


class PlacesError(Exception):
    """Errore restituito da Google (chiave, quota, richiesta non valida…)."""


@dataclass(frozen=True)
class FoundPlace:
    candidate: Candidate
    reviews: list[dict[str, Any]] = field(default_factory=list)
    primary_type: str | None = None
    types: list[str] = field(default_factory=list)
    business_status: str | None = None
    exclusion: str | None = None  # motivo per non considerarla: hotel, chiusa…
    reviews_raw: int = 0  # recensioni ricevute da Google, anche senza testo (solo per diagnostica)


@dataclass(frozen=True)
class SearchResult:
    places: list[FoundPlace]
    pages: int

    @property
    def reviews_raw(self) -> int:
        return sum(p.reviews_raw for p in self.places)

    @property
    def reviews_text(self) -> int:
        return sum(len(p.reviews) for p in self.places)


def platform_of(url: str | None) -> str | None:
    """'booking', 'airbnb'… se il link è di un portale, altrimenti None."""
    if not url:
        return None
    host = (urlparse(url).hostname or "").lower()
    for needle, name in PLATFORM_HOSTS.items():
        if needle in host:
            return name
    return None


def _reviews(place: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for review in place.get("reviews") or []:
        text = ((review.get("originalText") or {}).get("text") or (review.get("text") or {}).get("text") or "").strip()
        if not text:
            continue
        published = str(review.get("publishTime") or "")
        result.append(
            {
                "voto": review.get("rating"),
                "mese": published[:7] or None,  # AAAA-MM: basta per capire l'andamento
                "testo": text[:1500],
            }
        )
    return result


def parse_place(place: dict[str, Any]) -> FoundPlace:
    """Trasforma un risultato di Google in una struttura (solo i dati che servono)."""
    website = place.get("websiteUri")
    listing_urls: dict[str, str] = {}
    if place.get("googleMapsUri"):
        listing_urls["google_maps"] = place["googleMapsUri"]
    platform = platform_of(website)
    if platform:  # il "sito" è in realtà un annuncio su un portale
        listing_urls[platform] = website
        website = None
    rating = place.get("rating")
    ratings = {"google": {"voto": rating, "recensioni": place.get("userRatingCount") or 0}} if rating else {}
    types = list(place.get("types") or [])
    primary = place.get("primaryType")
    exclusion = None
    for t in [primary, *types]:
        if t in EXCLUDED_TYPES:
            exclusion = EXCLUDED_TYPES[t]
            break
    status = place.get("businessStatus")
    if status in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"):
        exclusion = "chiusa"
    location = place.get("location") or {}
    candidate = Candidate(
        name=((place.get("displayName") or {}).get("text") or "").strip(),
        address=place.get("formattedAddress"),
        latitude=location.get("latitude"),
        longitude=location.get("longitude"),
        google_place_id=place.get("id"),
        phone=place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber"),
        website=website,
        property_type=TYPE_LABELS.get(primary or ""),
        ratings=ratings,
        listing_urls=listing_urls,
    )
    raw = len(place.get("reviews") or [])
    return FoundPlace(candidate, _reviews(place), primary, types, status, exclusion, raw)


class PlacesClient:
    def __init__(self, api_key: str, http: httpx.AsyncClient | None = None) -> None:
        self._key = api_key
        self._http = http or httpx.AsyncClient(timeout=20)

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        response = await self._http.post(
            TEXT_SEARCH_URL,
            json=body,
            headers={"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": SEARCH_FIELD_MASK},
        )
        return self._json(response)

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        if response.status_code != 200:
            try:
                message = response.json().get("error", {}).get("message", "")
            except ValueError:
                message = ""
            raise PlacesError(f"Google ha risposto {response.status_code}: {message[:300]}")
        return response.json()

    async def search(
        self, query: str, bounds: tuple[float, float, float, float], max_pages: int = MAX_PAGES
    ) -> SearchResult:
        """Cerca `query` dentro il rettangolo (sud, ovest, nord, est). Ogni pagina è una richiesta pagata."""
        south, west, north, east = bounds
        body: dict[str, Any] = {
            "textQuery": query,
            "languageCode": "it",
            "regionCode": "IT",
            "pageSize": PAGE_SIZE,
            "locationRestriction": {
                "rectangle": {
                    "low": {"latitude": south, "longitude": west},
                    "high": {"latitude": north, "longitude": east},
                }
            },
        }
        places: list[FoundPlace] = []
        pages = 0
        while pages < max_pages:
            data = await self._post(body)
            pages += 1
            places.extend(parse_place(p) for p in data.get("places") or [])
            token = data.get("nextPageToken")
            if not token:
                break
            body = {**body, "pageToken": token}
        return SearchResult(places, pages)

    async def details(self, place_id: str) -> FoundPlace:
        """Dettagli di una scheda (con le recensioni): una richiesta pagata."""
        response = await self._http.get(
            PLACE_DETAILS_URL.format(place_id=place_id),
            params={"languageCode": "it", "regionCode": "IT"},
            headers={"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": DETAILS_FIELD_MASK},
        )
        return parse_place(self._json(response))
