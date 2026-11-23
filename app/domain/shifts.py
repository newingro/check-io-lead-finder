"""Turni delle persone: formato e testo leggibile."""

from __future__ import annotations

DAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
DAY_NAMES = {
    "lun": "lunedì",
    "mar": "martedì",
    "mer": "mercoledì",
    "gio": "giovedì",
    "ven": "venerdì",
    "sab": "sabato",
    "dom": "domenica",
}


def default_shifts() -> dict[str, list[list[str]]]:
    """Turno predefinito: dal lunedì al venerdì, 9–17."""
    return {day: [["09:00", "17:00"]] for day in DAYS[:5]}


def format_shifts(shifts: dict[str, list[list[str]]] | None) -> str:
    if not shifts:
        return "nessun turno impostato"
    parts: list[str] = []
    index = 0
    while index < len(DAYS):
        day = DAYS[index]
        slots = shifts.get(day)
        if not slots:
            index += 1
            continue
        end = index
        while end + 1 < len(DAYS) and shifts.get(DAYS[end + 1]) == slots:
            end += 1
        days_label = day if end == index else f"{day}–{DAYS[end]}"
        hours = ", ".join(f"{start}–{finish}" for start, finish in slots)
        parts.append(f"{days_label} {hours}")
        index = end + 1
    return "; ".join(parts)
