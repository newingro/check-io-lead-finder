import type { Metadata } from "next";
import { AuthShell } from "@/components/AuthShell";

export const metadata: Metadata = { title: "Configurazione" };

export default function ConfigurationPage() {
  return (
    <AuthShell title="Configurazione incompleta">
      <p className="text-sm text-slate">
        Mancano le variabili <code>NEXT_PUBLIC_SUPABASE_URL</code> e <code>NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY</code>{" "}
        nelle impostazioni del server.
      </p>
    </AuthShell>
  );
}
