"use server";

import { createAdminClient, isAdminConfigured } from "@/lib/supabase/admin";
import { createClient } from "@/lib/supabase/server";

/** Dopo il cambio della password temporanea, toglie l'obbligo di cambiarla. */
export async function clearPasswordChangeFlag(): Promise<{ ok: true } | { ok: false; error: string }> {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const claims = data?.claims;
  if (!claims || claims.aal !== "aal2") return { ok: false, error: "Sessione scaduta: accedi di nuovo." };
  if (!isAdminConfigured()) return { ok: false, error: "Configurazione del server incompleta (chiave segreta mancante)." };
  const admin = createAdminClient();
  const { error } = await admin.auth.admin.updateUserById(claims.sub, {
    app_metadata: { must_change_password: false },
  });
  return error ? { ok: false, error: "Password cambiata, ma non è stato possibile aggiornare l'account. Riprova." } : { ok: true };
}
