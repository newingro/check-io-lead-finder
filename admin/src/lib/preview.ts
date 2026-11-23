import { notFound } from "next/navigation";
import { caricaRegione } from "@/data/italia";
import type { MemorySummary, PropertyDetail, PropertyEvent, PropertyRow, SettingsRow, TeamRow } from "./data";
import type { CellaEsplorata, CoperturaProvincia, ProvinciaInfo } from "./italia";

/** Anteprima con dati finti, attiva solo in locale con ADMIN_PREVIEW=1 (mai in produzione). */
export function assertPreview() {
  if (process.env.ADMIN_PREVIEW !== "1" || process.env.VERCEL_ENV === "production") notFound();
}

export const previewSettings: SettingsRow = {
  zones: [
    { tipo: "provincia", codice: "047", nome: "Pistoia", attiva: true },
    { tipo: "provincia", codice: "046", nome: "Lucca", attiva: true },
    { tipo: "cerchio", nome: "Abetone - Val di Luce", lat: 44.1425, lng: 10.6633, raggio_km: 15, attiva: true },
  ],
  property_types: ["appartamento", "stanza", "b&b", "casa vacanze", "affittacamere", "guest house"],
  search_queries: ["casa vacanze", "appartamenti vacanze", "B&B", "affittacamere", "guest house"],
  min_score: 60,
  cards_per_run: 5,
  run_days: ["lun", "mar", "mer", "gio", "ven"],
  run_times: ["10:00", "12:30", "15:00"],
  followup_days: 5,
  max_followups: 2,
  archive_after_days: 30,
  max_call_attempts: 3,
  call_retry_minutes: 120,
  monthly_ai_budget_eur: 30,
  monthly_search_budget_eur: 30,
  data_retention_months: 12,
  version: 4,
  updated_by: "Matteo D'Amico",
  updated_at: new Date("2026-11-23T16:00:00Z").toISOString(),
};

export const previewTeam: TeamRow[] = [
  {
    id: "00000000-0000-4000-8000-000000000001",
    name: "Matteo D'Amico",
    role: "titolare",
    email: "titolare@esempio.it",
    is_active: true,
    shifts: { lun: [["09:00", "17:00"]], mar: [["09:00", "17:00"]], mer: [["09:00", "17:00"]], gio: [["09:00", "17:00"]], ven: [["09:00", "17:00"]] },
    has_account: true,
    telegram_linked: true,
  },
  {
    id: "00000000-0000-4000-8000-000000000002",
    name: "Commerciale di prova",
    role: "commerciale",
    email: null,
    is_active: true,
    shifts: { lun: [["10:00", "16:00"]], mer: [["10:00", "16:00"]] },
    has_account: false,
    telegram_linked: false,
  },
];

// ── Radar e memoria (dati di esempio per l'anteprima) ───────
export async function previewRadar(): Promise<{
  province: ProvinciaInfo[];
  coverage: CoperturaProvincia[];
  cells: Record<string, CellaEsplorata[]>;
}> {
  const regions = await Promise.all(Object.values(caricaRegione).map((load) => load()));
  const province = regions.flatMap((r) =>
    r.province.map((p) => ({ codice: p.codice, sigla: p.sigla, nome: p.nome, regione_codice: r.codice, regione: r.nome, lat: p.centro.lat, lng: p.centro.lng })),
  );
  const toscana = regions.find((r) => r.codice === "09")!;
  const pistoia = toscana.province.find((p) => p.codice === "047")!;
  const lucca = toscana.province.find((p) => p.codice === "046")!;
  const day = 24 * 60 * 60 * 1000;
  const base = new Date("2026-11-23T10:00:00Z").getTime();
  const explored = [...pistoia.celle.slice(0, 26), ...lucca.celle.slice(10, 22)];
  const cells: CellaEsplorata[] = explored.map((cell, i) => ({
    cell,
    ultima_ricerca: new Date(base - (i % 5) * 9 * day).toISOString(),
    ricerche: 1 + (i % 3),
    nuove: i % 4,
    a_riposo: i % 7 === 3,
  }));
  const coverage: CoperturaProvincia[] = [
    { codice: "047", celle_totali: pistoia.celle.length, celle_esplorate: 26, ricerche: 61, ultima_ricerca: new Date(base).toISOString(), strutture: 48, nuove_30_giorni: 17 },
    { codice: "046", celle_totali: lucca.celle.length, celle_esplorate: 12, ricerche: 24, ultima_ricerca: new Date(base - 2 * day).toISOString(), strutture: 19, nuove_30_giorni: 9 },
  ];
  return { province, coverage, cells: { "09": cells } };
}

export const previewMemory: MemorySummary = {
  strutture: 67,
  impronte: 241,
  consultate: 23,
  celle_esplorate: 38,
  ricerche: 85,
  ultima_ricerca: "2026-11-23T10:00:00Z",
};

export const previewProperties: PropertyRow[] = [
  { id: "30000000-0000-4000-8000-000000000001", name: "Esempio · Baita sulla neve", property_type: "casa vacanze", zone: "Pistoia", provincia: "047", status: "proposto", created_at: "2026-11-23T09:12:00Z", times_seen: 3, view_count: 2, last_viewed_at: "2026-11-23T11:40:00Z", last_viewed_by_name: "Matteo D'Amico" },
  { id: "30000000-0000-4000-8000-000000000002", name: "Esempio · Appartamento Val di Luce", property_type: "appartamento", zone: "Abetone - Val di Luce", provincia: "047", status: "nuovo", created_at: "2026-11-22T15:30:00Z", times_seen: 1, view_count: 0, last_viewed_at: null, last_viewed_by_name: null },
  { id: "30000000-0000-4000-8000-000000000003", name: "Esempio · B&B Le Querce", property_type: "b&b", zone: "Lucca", provincia: "046", status: "scartato", created_at: "2026-11-20T10:05:00Z", times_seen: 2, view_count: 1, last_viewed_at: "2026-11-20T16:02:00Z", last_viewed_by_name: "Commerciale di prova" },
];

export const previewProperty: PropertyDetail = {
  ...previewProperties[0],
  address: "Via di esempio 1, 51024 Abetone Cutigliano PT",
  phone: "+39 000 000 0000",
  email: "esempio@example.com",
  website: "https://example.com",
  cin: null,
  ratings: { google: { voto: 4.6, recensioni: 80 } },
  search_query: "casa vacanze",
  cell: "981_170",
  last_seen_at: "2026-11-23T10:00:00Z",
};

export const previewEvents: PropertyEvent[] = [
  { id: 3, actor_label: "Matteo D'Amico", source: "gestionale", event_type: "consultata", from_status: null, to_status: null, created_at: "2026-11-23T11:40:00Z" },
  { id: 2, actor_label: "Commerciale di prova", source: "gestionale", event_type: "consultata", from_status: null, to_status: null, created_at: "2026-11-23T10:15:00Z" },
  { id: 1, actor_label: "bot", source: "bot", event_type: "trovata", from_status: null, to_status: "nuovo", created_at: "2026-11-23T09:12:00Z" },
];
