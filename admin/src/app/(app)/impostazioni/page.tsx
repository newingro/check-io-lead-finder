import type { Metadata } from "next";
import { SettingsForm } from "@/components/forms/SettingsForm";
import { Notice, PageHeader } from "@/components/ui";
import { loadGoogleRequestsThisMonth, loadSettings } from "@/lib/data";
import { formatDateTime } from "@/lib/format";
import { requireMember } from "@/lib/member";

export const metadata: Metadata = { title: "Impostazioni" };

export default async function SettingsPage() {
  const member = await requireMember();
  const settings = await loadSettings();
  const googleUsed = member.role === "titolare" ? await loadGoogleRequestsThisMonth() : null;
  return (
    <>
      <PageHeader title="Impostazioni" description="Come e quando lavora il bot. Le zone si impostano dalla pagina Zone." />
      {settings ? (
        <>
          {googleUsed !== null ? (
            <div className="mb-6">
              <Notice tone="info">
                Richieste a Google questo mese: <strong className="tabular-nums">{googleUsed}</strong>
                {settings.google_monthly_requests > 0
                  ? ` su ${settings.google_monthly_requests} (massimo impostato).`
                  : " — nessun massimo impostato: senza massimo e senza prezzo sul server la ricerca Google resta spenta."}
              </Notice>
            </div>
          ) : null}
          <SettingsForm settings={settings} canEdit={member.role === "titolare"} />
          <p className="hint mt-6">
            Versione {settings.version}
            {settings.updated_by ? ` · ultima modifica: ${settings.updated_by}, ${formatDateTime(settings.updated_at)}` : ""}
          </p>
        </>
      ) : (
        <Notice tone="error">Impostazioni non disponibili.</Notice>
      )}
    </>
  );
}
