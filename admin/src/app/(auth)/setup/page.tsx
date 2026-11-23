import type { Metadata } from "next";
import Link from "next/link";
import { AuthShell } from "@/components/AuthShell";
import { Notice } from "@/components/ui";
import { createAdminClient, isAdminConfigured } from "@/lib/supabase/admin";
import { SetupForm } from "./SetupForm";

export const metadata: Metadata = { title: "Primo accesso del titolare" };

// Legge configurazione e database a ogni richiesta (mai una pagina fissa).
export const dynamic = "force-dynamic";

export default async function SetupPage() {
  if (!isAdminConfigured() || !process.env.ADMIN_SETUP_CODE) {
    return (
      <AuthShell title="Configurazione incompleta">
        <Notice tone="info">
          Per creare il primo account servono le variabili <code>SUPABASE_SECRET_KEY</code> e{" "}
          <code>ADMIN_SETUP_CODE</code> nelle impostazioni del server (Vercel → Settings → Environment Variables).
        </Notice>
      </AuthShell>
    );
  }
  const admin = createAdminClient();
  const { count } = await admin
    .from("lead_finders")
    .select("id", { count: "exact", head: true })
    .eq("role", "titolare")
    .not("auth_user_id", "is", null);
  if ((count ?? 0) > 0) {
    return (
      <AuthShell title="Configurazione già completata">
        <p className="text-sm text-slate">
          Esiste già un titolare con accesso al gestionale. Gli altri account si creano dalla pagina Team.
        </p>
        <Link href="/login" className="mt-6 inline-block text-sm font-semibold text-turq-700 underline">
          Vai all&apos;accesso
        </Link>
      </AuthShell>
    );
  }
  return (
    <AuthShell
      title="Primo accesso del titolare"
      description="Crea il tuo account. Serve il codice segreto impostato sul server (ADMIN_SETUP_CODE)."
    >
      <SetupForm />
    </AuthShell>
  );
}
