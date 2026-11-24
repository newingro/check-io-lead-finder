import "server-only";
import { createClient } from "@/lib/supabase/server";
import type { CoperturaProvincia, ProvinciaInfo } from "@/lib/italia";
import type { SettingsInput } from "@/lib/settings";
import { parseZones, type Zone } from "@/lib/zones";
import type { Shifts } from "@/lib/shifts";

export interface SettingsRow extends SettingsInput {
  zones: Zone[];
  version: number;
  updated_by: string | null;
  updated_at: string;
}

export interface StateRow {
  paused: boolean;
  mode: "telefonate" | "messaggi" | "misto";
  updated_by: string | null;
  updated_at: string;
}

export interface TeamRow {
  id: string;
  name: string;
  role: "titolare" | "commerciale";
  email: string | null;
  is_active: boolean;
  shifts: Shifts;
  has_account: boolean;
  telegram_linked: boolean;
}

export async function loadSettings(): Promise<SettingsRow | null> {
  const supabase = await createClient();
  const { data } = await supabase.from("finder_settings").select("*").eq("id", 1).maybeSingle();
  if (!data) return null;
  return {
    ...data,
    zones: parseZones(data.zones),
    monthly_ai_budget_eur: Number(data.monthly_ai_budget_eur),
    monthly_search_budget_eur: Number(data.monthly_search_budget_eur),
  } as SettingsRow;
}

export async function loadState(): Promise<StateRow | null> {
  const supabase = await createClient();
  const { data } = await supabase.from("finder_state").select("paused, mode, updated_by, updated_at").eq("id", 1).maybeSingle();
  return (data as StateRow | null) ?? null;
}

export async function loadTeam(): Promise<TeamRow[]> {
  const supabase = await createClient();
  const { data } = await supabase
    .from("lead_finders")
    .select("id, name, role, email, is_active, shifts, auth_user_id, telegram_user_id")
    .order("role", { ascending: false })
    .order("name");
  return (data ?? []).map((row) => ({
    id: row.id,
    name: row.name,
    role: row.role,
    email: row.email,
    is_active: row.is_active,
    shifts: (row.shifts ?? {}) as Shifts,
    has_account: row.auth_user_id !== null,
    telegram_linked: row.telegram_user_id !== null,
  }));
}

export interface AuditRow {
  id: number;
  actor_label: string;
  source: string;
  action: string;
  created_at: string;
}

export async function loadRecentActivity(limit = 8): Promise<AuditRow[]> {
  const supabase = await createClient();
  const { data } = await supabase
    .from("audit_log")
    .select("id, actor_label, source, action, created_at")
    .order("created_at", { ascending: false })
    .limit(limit);
  return (data as AuditRow[] | null) ?? [];
}

// ── Radar e memoria ─────────────────────────────────────────

export async function loadProvinceIndex(): Promise<ProvinciaInfo[]> {
  const supabase = await createClient();
  const { data } = await supabase
    .from("province")
    .select("codice, sigla, nome, regione_codice, regione, lat, lng")
    .order("regione_codice")
    .order("nome");
  return (data ?? []) as ProvinciaInfo[];
}

export async function loadCoverage(): Promise<CoperturaProvincia[]> {
  const supabase = await createClient();
  const { data } = await supabase.rpc("radar_province");
  return (data ?? []) as CoperturaProvincia[];
}

export interface MemorySummary {
  strutture: number;
  impronte: number;
  consultate: number;
  celle_esplorate: number;
  ricerche: number;
  ultima_ricerca: string | null;
}

export async function loadMemorySummary(): Promise<MemorySummary | null> {
  const supabase = await createClient();
  const { data } = await supabase.rpc("memoria_riepilogo");
  return ((data as MemorySummary[] | null) ?? [])[0] ?? null;
}

export const STATUS_LABELS: Record<string, string> = {
  nuovo: "Nuova",
  analizzato: "Analizzata",
  proposto: "Proposta",
  approvato: "Approvata",
  scartato: "Scartata",
  contattato: "Contattata",
  followup: "Follow-up",
  richiamare: "Da richiamare",
  risposto: "Ha risposto",
  trattativa: "Trattativa",
  cliente: "Cliente",
  perso: "Persa",
  errore: "Errore",
};

export interface PropertyRow {
  id: string;
  name: string;
  property_type: string | null;
  zone: string | null;
  provincia: string | null;
  status: string;
  created_at: string;
  times_seen: number;
  view_count: number;
  last_viewed_at: string | null;
  last_viewed_by_name: string | null;
}

export async function loadProperties(filters: { q?: string; stato?: string }, limit = 100): Promise<PropertyRow[]> {
  const supabase = await createClient();
  let query = supabase
    .from("properties")
    .select("id, name, property_type, zone, provincia, status, created_at, times_seen, view_count, last_viewed_at, viewer:lead_finders!properties_last_viewed_by_fkey(name)")
    .order("created_at", { ascending: false })
    .limit(limit);
  const q = filters.q?.trim();
  if (q) query = query.ilike("name", `%${q.replace(/[%_\\]/g, (c) => `\\${c}`)}%`);
  if (filters.stato && filters.stato in STATUS_LABELS) query = query.eq("status", filters.stato);
  const { data } = await query;
  return (data ?? []).map((row) => {
    const viewer = row.viewer as { name: string } | { name: string }[] | null;
    return {
      ...(row as unknown as Omit<PropertyRow, "last_viewed_by_name">),
      last_viewed_by_name: Array.isArray(viewer) ? (viewer[0]?.name ?? null) : (viewer?.name ?? null),
    };
  });
}

export interface PropertyDetail extends PropertyRow {
  address: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  cin: string | null;
  ratings: Record<string, { voto?: number; recensioni?: number }>;
  search_query: string | null;
  cell: string | null;
  last_seen_at: string;
  score: number | null;
  score_reasons: string[] | null;
  analysis: {
    sintesi?: string;
    recensioni?: { lette?: number; temi_negativi?: { tema: string; volte: number; su_quante: number }[]; temi_positivi?: string[] };
    esclusione?: { escludi?: boolean; spiegazione?: string };
  } | null;
  messages: {
    whatsapp?: string;
    email?: { oggetto?: string; corpo?: string };
    telefono?: { apertura?: string; domande?: string[] };
    variante?: string;
    da_ricontrollare?: string[];
  } | null;
  message_variant: string | null;
  discard_reason: string | null;
}

export interface PropertyEvent {
  id: number;
  actor_label: string;
  source: string;
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  created_at: string;
}

export async function loadProperty(id: string): Promise<{ property: PropertyDetail; events: PropertyEvent[] } | null> {
  if (!/^[0-9a-f-]{36}$/i.test(id)) return null;
  const supabase = await createClient();
  const { data } = await supabase
    .from("properties")
    .select("id, name, property_type, zone, provincia, status, created_at, times_seen, view_count, last_viewed_at, address, phone, email, website, cin, ratings, search_query, cell, last_seen_at, score, score_reasons, analysis, messages, message_variant, discard_reason, viewer:lead_finders!properties_last_viewed_by_fkey(name)")
    .eq("id", id)
    .maybeSingle();
  if (!data) return null;
  const { data: events } = await supabase
    .from("property_events")
    .select("id, actor_label, source, event_type, from_status, to_status, created_at")
    .eq("property_id", id)
    .order("created_at", { ascending: false })
    .limit(50);
  const viewer = data.viewer as { name: string } | { name: string }[] | null;
  return {
    property: {
      ...(data as unknown as Omit<PropertyDetail, "last_viewed_by_name">),
      ratings: (data.ratings ?? {}) as PropertyDetail["ratings"],
      last_viewed_by_name: Array.isArray(viewer) ? (viewer[0]?.name ?? null) : (viewer?.name ?? null),
    },
    events: (events ?? []) as PropertyEvent[],
  };
}


/** Richieste fatte a Google dall'inizio del mese (solo il titolare può leggere le ricerche). */
export async function loadGoogleRequestsThisMonth(): Promise<number | null> {
  const supabase = await createClient();
  const now = new Date();
  const since = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)).toISOString();
  const { data, error } = await supabase.from("search_runs").select("pages").gte("started_at", since);
  if (error) return null;
  return (data ?? []).reduce((sum, row) => sum + (Number(row.pages) || 0), 0);
}
