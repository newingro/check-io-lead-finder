"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";
import { generateCode, generateTemporaryPassword, hashCode } from "@/lib/codes";
import { requireMember } from "@/lib/member";
import { MODES, settingsSchema, type SettingsInput } from "@/lib/settings";
import { buildShifts, DAYS, defaultShifts } from "@/lib/shifts";
import { AdminNotConfiguredError, createAdminClient } from "@/lib/supabase/admin";
import { createClient } from "@/lib/supabase/server";
import { zonesSchema, type Zone } from "@/lib/zones";

export type ActionResult<T = object> = ({ ok: true } & T) | { ok: false; error: string };

const NOT_OWNER = { ok: false, error: "Solo il titolare può fare questa modifica." } as const satisfies { ok: false; error: string };

async function owner() {
  const member = await requireMember();
  return member.role === "titolare" ? member : null;
}

function adminOrError() {
  try {
    return createAdminClient();
  } catch (error) {
    if (error instanceof AdminNotConfiguredError) return null;
    throw error;
  }
}

const ADMIN_MISSING = "Manca la chiave segreta di Supabase sul server (SUPABASE_SECRET_KEY).";

// ── Stato e modalità ────────────────────────────────────────
export async function setPaused(paused: boolean): Promise<ActionResult> {
  if (!(await owner())) return NOT_OWNER;
  const supabase = await createClient();
  const { error } = await supabase.from("finder_state").update({ paused }).eq("id", 1);
  if (error) return { ok: false, error: "Modifica non salvata. Riprova." };
  revalidatePath("/");
  return { ok: true };
}

export async function setMode(mode: string): Promise<ActionResult> {
  if (!(await owner())) return NOT_OWNER;
  if (!(MODES as readonly string[]).includes(mode)) return { ok: false, error: "Modalità non valida." };
  const supabase = await createClient();
  const { error } = await supabase.from("finder_state").update({ mode }).eq("id", 1);
  if (error) return { ok: false, error: "Modifica non salvata. Riprova." };
  revalidatePath("/");
  return { ok: true };
}

// ── Zone ────────────────────────────────────────────────────
export async function saveZones(zones: Zone[]): Promise<ActionResult> {
  if (!(await owner())) return NOT_OWNER;
  const parsed = zonesSchema.safeParse(zones);
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0]?.message ?? "Zone non valide." };
  const names = parsed.data.map((z) => z.nome.toLowerCase());
  if (new Set(names).size !== names.length) return { ok: false, error: "Ci sono due zone con lo stesso nome." };
  const supabase = await createClient();
  const { error } = await supabase.from("finder_settings").update({ zones: parsed.data }).eq("id", 1);
  if (error) return { ok: false, error: "Zone non salvate. Riprova." };
  revalidatePath("/zone");
  revalidatePath("/");
  return { ok: true };
}

// ── Impostazioni ────────────────────────────────────────────
export async function saveSettings(input: SettingsInput): Promise<ActionResult> {
  if (!(await owner())) return NOT_OWNER;
  const parsed = settingsSchema.safeParse(input);
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0]?.message ?? "Impostazioni non valide." };
  const supabase = await createClient();
  const { error } = await supabase.from("finder_settings").update(parsed.data).eq("id", 1);
  if (error) return { ok: false, error: "Impostazioni non salvate. Riprova." };
  revalidatePath("/impostazioni");
  revalidatePath("/");
  return { ok: true };
}

// ── Team ────────────────────────────────────────────────────
const newAccountSchema = z.object({
  name: z.string().trim().min(2, "Inserisci nome e cognome.").max(80),
  email: z.email("Email non valida.").trim().toLowerCase(),
  role: z.enum(["titolare", "commerciale"]),
  memberId: z.uuid().optional(),
});

/** Crea l'account del gestionale: per una persona nuova o per una già collegata a Telegram. */
export async function createAccount(input: z.input<typeof newAccountSchema>): Promise<ActionResult<{ password: string }>> {
  const me = await owner();
  if (!me) return NOT_OWNER;
  const parsed = newAccountSchema.safeParse(input);
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0]?.message ?? "Dati non validi." };
  const admin = adminOrError();
  if (!admin) return { ok: false, error: ADMIN_MISSING };

  if (parsed.data.memberId) {
    const { data: target } = await admin.from("lead_finders").select("auth_user_id").eq("id", parsed.data.memberId).maybeSingle();
    if (!target) return { ok: false, error: "Persona non trovata." };
    if (target.auth_user_id) return { ok: false, error: "Questa persona ha già un account." };
  }

  const password = generateTemporaryPassword();
  const { data: created, error: createError } = await admin.auth.admin.createUser({
    email: parsed.data.email,
    password,
    email_confirm: true,
    app_metadata: { must_change_password: true },
  });
  if (createError || !created.user) {
    return {
      ok: false,
      error: createError?.code === "email_exists" ? "Esiste già un account con questa email." : "Account non creato. Riprova.",
    };
  }

  const result = parsed.data.memberId
    ? await admin
        .from("lead_finders")
        .update({ auth_user_id: created.user.id, email: parsed.data.email })
        .eq("id", parsed.data.memberId)
    : await admin.from("lead_finders").insert({
        name: parsed.data.name,
        role: parsed.data.role,
        email: parsed.data.email,
        auth_user_id: created.user.id,
        shifts: defaultShifts(),
      });
  if (result.error) {
    await admin.auth.admin.deleteUser(created.user.id);
    return { ok: false, error: "Account non collegato al team. Riprova." };
  }
  await admin.from("audit_log").insert({
    actor_id: me.id,
    actor_label: me.name,
    source: "gestionale",
    action: "account_creato",
    details: { per: parsed.data.name, ruolo: parsed.data.role },
  });
  revalidatePath("/team");
  return { ok: true, password };
}

async function memberAuthUser(admin: NonNullable<ReturnType<typeof adminOrError>>, memberId: string) {
  const { data } = await admin.from("lead_finders").select("id, name, auth_user_id").eq("id", memberId).maybeSingle();
  return data;
}

export async function resetPassword(memberId: string): Promise<ActionResult<{ password: string }>> {
  const me = await owner();
  if (!me) return NOT_OWNER;
  const admin = adminOrError();
  if (!admin) return { ok: false, error: ADMIN_MISSING };
  const target = await memberAuthUser(admin, memberId);
  if (!target?.auth_user_id) return { ok: false, error: "Questa persona non ha un account del gestionale." };
  const password = generateTemporaryPassword();
  const { error } = await admin.auth.admin.updateUserById(target.auth_user_id, {
    password,
    app_metadata: { must_change_password: true },
  });
  if (error) return { ok: false, error: "Password non reimpostata. Riprova." };
  await admin.from("audit_log").insert({
    actor_id: me.id, actor_label: me.name, source: "gestionale", action: "password_reimpostata", details: { per: target.name },
  });
  return { ok: true, password };
}

export async function resetTwoFactor(memberId: string): Promise<ActionResult> {
  const me = await owner();
  if (!me) return NOT_OWNER;
  const admin = adminOrError();
  if (!admin) return { ok: false, error: ADMIN_MISSING };
  const target = await memberAuthUser(admin, memberId);
  if (!target?.auth_user_id) return { ok: false, error: "Questa persona non ha un account del gestionale." };
  const { data: factors, error } = await admin.auth.admin.mfa.listFactors({ userId: target.auth_user_id });
  if (error) return { ok: false, error: "Operazione non riuscita. Riprova." };
  for (const factor of factors?.factors ?? []) {
    await admin.auth.admin.mfa.deleteFactor({ userId: target.auth_user_id, id: factor.id });
  }
  await admin.auth.admin.signOut(target.auth_user_id).catch(() => undefined);
  await admin.from("audit_log").insert({
    actor_id: me.id, actor_label: me.name, source: "gestionale", action: "2fa_reimpostata", details: { per: target.name },
  });
  return { ok: true };
}

const memberUpdateSchema = z.object({
  memberId: z.uuid(),
  name: z.string().trim().min(2).max(80),
  role: z.enum(["titolare", "commerciale"]),
  days: z.array(z.enum(DAYS)),
  start: z.string().regex(/^([01]\d|2[0-3]):[0-5]\d$/),
  end: z.string().regex(/^([01]\d|2[0-3]):[0-5]\d$/),
});

export async function updateMember(input: z.input<typeof memberUpdateSchema>): Promise<ActionResult> {
  const me = await owner();
  if (!me) return NOT_OWNER;
  const parsed = memberUpdateSchema.safeParse(input);
  if (!parsed.success) return { ok: false, error: "Dati non validi: controlla nome e orari." };
  if (parsed.data.start >= parsed.data.end) return { ok: false, error: "L'orario di fine deve essere dopo l'inizio." };
  if (parsed.data.memberId === me.id && parsed.data.role !== "titolare") {
    return { ok: false, error: "Non puoi togliere a te stesso il ruolo di titolare." };
  }
  const supabase = await createClient();
  const { error } = await supabase
    .from("lead_finders")
    .update({
      name: parsed.data.name,
      role: parsed.data.role,
      shifts: buildShifts(parsed.data.days, parsed.data.start, parsed.data.end),
    })
    .eq("id", parsed.data.memberId);
  if (error) return { ok: false, error: "Modifica non salvata. Riprova." };
  revalidatePath("/team");
  return { ok: true };
}

export async function setMemberActive(memberId: string, active: boolean): Promise<ActionResult> {
  const me = await owner();
  if (!me) return NOT_OWNER;
  if (memberId === me.id) return { ok: false, error: "Non puoi sospendere il tuo account." };
  const supabase = await createClient();
  const { error } = await supabase.from("lead_finders").update({ is_active: active }).eq("id", memberId);
  if (error) return { ok: false, error: "Modifica non salvata. Riprova." };
  if (!active) {
    const admin = adminOrError();
    const target = admin ? await memberAuthUser(admin, memberId) : null;
    if (admin && target?.auth_user_id) await admin.auth.admin.signOut(target.auth_user_id).catch(() => undefined);
  }
  revalidatePath("/team");
  return { ok: true };
}

export async function addPerson(input: { name: string; role: string }): Promise<ActionResult> {
  const me = await owner();
  if (!me) return NOT_OWNER;
  const parsed = z
    .object({ name: z.string().trim().min(2, "Inserisci nome e cognome.").max(80), role: z.enum(["titolare", "commerciale"]) })
    .safeParse(input);
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0]?.message ?? "Dati non validi." };
  const admin = adminOrError();
  if (!admin) return { ok: false, error: ADMIN_MISSING };
  const { error } = await admin
    .from("lead_finders")
    .insert({ name: parsed.data.name, role: parsed.data.role, shifts: defaultShifts() });
  if (error) return { ok: false, error: "Persona non aggiunta. Riprova." };
  revalidatePath("/team");
  return { ok: true };
}

/** Codice per collegare Telegram: il bot lo accetta con /collega (valido 15 minuti, una volta sola). */
export async function createTelegramCode(memberId: string): Promise<ActionResult<{ code: string; expiresAt: string }>> {
  const me = await owner();
  if (!me) return NOT_OWNER;
  const admin = adminOrError();
  if (!admin) return { ok: false, error: ADMIN_MISSING };
  const target = await memberAuthUser(admin, memberId);
  if (!target) return { ok: false, error: "Persona non trovata." };
  const code = generateCode();
  const expiresAt = new Date(Date.now() + 15 * 60 * 1000).toISOString();
  await admin.from("link_codes").update({ used_at: new Date().toISOString() }).eq("lead_finder_id", memberId).is("used_at", null);
  const { error } = await admin.from("link_codes").insert({
    code_hash: hashCode(code),
    lead_finder_id: memberId,
    expires_at: expiresAt,
    created_by: me.id,
  });
  if (error) return { ok: false, error: "Codice non creato. Riprova." };
  return { ok: true, code, expiresAt };
}
