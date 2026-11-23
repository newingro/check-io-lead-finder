import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Badge } from "@/components/ui";
import { STATUS_LABELS, type PropertyDetail, type PropertyEvent } from "@/lib/data";
import { formatDateTime } from "@/lib/format";
import type { ReactNode } from "react";

const EVENT_LABELS: Record<string, string> = {
  trovata: "Trovata dal radar",
  consultata: "Consultata",
  rimessa_in_ricerca: "Rimessa in ricerca",
};

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-0.5 py-2 sm:grid-cols-[10rem_1fr] sm:gap-4">
      <dt className="text-sm text-slate">{label}</dt>
      <dd className="text-sm break-words text-navy-900">{children || "—"}</dd>
    </div>
  );
}

export function PropertyView({
  property,
  events,
  provinceName,
  actions,
}: {
  property: PropertyDetail;
  events: PropertyEvent[];
  provinceName: string | null;
  actions?: ReactNode;
}) {
  const ratings = Object.entries(property.ratings ?? {});
  return (
    <div className="space-y-6">
      <Link href="/memoria" className="inline-flex items-center gap-1 text-sm font-semibold text-turq-700 hover:underline">
        <ArrowLeft aria-hidden="true" className="size-4" /> Torna alla memoria
      </Link>
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <section className="card p-5" aria-labelledby="scheda">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <h2 id="scheda" className="text-xl font-semibold text-navy-900">
              {property.name}
            </h2>
            <Badge tone={property.status === "cliente" ? "ok" : "neutral"}>{STATUS_LABELS[property.status] ?? property.status}</Badge>
          </div>
          <dl className="mt-4 divide-y divide-line">
            <Row label="Tipo">{property.property_type}</Row>
            <Row label="Indirizzo">{property.address}</Row>
            <Row label="Zona">{[property.zone, provinceName].filter(Boolean).join(" · ")}</Row>
            <Row label="Telefono">{property.phone ? <a className="text-turq-700 hover:underline" href={`tel:${property.phone}`}>{property.phone}</a> : null}</Row>
            <Row label="Email">{property.email ? <a className="text-turq-700 hover:underline" href={`mailto:${property.email}`}>{property.email}</a> : null}</Row>
            <Row label="Sito">
              {property.website ? (
                <a className="text-turq-700 hover:underline" href={property.website} target="_blank" rel="noopener noreferrer">
                  {property.website}
                </a>
              ) : null}
            </Row>
            <Row label="CIN">{property.cin}</Row>
            <Row label="Valutazioni">
              {ratings.length
                ? ratings.map(([portal, r]) => `${portal}: ${r.voto ?? "—"} (${r.recensioni ?? 0} recensioni)`).join(" · ")
                : null}
            </Row>
          </dl>
        </section>
        <aside className="space-y-4">
          <section className="card p-4 text-sm" aria-labelledby="memoria-scheda">
            <h2 id="memoria-scheda" className="font-semibold text-navy-900">
              Memoria
            </h2>
            <dl className="mt-2 space-y-1.5 text-slate">
              <div>
                <dt className="inline">Trovata il </dt>
                <dd className="inline text-navy-900">{formatDateTime(property.created_at)}</dd>
              </div>
              <div>
                <dt className="inline">Con la ricerca </dt>
                <dd className="inline text-navy-900">«{property.search_query ?? "—"}»</dd>
              </div>
              <div>
                <dt className="inline">Ritrovata dal radar </dt>
                <dd className="inline text-navy-900">
                  {property.times_seen - 1} {property.times_seen === 2 ? "volta" : "volte"} (non riproposta)
                </dd>
              </div>
              <div>
                <dt className="inline">Consultata </dt>
                <dd className="inline text-navy-900">
                  {property.view_count} {property.view_count === 1 ? "volta" : "volte"}
                </dd>
              </div>
            </dl>
          </section>
          {actions}
          <section className="card p-4" aria-labelledby="storico">
            <h2 id="storico" className="font-semibold text-navy-900">
              Storico
            </h2>
            {events.length === 0 ? (
              <p className="mt-2 text-sm text-slate">Nessun evento.</p>
            ) : (
              <ol className="mt-3 space-y-2.5">
                {events.map((e) => (
                  <li key={e.id} className="text-sm">
                    <span className="font-medium text-navy-900">{EVENT_LABELS[e.event_type] ?? e.event_type}</span>
                    <span className="block text-xs text-slate">
                      {e.actor_label} · {formatDateTime(e.created_at)}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
