import { notFound } from "next/navigation";
import type { SettingsRow, TeamRow } from "./data";

/** Anteprima con dati finti, attiva solo in locale con ADMIN_PREVIEW=1 (mai in produzione). */
export function assertPreview() {
  if (process.env.ADMIN_PREVIEW !== "1" || process.env.VERCEL_ENV === "production") notFound();
}

export const previewSettings: SettingsRow = {
  zones: [
    { nome: "Abetone - Val di Luce", lat: 44.1425, lng: 10.6633, raggio_km: 15, attiva: true },
    { nome: "Cutigliano", lat: 44.1001, lng: 10.7553, raggio_km: 8, attiva: true },
    { nome: "San Marcello Pistoiese", lat: 44.0567, lng: 10.7915, raggio_km: 10, attiva: false },
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
