import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { ZonesEditor } from "@/components/zones/ZonesEditor";
import { loadCoverage, loadProvinceIndex, loadSettings } from "@/lib/data";
import { formatDateTime } from "@/lib/format";
import { requireMember } from "@/lib/member";

export const metadata: Metadata = { title: "Zone" };

export default async function ZonesPage() {
  const member = await requireMember();
  const [settings, province, coverage] = await Promise.all([loadSettings(), loadProvinceIndex(), loadCoverage()]);
  return (
    <>
      <PageHeader
        title="Zone di ricerca"
        description="Dove il radar del bot cerca strutture: intere province, oppure un comune con il suo raggio. Il radar parte dalle zone mai esplorate e non ripropone mai una struttura già trovata."
      />
      <ZonesEditor initialZones={settings?.zones ?? []} canEdit={member.role === "titolare"} province={province} coverage={coverage} />
      {settings?.updated_by ? (
        <p className="hint mt-6">
          Ultima modifica delle impostazioni: {settings.updated_by}, {formatDateTime(settings.updated_at)}
        </p>
      ) : null}
    </>
  );
}
