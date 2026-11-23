import "server-only";
import { createClient } from "@supabase/supabase-js";
import { SUPABASE_URL } from "@/lib/env";

/**
 * Client con la chiave segreta: ignora le regole di accesso.
 * Si usa SOLO sul server, dopo aver verificato che chi chiede sia un titolare,
 * per le operazioni sugli account (creazione, password, verifica in due passaggi).
 */
export function createAdminClient() {
  const secret = process.env.SUPABASE_SECRET_KEY;
  if (!secret) {
    throw new AdminNotConfiguredError();
  }
  return createClient(SUPABASE_URL, secret, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

export function isAdminConfigured() {
  return Boolean(process.env.SUPABASE_SECRET_KEY);
}

export class AdminNotConfiguredError extends Error {
  constructor() {
    super("SUPABASE_SECRET_KEY non configurata sul server.");
  }
}
