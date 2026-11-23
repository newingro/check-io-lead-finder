import type { Metadata } from "next";
import { SettingsForm } from "@/components/forms/SettingsForm";
import { Notice, PageHeader } from "@/components/ui";
import { loadSettings } from "@/lib/data";
import { formatDateTime } from "@/lib/format";
import { requireMember } from "@/lib/member";

export const metadata: Metadata = { title: "Impostazioni" };

export default async function SettingsPage() {
  const member = await requireMember();
  const settings = await loadSettings();
  return (
    <>
      <PageHeader title="Impostazioni" description="Come e quando lavora il bot. Le zone si impostano dalla pagina Zone." />
      {settings ? (
        <>
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
