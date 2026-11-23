import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { ZoneManager } from "@/components/zones/ZoneManager";
import { loadSettings } from "@/lib/data";
import { formatDateTime } from "@/lib/format";
import { requireMember } from "@/lib/member";

export const metadata: Metadata = { title: "Zone" };

export default async function ZonesPage() {
  const member = await requireMember();
  const settings = await loadSettings();
  return (
    <>
      <PageHeader
        title="Zone di ricerca"
        description="Le aree in cui il bot cerca strutture. Per ogni zona scegli il centro sulla mappa e il raggio in km."
      />
      <ZoneManager initialZones={settings?.zones ?? []} canEdit={member.role === "titolare"} />
      {settings?.updated_by ? (
        <p className="hint mt-6">
          Ultima modifica delle impostazioni: {settings.updated_by}, {formatDateTime(settings.updated_at)}
        </p>
      ) : null}
    </>
  );
}
