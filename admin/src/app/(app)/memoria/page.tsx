import type { Metadata } from "next";
import { MemoryView } from "@/components/memoria/MemoryView";
import { PageHeader } from "@/components/ui";
import { loadMemorySummary, loadProperties, loadProvinceIndex } from "@/lib/data";
import { requireMember } from "@/lib/member";

export const metadata: Metadata = { title: "Memoria" };

export default async function MemoryPage({ searchParams }: { searchParams: Promise<{ q?: string; stato?: string }> }) {
  const member = await requireMember();
  const params = await searchParams;
  const filters = { q: typeof params.q === "string" ? params.q.slice(0, 80) : undefined, stato: typeof params.stato === "string" ? params.stato : undefined };
  const [summary, rows, province] = await Promise.all([loadMemorySummary(), loadProperties(filters), loadProvinceIndex()]);
  return (
    <>
      <PageHeader
        title="Memoria del radar"
        description="Ogni struttura trovata resta qui: il radar la riconosce (scheda Google, CIN, telefono, email, nome e indirizzo) e non la ripropone mai come nuova."
      />
      <MemoryView
        summary={summary}
        rows={rows}
        filters={filters}
        provinceNames={Object.fromEntries(province.map((p) => [p.codice, p.nome]))}
        isOwner={member.role === "titolare"}
      />
    </>
  );
}
