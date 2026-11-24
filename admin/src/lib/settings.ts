import { z } from "zod";
import { DAYS } from "./shifts.ts";

const TIME = /^([01]\d|2[0-3]):[0-5]\d$/;

const lines = (max: number, label: string) =>
  z
    .array(z.string().trim().min(1).max(60))
    .min(1, `Inserisci almeno ${label}.`)
    .max(max, `Massimo ${max} voci.`);

export const settingsSchema = z.object({
  property_types: lines(20, "un tipo di struttura"),
  search_queries: lines(20, "una ricerca"),
  min_score: z.number().int().min(0).max(100),
  cards_per_run: z.number().int().min(1).max(50),
  searches_per_run: z.number().int().min(0).max(50),
  run_days: z.array(z.enum(DAYS)).min(1, "Scegli almeno un giorno."),
  run_times: z
    .array(z.string().regex(TIME, "Usa il formato 10:00."))
    .min(1, "Inserisci almeno un orario.")
    .max(12),
  followup_days: z.number().int().min(1).max(60),
  max_followups: z.number().int().min(0).max(5),
  archive_after_days: z.number().int().min(1).max(365),
  max_call_attempts: z.number().int().min(1).max(10),
  call_retry_minutes: z.number().int().min(30).max(1440),
  monthly_ai_budget_eur: z.number().min(0).max(10000),
  monthly_search_budget_eur: z.number().min(0).max(10000),
  google_monthly_requests: z.number().int().min(0).max(1000000),
  data_retention_months: z.number().int().min(1).max(60),
});

export type SettingsInput = z.output<typeof settingsSchema>;

export const MODES = ["telefonate", "messaggi", "misto"] as const;
export type Mode = (typeof MODES)[number];
