import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { MarkViewed } from "@/components/memoria/MarkViewed";
import { PropertyView } from "@/components/memoria/PropertyView";
import { ReleaseForm } from "@/components/memoria/ReleaseForm";
import { loadProperty, loadProvinceIndex } from "@/lib/data";
import { requireMember } from "@/lib/member";

export const metadata: Metadata = { title: "Struttura" };

export default async function PropertyPage({ params }: { params: Promise<{ id: string }> }) {
  const member = await requireMember();
  const { id } = await params;
  const [result, province] = await Promise.all([loadProperty(id), loadProvinceIndex()]);
  if (!result) notFound();
  const provinceName = province.find((p) => p.codice === result.property.provincia)?.nome ?? null;
  return (
    <>
      <MarkViewed propertyId={result.property.id} />
      <PropertyView
        property={result.property}
        events={result.events}
        provinceName={provinceName}
        actions={member.role === "titolare" ? <ReleaseForm propertyId={result.property.id} /> : null}
      />
    </>
  );
}
