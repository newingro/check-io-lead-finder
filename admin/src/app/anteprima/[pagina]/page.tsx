import { notFound } from "next/navigation";
import { StateControls } from "@/components/forms/StateControls";
import { SettingsForm } from "@/components/forms/SettingsForm";
import { Shell } from "@/components/Shell";
import { TeamManager } from "@/components/team/TeamManager";
import { Badge, PageHeader } from "@/components/ui";
import { MemoryView } from "@/components/memoria/MemoryView";
import { PropertyView } from "@/components/memoria/PropertyView";
import { ReleaseForm } from "@/components/memoria/ReleaseForm";
import { ZonesEditor } from "@/components/zones/ZonesEditor";
import {
  assertPreview,
  previewEvents,
  previewMemory,
  previewProperties,
  previewProperty,
  previewRadar,
  previewSettings,
  previewTeam,
} from "@/lib/preview";
import { isProvinceZone, zoneDetail } from "@/lib/zones";

export const dynamic = "force-dynamic";

export default async function PreviewPage({ params }: { params: Promise<{ pagina: string }> }) {
  assertPreview();
  const { pagina } = await params;
  const role = pagina.endsWith("-commerciale") ? "commerciale" : "titolare";
  const isOwner = role === "titolare";
  const base = pagina.replace(/-commerciale$/, "");
  let content: React.ReactNode;
  if (base === "panoramica") {
    content = (
      <>
        <PageHeader title="Ciao Matteo" description="Lo stato del Lead Finder a colpo d'occhio." />
        <div className="grid gap-6 lg:grid-cols-2">
          <section className="card p-6">
            <h2 className="text-lg font-semibold text-navy-900">Stato dei giri</h2>
            <div className="mt-4"><StateControls paused mode="misto" canEdit={isOwner} /></div>
          </section>
          <section className="card p-6">
            <h2 className="text-lg font-semibold text-navy-900">Zone attive</h2>
            <ul className="mt-4 divide-y divide-line">
              {previewSettings.zones.filter((z) => z.attiva).map((z) => (
                <li key={isProvinceZone(z) ? z.codice : z.nome} className="flex items-center justify-between py-2.5 text-sm">
                  <span className="font-medium text-navy-900">{z.nome}</span>
                  <Badge tone="ok">{zoneDetail(z)}</Badge>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </>
    );
  } else if (base === "zone") {
    const radar = await previewRadar();
    content = (
      <>
        <PageHeader title="Zone di ricerca" description="Dove il radar del bot cerca strutture: intere province, oppure un comune con il suo raggio." />
        <ZonesEditor initialZones={previewSettings.zones} canEdit={isOwner} province={radar.province} coverage={radar.coverage} previewCells={radar.cells} />
      </>
    );
  } else if (base === "memoria") {
    content = (
      <>
        <PageHeader title="Memoria del radar" description="Ogni struttura trovata resta qui e non viene mai riproposta come nuova." />
        <MemoryView summary={previewMemory} rows={isOwner ? previewProperties : previewProperties.slice(0, 1)} filters={{}} provinceNames={{ "047": "Pistoia", "046": "Lucca" }} isOwner={isOwner} />
      </>
    );
  } else if (base === "struttura") {
    content = <PropertyView property={previewProperty} events={previewEvents} provinceName="Pistoia" actions={isOwner ? <ReleaseForm propertyId={previewProperty.id} /> : null} />;
  } else if (base === "impostazioni") {
    content = (
      <>
        <PageHeader title="Impostazioni" />
        <SettingsForm settings={previewSettings} canEdit={isOwner} />
      </>
    );
  } else if (base === "team") {
    content = (
      <>
        <PageHeader title="Team" />
        <TeamManager team={isOwner ? previewTeam : [previewTeam[1]]} selfId={isOwner ? previewTeam[0].id : previewTeam[1].id} isOwner={isOwner} botUsername="checkio_leads_bot" />
      </>
    );
  } else {
    notFound();
  }
  return <Shell name={isOwner ? "Matteo D'Amico" : "Commerciale di prova"} role={isOwner ? "Titolare" : "Commerciale"}>{content}</Shell>;
}
