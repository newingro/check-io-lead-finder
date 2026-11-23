"use server";

import { timingSafeEqual } from "node:crypto";
import { headers } from "next/headers";
import { z } from "zod";
import { createAdminClient, isAdminConfigured } from "@/lib/supabase/admin";
import { defaultShifts } from "@/lib/shifts";

export type SetupState = { status: "idle" } | { status: "done" } | { status: "error"; message: string };

const schema = z.object({
  code: z.string().min(1),
  name: z.string().trim().min(2, "Inserisci nome e cognome.").max(80),
  email: z.email("Email non valida.").trim().toLowerCase(),
  password: z.string().min(12, "La password deve avere almeno 12 caratteri.").max(200),
});

const attempts = new Map<string, number[]>();

function tooManyAttempts(key: string) {
  const now = Date.now();
  const recent = (attempts.get(key) ?? []).filter((t) => now - t < 60 * 60 * 1000);
  attempts.set(key, recent);
  return recent.length >= 5;
}

function sameSecret(a: string, b: string) {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

export async function createOwnerAccount(_prev: SetupState, formData: FormData): Promise<SetupState> {
  const setupCode = process.env.ADMIN_SETUP_CODE;
  if (!setupCode || !isAdminConfigured()) return { status: "error", message: "Configurazione del server incompleta." };

  const ip = (await headers()).get("x-forwarded-for")?.split(",")[0]?.trim() ?? "sconosciuto";
  if (tooManyAttempts(ip)) return { status: "error", message: "Troppi tentativi. Riprova tra un'ora." };

  const parsed = schema.safeParse(Object.fromEntries(formData));
  if (!parsed.success) return { status: "error", message: parsed.error.issues[0]?.message ?? "Dati non validi." };
  if (!sameSecret(parsed.data.code.trim(), setupCode.trim())) {
    attempts.get(ip)?.push(Date.now());
    return { status: "error", message: "Codice segreto non corretto." };
  }

  const admin = createAdminClient();
  const { count } = await admin
    .from("lead_finders")
    .select("id", { count: "exact", head: true })
    .eq("role", "titolare")
    .not("auth_user_id", "is", null);
  if ((count ?? 0) > 0) return { status: "error", message: "Esiste già un titolare con accesso al gestionale." };

  const { data: created, error: createError } = await admin.auth.admin.createUser({
    email: parsed.data.email,
    password: parsed.data.password,
    email_confirm: true,
    app_metadata: { must_change_password: false },
  });
  if (createError || !created.user) {
    return {
      status: "error",
      message: createError?.code === "email_exists" ? "Esiste già un account con questa email." : "Account non creato. Riprova.",
    };
  }

  // Collega l'account al titolare già registrato dal bot (se c'è), altrimenti ne crea uno.
  const { data: existing } = await admin
    .from("lead_finders")
    .select("id")
    .eq("role", "titolare")
    .is("auth_user_id", null)
    .order("created_at")
    .limit(1)
    .maybeSingle();

  const link = existing
    ? await admin
        .from("lead_finders")
        .update({ auth_user_id: created.user.id, email: parsed.data.email, name: parsed.data.name, is_active: true })
        .eq("id", existing.id)
    : await admin.from("lead_finders").insert({
        name: parsed.data.name,
        role: "titolare",
        email: parsed.data.email,
        auth_user_id: created.user.id,
        shifts: defaultShifts(),
      });

  if (link.error) {
    await admin.auth.admin.deleteUser(created.user.id);
    return { status: "error", message: "Account non collegato al team. Riprova." };
  }
  await admin.from("audit_log").insert({
    actor_label: parsed.data.name,
    source: "gestionale",
    action: "titolare_creato",
    details: { email: parsed.data.email },
  });
  attempts.delete(ip);
  return { status: "done" };
}
