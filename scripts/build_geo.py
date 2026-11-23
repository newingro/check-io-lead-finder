"""Prepara i dati geografici del radar (si esegue a mano, una volta, quando cambiano i confini).

Fonte: confini ISTAT pubblicati da openpolis/geojson-italy (licenza CC BY 4.0):
  https://github.com/openpolis/geojson-italy  (limits_IT_regions.geojson, limits_IT_provinces.geojson)

Produce:
  admin/src/data/italia/regioni.json          mappa dell'Italia con le regioni (SVG già proiettato)
  admin/src/data/italia/regioni/<codice>.json  una mappa per regione con le sue province e le celle
  admin/src/data/italia/index.ts               caricamento delle regioni su richiesta
  supabase/migrations/20261124090100_province.sql  province e celle per il bot

Le celle sono quadrati di circa 5 km x 5 km (griglia fissa in gradi, uguale nel bot e nel
gestionale): il radar del bot cerca una cella alla volta e ricorda quando l'ha cercata.

Uso:  python -I scripts/build_geo.py CARTELLA_CON_I_GEOJSON
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Griglia del radar: deve restare identica a app/domain/radar.py e admin/src/lib/radar.ts.
STEP_LAT = 0.045
STEP_LNG = 0.0625

ITALY_WIDTH = 600
REGION_WIDTH = 600
PAD = 8


# ── Geometria ────────────────────────────────────────────────
def polygons(geometry: dict) -> list[list[list[tuple[float, float]]]]:
    """Restituisce [poligono][anello][(lng, lat)]."""
    if geometry["type"] == "Polygon":
        return [[[(p[0], p[1]) for p in ring] for ring in geometry["coordinates"]]]
    if geometry["type"] == "MultiPolygon":
        return [[[(p[0], p[1]) for p in ring] for ring in poly] for poly in geometry["coordinates"]]
    raise ValueError(geometry["type"])


def ring_area(ring: list[tuple[float, float]]) -> float:
    return 0.5 * sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(len(ring) - 1))


def simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas-Peucker iterativo."""
    if len(points) < 4:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    tol2 = tolerance * tolerance
    while stack:
        start, end = stack.pop()
        ax, ay = points[start]
        bx, by = points[end]
        dx, dy = bx - ax, by - ay
        norm = dx * dx + dy * dy
        best, index = -1.0, -1
        for i in range(start + 1, end):
            px, py = points[i]
            if norm == 0:
                d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / norm))
                d2 = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d2 > best:
                best, index = d2, i
        if best > tol2:
            keep[index] = True
            stack.append((start, index))
            stack.append((index, end))
    return [p for p, k in zip(points, keep) if k]


class Projection:
    """Equirettangolare con correzione del coseno della latitudine media (come la mappa MetaCraft)."""

    def __init__(self, min_lng: float, min_lat: float, max_lng: float, max_lat: float, width: int):
        self.cos = math.cos(math.radians((min_lat + max_lat) / 2))
        span_x = (max_lng - min_lng) * self.cos
        span_y = max_lat - min_lat
        self.k = (width - 2 * PAD) / span_x
        self.lon0 = min_lng - PAD / (self.k * self.cos)
        self.lat1 = max_lat + PAD / self.k
        self.width = width
        self.height = math.ceil(span_y * self.k + 2 * PAD)

    def __call__(self, lng: float, lat: float) -> tuple[float, float]:
        return (lng - self.lon0) * self.cos * self.k, (self.lat1 - lat) * self.k

    def meta(self) -> dict:
        return {
            "larghezza": self.width,
            "altezza": self.height,
            "lon0": round(self.lon0, 6),
            "lat1": round(self.lat1, 6),
            "k": round(self.k, 6),
            "cos": round(self.cos, 6),
        }


def path(polys, project: Projection, tolerance: float, min_area: float) -> str:
    """Contorno SVG. Le isole più piccole di min_area (px²) si tralasciano, tranne l'anello principale."""
    rings = [[project(lng, lat) for lng, lat in ring] for poly in polys for ring in poly]
    largest = max(abs(ring_area(r)) for r in rings)
    parts: list[str] = []
    for projected in rings:
        area = abs(ring_area(projected))
        if area < min_area and area < largest:
            continue
        simple = simplify(projected, tolerance)
        if len(simple) < 4:
            continue
        coords = "L".join(f"{x:.1f},{y:.1f}" for x, y in simple[:-1])
        parts.append(f"M{coords}Z")
    return "".join(parts)


def bbox(polys) -> tuple[float, float, float, float]:
    xs = [p[0] for poly in polys for ring in poly for p in ring]
    ys = [p[1] for poly in polys for ring in poly for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def centroid(polys) -> tuple[float, float]:
    """Baricentro dell'anello esterno più grande (lng, lat)."""
    ring = max((poly[0] for poly in polys), key=lambda r: abs(ring_area(r)))
    a = ring_area(ring)
    cx = sum((ring[i][0] + ring[i + 1][0]) * (ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]) for i in range(len(ring) - 1))
    cy = sum((ring[i][1] + ring[i + 1][1]) * (ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]) for i in range(len(ring) - 1))
    return cx / (6 * a), cy / (6 * a)


# ── Celle del radar ──────────────────────────────────────────
def cells_for(polys) -> list[str]:
    """Celle della griglia che toccano la provincia (controllo su 3x3 punti per cella)."""
    rings = [ring for poly in polys for ring in poly]
    min_lng, min_lat, max_lng, max_lat = bbox(polys)
    i0, i1 = math.floor(min_lat / STEP_LAT), math.floor(max_lat / STEP_LAT)
    j0, j1 = math.floor(min_lng / STEP_LNG), math.floor(max_lng / STEP_LNG)
    found: set[tuple[int, int]] = set()
    for i in range(i0, i1 + 1):
        for fy in (0.17, 0.5, 0.83):
            lat = (i + fy) * STEP_LAT
            xs: list[float] = []
            for ring in rings:
                for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                    if (y1 > lat) != (y2 > lat):
                        xs.append(x1 + (lat - y1) * (x2 - x1) / (y2 - y1))
            xs.sort()
            for j in range(j0, j1 + 1):
                for fx in (0.17, 0.5, 0.83):
                    lng = (j + fx) * STEP_LNG
                    crossings = sum(1 for x in xs if x < lng)
                    if crossings % 2 == 1:
                        found.add((i, j))
                        break
    return [f"{i}_{j}" for i, j in sorted(found)]


def cell_bitmap(cells: list[str]) -> tuple[int, int, int, int, str]:
    """Celle → (i0, j0, righe, colonne, bit in esadecimale). Bit n = riga*colonne+colonna,
    numerati come get_bit di Postgres (dal bit meno significativo di ogni byte)."""
    pairs = [tuple(int(x) for x in c.split("_")) for c in cells]
    i0, j0 = min(i for i, _ in pairs), min(j for _, j in pairs)
    rows = max(i for i, _ in pairs) - i0 + 1
    cols = max(j for _, j in pairs) - j0 + 1
    data = bytearray((rows * cols + 7) // 8)
    for i, j in pairs:
        n = (i - i0) * cols + (j - j0)
        data[n // 8] |= 1 << (n % 8)
    return i0, j0, rows, cols, data.hex()


# ── Programma ───────────────────────────────────────────────
def short(name: str) -> str:
    """Nomi bilingui: si mostra solo la forma italiana (es. «Valle d'Aosta/Vallée d'Aoste»)."""
    return name.split("/")[0].strip()


def main(source: Path) -> None:
    regions = json.loads((source / "limits_IT_regions.geojson").read_text())["features"]
    provinces = json.loads((source / "limits_IT_provinces.geojson").read_text())["features"]
    out = ROOT / "admin" / "src" / "data" / "italia"
    (out / "regioni").mkdir(parents=True, exist_ok=True)

    all_polys = [p for f in regions for p in polygons(f["geometry"])]
    min_lng, min_lat, max_lng, max_lat = bbox(all_polys)
    italy = Projection(min_lng, min_lat, max_lng, max_lat, ITALY_WIDTH)

    italy_json = {**italy.meta(), "fonte": "ISTAT, via openpolis/geojson-italy (CC BY 4.0)", "aree": []}
    loaders: list[str] = []
    seed_rows: list[str] = []
    total_cells = 0

    for region in sorted(regions, key=lambda f: f["properties"]["reg_istat_code"]):
        props = region["properties"]
        code, name = props["reg_istat_code"], short(props["reg_name"])
        polys = polygons(region["geometry"])
        cx, cy = italy(*centroid(polys))
        italy_json["aree"].append(
            {"codice": code, "nome": name, "d": path(polys, italy, 0.6, 4.0), "centro": {"x": round(cx, 1), "y": round(cy, 1)}}
        )

        r_min_lng, r_min_lat, r_max_lng, r_max_lat = bbox(polys)
        proj = Projection(r_min_lng, r_min_lat, r_max_lng, r_max_lat, REGION_WIDTH)
        items = []
        for prov in sorted(
            (p for p in provinces if p["properties"]["reg_istat_code"] == code), key=lambda f: short(f["properties"]["prov_name"])
        ):
            pp = prov["properties"]
            p_polys = polygons(prov["geometry"])
            lng, lat = centroid(p_polys)
            px, py = proj(lng, lat)
            cells = cells_for(p_polys)
            total_cells += len(cells)
            items.append(
                {
                    "codice": pp["prov_istat_code"],
                    "sigla": pp["prov_acr"],
                    "nome": short(pp["prov_name"]),
                    "tipo": pp["prov_tipo_uts"],
                    "d": path(p_polys, proj, 0.7, 6.0),
                    "centro": {"x": round(px, 1), "y": round(py, 1), "lat": round(lat, 4), "lng": round(lng, 4)},
                    "celle": cells,
                }
            )
            sql_name = short(pp["prov_name"]).replace("'", "''")
            sql_region = name.replace("'", "''")
            i0, j0, rows, cols, bits = cell_bitmap(cells)
            seed_rows.append(
                f"  ('{pp['prov_istat_code']}', '{pp['prov_acr']}', '{sql_name}', '{code}', '{sql_region}', "
                f"{lat:.4f}, {lng:.4f}, {i0}, {j0}, {rows}, {cols}, '{bits}')"
            )
        region_json = {"codice": code, "nome": name, **proj.meta(), "province": items}
        (out / "regioni" / f"{code}.json").write_text(json.dumps(region_json, ensure_ascii=False, separators=(",", ":")))
        loaders.append(f'  "{code}": () => import("./regioni/{code}.json").then((m) => m.default as unknown as RegioneMappa),')

    (out / "regioni.json").write_text(json.dumps(italy_json, ensure_ascii=False, separators=(",", ":")))
    (out / "index.ts").write_text(
        "// File generato da scripts/build_geo.py: non modificarlo a mano.\n"
        'import type { RegioneMappa } from "@/lib/italia";\n\n'
        "export const caricaRegione: Record<string, () => Promise<RegioneMappa>> = {\n" + "\n".join(loaders) + "\n};\n"
    )

    sql = (
        "-- File generato da scripts/build_geo.py: non modificarlo a mano.\n"
        "-- Province italiane (ISTAT 2026, via openpolis/geojson-italy, CC BY 4.0) con le celle del radar\n"
        f"-- (griglia {STEP_LAT}° x {STEP_LNG}°, circa 5 km x 5 km). {len(seed_rows)} province, {total_cells} celle.\n"
        "-- Le celle di ogni provincia sono scritte come griglia di bit (esadecimale) a partire dalla\n"
        "-- cella i0_j0, riga per riga; il database le trasforma nell'elenco «i_j».\n\n"
        "insert into public.province (codice, sigla, nome, regione_codice, regione, lat, lng, celle)\n"
        "select v.codice, v.sigla, v.nome, v.regione_codice, v.regione, v.lat, v.lng,\n"
        "  array(select (v.i0 + r)::text || '_' || (v.j0 + c)::text\n"
        "        from generate_series(0, v.righe - 1) as r, generate_series(0, v.colonne - 1) as c\n"
        "        where get_bit(decode(v.bits, 'hex'), r * v.colonne + c) = 1\n"
        "        order by r, c)\n"
        "from (values\n"
        + ",\n".join(seed_rows)
        + "\n) as v(codice, sigla, nome, regione_codice, regione, lat, lng, i0, j0, righe, colonne, bits)\n"
        "on conflict (codice) do update set sigla = excluded.sigla, nome = excluded.nome,\n"
        "  regione_codice = excluded.regione_codice, regione = excluded.regione, lat = excluded.lat,\n"
        "  lng = excluded.lng, celle = excluded.celle;\n"
    )
    (ROOT / "supabase" / "migrations" / "20261124090100_province.sql").write_text(sql)
    print(f"Regioni: {len(regions)}, province: {len(seed_rows)}, celle: {total_cells}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
