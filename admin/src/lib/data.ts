import "server-only";
import { createClient } from "@/lib/supabase/server";
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
