"""Radar: divide le zone in celle di circa 5 km x 5 km e decide dove cercare.

Regole (tutte qui, in un posto solo):
  • prima le celle mai cercate, poi quelle cercate da più tempo;
  • le zone si alternano, così una provincia grande non lascia indietro le altre;
  • una cella (per una certa ricerca) che per 2 volte di fila non dà strutture nuove
    va a riposo 30 giorni; se continua a non darne, 90 giorni;
  • le zone disattivate non si cercano.

La griglia deve restare identica a scripts/build_geo.py e admin/src/lib/radar.ts.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

STEP_LAT = 0.045
STEP_LNG = 0.0625

EMPTY_SEARCHES_BEFORE_REST = 2
FIRST_REST = timedelta(days=30)
LONG_REST = timedelta(days=90)

_KM_PER_DEG_LAT = 110.574


# ── Griglia ──────────────────────────────────────────────────
def cell_id(lat: float, lng: float) -> str:
    return f"{math.floor(lat / STEP_LAT)}_{math.floor(lng / STEP_LNG)}"


def _indices(cell: str) -> tuple[int, int]:
    i, j = cell.split("_")
    return int(i), int(j)


def cell_bounds(cell: str) -> tuple[float, float, float, float]:
    """(sud, ovest, nord, est) in gradi: il rettangolo in cui cercare."""
    i, j = _indices(cell)
    return (
        round(i * STEP_LAT, 6),
        round(j * STEP_LNG, 6),
        round((i + 1) * STEP_LAT, 6),
        round((j + 1) * STEP_LNG, 6),
    )


def cell_center(cell: str) -> tuple[float, float]:
    south, west, north, east = cell_bounds(cell)
    return (south + north) / 2, (west + east) / 2


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def cells_in_circle(lat: float, lng: float, radius_km: float) -> list[str]:
    """Celle che toccano il cerchio (controllo su 3x3 punti per cella, come per le province)."""
    d_lat = radius_km / _KM_PER_DEG_LAT
    d_lng = radius_km / (111.320 * math.cos(math.radians(lat)))
    i0, i1 = math.floor((lat - d_lat) / STEP_LAT), math.floor((lat + d_lat) / STEP_LAT)
    j0, j1 = math.floor((lng - d_lng) / STEP_LNG), math.floor((lng + d_lng) / STEP_LNG)
    found: list[str] = []
    for i in range(i0, i1 + 1):
        for j in range(j0, j1 + 1):
            if any(
                distance_km(lat, lng, (i + fy) * STEP_LAT, (j + fx) * STEP_LNG) <= radius_km
                for fy in (0.17, 0.5, 0.83)
                for fx in (0.17, 0.5, 0.83)
            ):
                found.append(f"{i}_{j}")
    return found


# ── Zone → celle ─────────────────────────────────────────────
@dataclass(frozen=True)
class ZoneRef:
    """La zona a cui appartiene una cella."""

    zone: str
    provincia: str | None = None


def active_zones(zones: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [z for z in zones if z.get("attiva", True)]


def province_codes(zones: Iterable[Mapping[str, Any]]) -> list[str]:
    return sorted({str(z["codice"]) for z in active_zones(zones) if z.get("tipo") == "provincia" and z.get("codice")})


def zone_cells(zones: Iterable[Mapping[str, Any]], province_cells: Mapping[str, list[str]]) -> dict[str, ZoneRef]:
    """Celle da cercare per le zone attive. Una cella in più zone conta una volta (vince la prima)."""
    result: dict[str, ZoneRef] = {}
    for zone in active_zones(zones):
        name = str(zone.get("nome", "")).strip() or "Zona"
        if zone.get("tipo") == "provincia":
            code = str(zone.get("codice", ""))
            cells = province_cells.get(code, [])
            ref = ZoneRef(name, code)
        else:
            try:
                cells = cells_in_circle(float(zone["lat"]), float(zone["lng"]), float(zone["raggio_km"]))
            except (KeyError, TypeError, ValueError):
                continue  # zona incompleta: il database non dovrebbe permetterla, ma non blocca le altre
            ref = ZoneRef(name, None)
        for cell in cells:
            result.setdefault(cell, ref)
    return result


# ── Memoria delle ricerche ───────────────────────────────────
@dataclass(frozen=True)
class CellMemory:
    cell: str
    query: str
    searches: int = 0
    last_searched_at: datetime | None = None
    empty_streak: int = 0
    rest_until: datetime | None = None
    last_results: int = 0
    last_new: int = 0

    def resting(self, now: datetime) -> bool:
        return self.rest_until is not None and self.rest_until > now


@dataclass(frozen=True)
class Target:
    """Una ricerca da fare: una cella con una parola chiave."""

    cell: str
    query: str
    zone: str
    provincia: str | None

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return cell_bounds(self.cell)


def plan(
    cells: Mapping[str, ZoneRef],
    queries: Iterable[str],
    memory: Mapping[tuple[str, str], CellMemory],
    now: datetime,
    limit: int,
    rng: random.Random | None = None,
) -> list[Target]:
    """Sceglie le prossime ricerche: mai fatte prima, poi le più vecchie, alternando le zone."""
    rng = rng or random.Random()
    queries = [q.strip() for q in queries if q and q.strip()]
    by_zone: dict[str, list[tuple[int, float, float, str, str]]] = {}
    for cell, ref in cells.items():
        for query in queries:
            mem = memory.get((cell, query))
            if mem is not None and mem.resting(now):
                continue
            searched = mem is not None and mem.last_searched_at is not None
            age = mem.last_searched_at.timestamp() if searched else 0.0  # type: ignore[union-attr]
            by_zone.setdefault(ref.zone, []).append((1 if searched else 0, age, rng.random(), cell, query))

    ranked: list[tuple[int, int, float, float, Target]] = []
    for zone_items in by_zone.values():
        zone_items.sort()
        for rank, (searched, age, tie, cell, query) in enumerate(zone_items):
            ref = cells[cell]
            ranked.append((searched, rank, age, tie, Target(cell, query, ref.zone, ref.provincia)))
    ranked.sort(key=lambda item: item[:4])
    return [item[4] for item in ranked[: max(0, limit)]]


def after_search(previous: CellMemory | None, cell: str, query: str, results: int, new: int, now: datetime) -> CellMemory:
    """Aggiorna la memoria di una cella dopo una ricerca, con la regola del riposo."""
    base = previous or CellMemory(cell=cell, query=query)
    streak = 0 if new > 0 else base.empty_streak + 1
    rest_until = None
    if streak >= EMPTY_SEARCHES_BEFORE_REST:
        rest_until = now + (FIRST_REST if streak == EMPTY_SEARCHES_BEFORE_REST else LONG_REST)
    return replace(
        base,
        searches=base.searches + 1,
        last_searched_at=now,
        empty_streak=streak,
        rest_until=rest_until,
        last_results=results,
        last_new=new,
    )
