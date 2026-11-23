"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { ArrowLeft, Check, MapPinned } from "lucide-react";
import { loadRegionCells } from "@/app/(app)/actions";
import { Badge, Button, cn } from "@/components/ui";
import { caricaRegione } from "@/data/italia";
import italiaJson from "@/data/italia/regioni.json";
import { formatDateTime } from "@/lib/format";
import {
  proietta,
  rettangoloCella,
  type CellaEsplorata,
  type CoperturaProvincia,
  type ItaliaMappa,
  type Proiezione,
  type ProvinciaInfo,
  type RegioneMappa,
} from "@/lib/italia";
import type { CircleZone } from "@/lib/zones";

const ITALIA = italiaJson as unknown as ItaliaMappa;
const KM_PER_DEG_LAT = 110.574;
const DAY = 24 * 60 * 60 * 1000;

export interface ProvinceChoice {
  codice: string;
  nome: string;
}

interface ItalyRadarProps {
  province: ProvinciaInfo[];
  coverage: Record<string, CoperturaProvincia>;
  activeCodes: Set<string>;
  circles: CircleZone[];
  canEdit: boolean;
  onToggle: (items: ProvinceChoice[], active: boolean) => void;
  /** Solo per l'anteprima locale: celle finte al posto di quelle del database. */
  previewCells?: Record<string, CellaEsplorata[]>;
}

interface Point {
  key: string;
  x: number;
  y: number;
}

function cellFill(cell: CellaEsplorata, now: number) {
  if (cell.a_riposo) return "rgb(217 119 6 / 0.38)";
  const age = now - new Date(cell.ultima_ricerca).getTime();
  if (age < 7 * DAY) return "rgb(3 150 139 / 0.62)";
  if (age < 30 * DAY) return "rgb(3 150 139 / 0.4)";
  return "rgb(3 150 139 / 0.22)";
}

/** Fascio del radar che gira attorno al centro, ritagliato sulle aree indicate. */
function Sweep({ map, points, clipId, gradientId }: { map: Proiezione; points: Point[]; clipId: string; gradientId: string }) {
  const cx = points.length ? points.reduce((sum, p) => sum + p.x, 0) / points.length : map.larghezza / 2;
  const cy = points.length ? points.reduce((sum, p) => sum + p.y, 0) / points.length : map.altezza / 2;
  const r = Math.max(map.larghezza, map.altezza) * 1.2;
  const end = { x: cx + r * Math.cos(-Math.PI / 4), y: cy + r * Math.sin(-Math.PI / 4) };
  return (
    <g clipPath={`url(#${clipId})`} aria-hidden="true" pointerEvents="none">
      <g className="radar-giro" style={{ transformOrigin: `${cx}px ${cy}px` }}>
        <path d={`M${cx},${cy} L${cx + r},${cy} A${r},${r} 0 0 0 ${end.x},${end.y} Z`} fill={`url(#${gradientId})`} />
        <line x1={cx} y1={cy} x2={cx + r} y2={cy} stroke="#35cdbd" strokeWidth={1.4} strokeOpacity={0.9} />
      </g>
      {[0.12, 0.24, 0.36].map((f) => (
        <circle key={f} cx={cx} cy={cy} r={Math.max(map.larghezza, map.altezza) * f} fill="none" stroke="#03968b" strokeOpacity={0.25} strokeDasharray="3 5" />
      ))}
    </g>
  );
}

function Pulses({ points }: { points: Point[] }) {
  return (
    <g aria-hidden="true" pointerEvents="none">
      {points.map((p) => (
        <g key={p.key}>
          <circle cx={p.x} cy={p.y} r={4} fill="none" stroke="#03968b" strokeWidth={1.6} className="radar-onda" />
          <circle cx={p.x} cy={p.y} r={3.2} fill="#03968b" stroke="#fff" strokeWidth={1.2} />
        </g>
      ))}
    </g>
  );
}

function GradientDefs({ id }: { id: string }) {
  return (
    <linearGradient id={id} x1="0" y1="0.5" x2="1" y2="0">
      <stop offset="0%" stopColor="#08b7a9" stopOpacity="0" />
      <stop offset="100%" stopColor="#08b7a9" stopOpacity="0.32" />
    </linearGradient>
  );
}

function keyActivate(handler: () => void) {
  return (event: React.KeyboardEvent) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      handler();
    }
  };
}

function coverageText(c: CoperturaProvincia | undefined) {
  if (!c || c.celle_esplorate === 0) return "Non ancora esplorata";
  return `${c.celle_esplorate} di ${c.celle_totali} celle esplorate · ${c.strutture} ${c.strutture === 1 ? "struttura" : "strutture"}`;
}

export function ItalyRadar({ province, coverage, activeCodes, circles, canEdit, onToggle, previewCells }: ItalyRadarProps) {
  const uid = useId().replace(/:/g, "");
  const [regionCode, setRegionCode] = useState<string | null>(null);
  const [region, setRegion] = useState<RegioneMappa | null>(null);
  const [cells, setCells] = useState<CellaEsplorata[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [now] = useState(() => Date.now());

  const byRegion = useMemo(() => {
    const map = new Map<string, ProvinciaInfo[]>();
    for (const p of province) map.set(p.regione_codice, [...(map.get(p.regione_codice) ?? []), p]);
    return map;
  }, [province]);

  useEffect(() => {
    if (!regionCode) return;
    let cancelled = false;
    const loader = caricaRegione[regionCode];
    if (!loader) return;
    loader().then((data) => {
      if (!cancelled) setRegion(data);
    });
    if (!previewCells) {
      loadRegionCells(regionCode).then((result) => {
        if (cancelled) return;
        if (result.ok) setCells(result.cells);
        else setError(result.error);
      });
    }
    return () => {
      cancelled = true;
    };
  }, [regionCode, previewCells]);

  function openRegion(code: string | null) {
    setRegion(null);
    setCells([]);
    setError(null);
    setRegionCode(code);
  }

  const activeIn = (code: string) => (byRegion.get(code) ?? []).filter((p) => activeCodes.has(p.codice));

  // ── Vista Italia ───────────────────────────────────────────
  if (!regionCode) {
    const points: Point[] = [
      ...province.filter((p) => activeCodes.has(p.codice)).map((p) => ({ key: p.codice, ...proietta(ITALIA, p.lat, p.lng) })),
      ...circles.filter((c) => c.attiva).map((c, i) => ({ key: `c${i}`, ...proietta(ITALIA, c.lat, c.lng) })),
    ];
    return (
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <figure className="card m-0 p-3">
          <svg viewBox={`0 0 ${ITALIA.larghezza} ${ITALIA.altezza}`} className="mx-auto block max-h-[680px] w-full" role="group" aria-label="Mappa dell'Italia: scegli una regione">
            <defs>
              <clipPath id={`${uid}-terra`}>
                {ITALIA.aree.map((a) => (
                  <path key={a.codice} d={a.d} />
                ))}
              </clipPath>
              <GradientDefs id={`${uid}-fascio`} />
            </defs>
            {ITALIA.aree.map((a) => {
              const active = activeIn(a.codice).length;
              return (
                <path
                  key={a.codice}
                  d={a.d}
                  role="button"
                  tabIndex={0}
                  aria-label={`${a.nome}: ${active ? `${active} ${active === 1 ? "provincia attiva" : "province attive"}` : "nessuna provincia attiva"}`}
                  onClick={() => openRegion(a.codice)}
                  onKeyDown={keyActivate(() => openRegion(a.codice))}
                  className={cn("mappa-area", active ? "fill-turq-500/25 hover:fill-turq-500/40" : "fill-mist hover:fill-turq-300/30")}
                  stroke={active ? "#03968b" : "#b9c7ce"}
                  strokeWidth={active ? 1.2 : 0.8}
                  strokeLinejoin="round"
                >
                  <title>{a.nome}</title>
                </path>
              );
            })}
            <Sweep map={ITALIA} points={points} clipId={`${uid}-terra`} gradientId={`${uid}-fascio`} />
            <Pulses points={points} />
          </svg>
          <figcaption className="px-1 pt-2 text-xs text-slate">Confini: ISTAT 2026 (CC BY 4.0), elaborazione openpolis.</figcaption>
        </figure>

        <aside className="space-y-4">
          <div className="card space-y-3 p-4">
            <h2 className="font-semibold text-navy-900">Scegli una regione</h2>
            <p className="text-sm text-slate">Tocca una regione sulla mappa{canEdit ? " e poi le province da attivare." : " per vedere le sue province."}</p>
            <label className="label sr-only" htmlFor={`${uid}-regione`}>
              Regione
            </label>
            <select id={`${uid}-regione`} className="input" value="" onChange={(e) => e.target.value && openRegion(e.target.value)}>
              <option value="">Oppure scegli dall&apos;elenco…</option>
              {ITALIA.aree.map((a) => (
                <option key={a.codice} value={a.codice}>
                  {a.nome}
                  {activeIn(a.codice).length ? ` (${activeIn(a.codice).length} attive)` : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="card p-4">
            <h2 className="font-semibold text-navy-900">Province attive ({activeCodes.size})</h2>
            {activeCodes.size === 0 ? (
              <p className="mt-2 text-sm text-slate">Nessuna provincia attiva.</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {province
                  .filter((p) => activeCodes.has(p.codice))
                  .map((p) => (
                    <li key={p.codice} className="text-sm">
                      <button type="button" onClick={() => openRegion(p.regione_codice)} className="font-medium text-navy-900 hover:underline">
                        {p.nome}
                      </button>{" "}
                      <span className="text-slate">· {p.regione}</span>
                      <span className="block text-xs text-slate">{coverageText(coverage[p.codice])}</span>
                    </li>
                  ))}
              </ul>
            )}
          </div>
          <Legend />
        </aside>
      </div>
    );
  }

  // ── Vista regione ─────────────────────────────────────────
  const regionInfo = ITALIA.aree.find((a) => a.codice === regionCode);
  const list = byRegion.get(regionCode) ?? [];
  const activeList = list.filter((p) => activeCodes.has(p.codice));
  const shapes = region?.province ?? [];
  const points: Point[] = region
    ? [
        ...shapes.filter((p) => activeCodes.has(p.codice)).map((p) => ({ key: p.codice, x: p.centro.x, y: p.centro.y })),
        ...circles
          .filter((c) => c.attiva)
          .map((c, i) => ({ key: `c${i}`, ...proietta(region, c.lat, c.lng) }))
          .filter((p) => p.x >= 0 && p.y >= 0 && p.x <= region.larghezza && p.y <= region.altezza),
      ]
    : [];

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <figure className="card m-0 p-3">
        <div className="flex items-center gap-2 px-1 pb-2">
          <Button type="button" variant="ghost" onClick={() => openRegion(null)} className="min-h-9 px-2">
            <ArrowLeft aria-hidden="true" className="size-4" /> Italia
          </Button>
          <span className="text-slate" aria-hidden="true">
            ›
          </span>
          <h2 className="font-semibold text-navy-900">{regionInfo?.nome}</h2>
        </div>
        {region ? (
          <svg viewBox={`0 0 ${region.larghezza} ${region.altezza}`} className="mx-auto block max-h-[680px] w-full" role="group" aria-label={`Province della regione ${region.nome}`}>
            <defs>
              <clipPath id={`${uid}-attive`}>
                {shapes
                  .filter((p) => activeCodes.has(p.codice))
                  .map((p) => (
                    <path key={p.codice} d={p.d} />
                  ))}
              </clipPath>
              <GradientDefs id={`${uid}-fascio-r`} />
            </defs>
            {shapes.map((p) => {
              const active = activeCodes.has(p.codice);
              const toggle = () => canEdit && onToggle([{ codice: p.codice, nome: p.nome }], !active);
              return (
                <path
                  key={p.codice}
                  d={p.d}
                  role={canEdit ? "button" : undefined}
                  tabIndex={canEdit ? 0 : undefined}
                  aria-pressed={canEdit ? active : undefined}
                  aria-label={`${p.nome}${active ? ", attiva" : ""}`}
                  onClick={toggle}
                  onKeyDown={canEdit ? keyActivate(toggle) : undefined}
                  className={cn(canEdit && "mappa-area", active ? "fill-turq-500/25 hover:fill-turq-500/35" : "fill-mist hover:fill-turq-300/25")}
                  stroke={active ? "#03968b" : "#b9c7ce"}
                  strokeWidth={active ? 1.6 : 1}
                  strokeLinejoin="round"
                >
                  <title>
                    {p.nome} — {coverageText(coverage[p.codice])}
                  </title>
                </path>
              );
            })}
            <g aria-hidden="true" pointerEvents="none">
              {(previewCells ? (previewCells[regionCode] ?? []) : cells).map((c) => {
                const r = rettangoloCella(region, c.cell);
                return <rect key={c.cell} x={r.x} y={r.y} width={r.w} height={r.h} fill={cellFill(c, now)} />;
              })}
            </g>
            {circles
              .filter((c) => c.attiva)
              .map((c, i) => {
                const center = proietta(region, c.lat, c.lng);
                return (
                  <circle
                    key={i}
                    cx={center.x}
                    cy={center.y}
                    r={(c.raggio_km / KM_PER_DEG_LAT) * region.k}
                    fill="rgb(8 183 169 / 0.08)"
                    stroke="#03968b"
                    strokeDasharray="5 4"
                    pointerEvents="none"
                  />
                );
              })}
            {activeList.length ? <Sweep map={region} points={points} clipId={`${uid}-attive`} gradientId={`${uid}-fascio-r`} /> : null}
            <Pulses points={points} />
            <g aria-hidden="true" pointerEvents="none">
              {shapes.map((p) => (
                <text
                  key={p.codice}
                  x={p.centro.x}
                  y={p.centro.y - 8}
                  textAnchor="middle"
                  className="fill-navy-900 text-[13px] font-semibold"
                  style={{ paintOrder: "stroke", stroke: "#fff", strokeWidth: 3 }}
                >
                  {p.sigla}
                </text>
              ))}
            </g>
          </svg>
        ) : (
          <div className="flex h-[420px] items-center justify-center text-sm text-slate">Caricamento della regione…</div>
        )}
        <figcaption className="px-1 pt-2 text-xs text-slate">Confini: ISTAT 2026 (CC BY 4.0), elaborazione openpolis. Ogni quadratino è una cella di circa 5 km.</figcaption>
      </figure>

      <aside className="space-y-4">
        <div className="card p-4">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-semibold text-navy-900">Province</h2>
            <Badge tone={activeList.length ? "ok" : "off"}>
              {activeList.length} di {list.length} attive
            </Badge>
          </div>
          {canEdit ? (
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                type="button"
                variant="secondary"
                className="min-h-9 px-3"
                disabled={activeList.length === list.length}
                onClick={() => onToggle(list.map((p) => ({ codice: p.codice, nome: p.nome })), true)}
              >
                <Check aria-hidden="true" className="size-4" /> Tutta la regione
              </Button>
              <Button type="button" variant="ghost" className="min-h-9 px-3" disabled={!activeList.length} onClick={() => onToggle(activeList, false)}>
                Nessuna
              </Button>
            </div>
          ) : null}
          <ul className="mt-3 divide-y divide-line">
            {list.map((p) => {
              const active = activeCodes.has(p.codice);
              const c = coverage[p.codice];
              return (
                <li key={p.codice} className="py-2.5">
                  <label className={cn("flex items-start gap-3 text-sm", canEdit && "cursor-pointer")}>
                    <input
                      type="checkbox"
                      className="mt-0.5 size-4 accent-turq-600"
                      checked={active}
                      disabled={!canEdit}
                      onChange={(e) => onToggle([{ codice: p.codice, nome: p.nome }], e.target.checked)}
                    />
                    <span className="min-w-0">
                      <span className="font-medium text-navy-900">
                        {p.nome} <span className="font-normal text-slate">({p.sigla})</span>
                      </span>
                      <span className="block text-xs text-slate">{coverageText(c)}</span>
                      {c?.ultima_ricerca ? <span className="block text-xs text-slate">Ultima ricerca: {formatDateTime(c.ultima_ricerca)}</span> : null}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
          {error ? <p className="hint text-danger">{error}</p> : null}
        </div>
        <Legend />
      </aside>
    </div>
  );
}

function Legend() {
  return (
    <div className="card space-y-2 p-4 text-sm">
      <h2 className="flex items-center gap-2 font-semibold text-navy-900">
        <MapPinned aria-hidden="true" className="size-4 text-turq-700" /> Legenda
      </h2>
      <p className="flex items-center gap-2">
        <span className="inline-block size-3.5 rounded-sm border border-turq-600 bg-turq-500/25" /> Zona attiva: il radar la cerca
      </p>
      <p className="flex items-center gap-2">
        <span className="inline-block size-3.5 rounded-sm" style={{ background: "rgb(3 150 139 / 0.62)" }} /> Cella cercata di recente
      </p>
      <p className="flex items-center gap-2">
        <span className="inline-block size-3.5 rounded-sm" style={{ background: "rgb(3 150 139 / 0.22)" }} /> Cella cercata più di un mese fa
      </p>
      <p className="flex items-center gap-2">
        <span className="inline-block size-3.5 rounded-sm" style={{ background: "rgb(217 119 6 / 0.38)" }} /> A riposo: niente di nuovo, si riprova più avanti
      </p>
    </div>
  );
}
