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
  analizzata: "Analizzata dall'AI",
  esclusa: "Esclusa",
  errore_analisi: "Errore nell'analisi",
  messaggi_scritti: "Messaggi scritti",
  messaggio_modificato: "Messaggio modificato",
  proposta: "Scheda inviata su Telegram",
  approvata: "Approvata",
  scartata: "Scartata",
  gia_gestita: "Già gestita da altri",
  inviato: "Messaggio inviato",
  opt_out: "Non vuole essere contattata",
};

const DISCARD_LABELS: Record<string, string> = {
  senza_contatti: "nessun telefono o email pubblici",
  senza_cellulare: "nessun cellulare pubblico (solo fisso o email)",
  hotel: "è un hotel",
  gestita_da_altri: "già gestita da un altro property manager",
  fuori_target: "fuori target",
  chiusa: "chiusa",
  scartata_dal_team: "scartata dal team",
  opt_out: "ha chiesto di non essere contattata",
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
          {property.messages?.whatsapp || property.messages?.email?.corpo ? (
            <div className="mt-6 space-y-4 border-t border-line pt-5">
              <h3 className="font-semibold text-navy-900">
                Messaggi {property.messages?.variante ? <span className="font-normal text-slate">· versione {property.messages.variante}</span> : null}
              </h3>
              {property.messages?.whatsapp ? (
                <div>
                  <p className="text-xs font-semibold tracking-wide text-slate uppercase">WhatsApp</p>
                  <p className="mt-1 rounded-md bg-paper p-3 text-sm whitespace-pre-line text-navy-900">{property.messages.whatsapp}</p>
                </div>
              ) : null}
              {property.messages?.email?.corpo ? (
                <div>
                  <p className="text-xs font-semibold tracking-wide text-slate uppercase">Email · {property.messages.email.oggetto}</p>
                  <p className="mt-1 rounded-md bg-paper p-3 text-sm whitespace-pre-line text-navy-900">{property.messages.email.corpo}</p>
                </div>
              ) : null}
              {(property.messages?.da_ricontrollare ?? []).length ? (
                <p className="text-sm text-amber-800">Da ricontrollare: {(property.messages?.da_ricontrollare ?? []).join("; ")}</p>
              ) : null}
            </div>
          ) : null}
        </section>
        <aside className="space-y-4">
          {property.score !== null || property.discard_reason ? (
            <section className="card space-y-2 p-4 text-sm" aria-labelledby="analisi">
              <h2 id="analisi" className="font-semibold text-navy-900">
                Analisi {property.score !== null ? <span className="tabular-nums">· {property.score}/100</span> : null}
              </h2>
              {property.discard_reason ? (
                <p className="text-slate">Scartata: {DISCARD_LABELS[property.discard_reason] ?? property.discard_reason}</p>
              ) : null}
              {(property.score_reasons ?? []).length ? (
                <ul className="space-y-1 text-navy-900">
                  {(property.score_reasons ?? []).map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              ) : null}
              {property.analysis?.sintesi ? <p className="text-slate italic">{property.analysis.sintesi}</p> : null}
            </section>
          ) : null}
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
