import Link from "next/link";
import { Search } from "lucide-react";
import { Badge, buttonClass } from "@/components/ui";
import { STATUS_LABELS, type MemorySummary, type PropertyRow } from "@/lib/data";
import { formatDateTime } from "@/lib/format";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card p-4">
      <p className="text-xs font-semibold tracking-wide text-slate uppercase">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-navy-900 tabular-nums">{value}</p>
      {hint ? <p className="mt-0.5 text-xs text-slate">{hint}</p> : null}
    </div>
  );
}

const number = new Intl.NumberFormat("it-IT");

export function MemoryView({
  summary,
  rows,
  filters,
  provinceNames,
  isOwner,
}: {
  summary: MemorySummary | null;
  rows: PropertyRow[];
  filters: { q?: string; stato?: string };
  provinceNames: Record<string, string>;
  isOwner: boolean;
}) {
  const s = summary ?? { strutture: 0, impronte: 0, consultate: 0, celle_esplorate: 0, ricerche: 0, ultima_ricerca: null };
  const filtered = Boolean(filters.q || filters.stato);
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Strutture in memoria" value={number.format(s.strutture)} hint="Non verranno mai riproposte come nuove" />
        <Stat label="Già consultate" value={number.format(s.consultate)} hint="Aperte da qualcuno del team" />
        <Stat label="Celle esplorate" value={number.format(s.celle_esplorate)} hint={`${number.format(s.ricerche)} ricerche fatte`} />
        <Stat label="Ultima ricerca" value={s.ultima_ricerca ? formatDateTime(s.ultima_ricerca).split(",")[0] : "—"} hint={`${number.format(s.impronte)} impronte salvate`} />
      </div>

      <form method="get" className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-end" role="search">
        <div className="min-w-0 flex-1">
          <label className="label" htmlFor="q">
            Cerca per nome
          </label>
          <input id="q" name="q" defaultValue={filters.q ?? ""} placeholder="Es. Baita" className="input" />
        </div>
        <div className="sm:w-48">
          <label className="label" htmlFor="stato">
            Stato
          </label>
          <select id="stato" name="stato" defaultValue={filters.stato ?? ""} className="input">
            <option value="">Tutti</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <button type="submit" className={buttonClass("secondary")}>
          <Search aria-hidden="true" className="size-4" /> Cerca
        </button>
      </form>

      <section className="card overflow-hidden" aria-labelledby="memoria-elenco">
        <h2 id="memoria-elenco" className="border-b border-line px-4 py-3 font-semibold text-navy-900">
          {filtered ? "Risultati" : "Strutture trovate"} ({rows.length}
          {rows.length === 100 ? "+" : ""})
        </h2>
        {rows.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-slate">
            {filtered
              ? "Nessuna struttura con questi filtri."
              : isOwner
                ? "La memoria è vuota. Le strutture compariranno qui quando il radar inizierà a cercare."
                : "Qui compariranno le strutture assegnate a te."}
          </p>
        ) : (
          <ul className="divide-y divide-line">
            {rows.map((row) => (
              <li key={row.id}>
                <Link href={`/memoria/${row.id}`} className="grid gap-1 px-4 py-3 hover:bg-paper sm:grid-cols-[1fr_auto] sm:items-center sm:gap-4">
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-navy-900">{row.name}</span>
                    <span className="block text-xs text-slate">
                      {[row.property_type, row.zone, row.provincia ? provinceNames[row.provincia] : null].filter(Boolean).join(" · ") || "—"}
                    </span>
                  </span>
                  <span className="flex flex-wrap items-center gap-2 text-xs text-slate sm:justify-end">
                    <Badge tone={row.status === "cliente" ? "ok" : row.status === "scartato" || row.status === "perso" ? "off" : "neutral"}>
                      {STATUS_LABELS[row.status] ?? row.status}
                    </Badge>
                    <span>Trovata il {formatDateTime(row.created_at).split(",")[0]}</span>
                    {row.times_seen > 1 ? <span>· ritrovata {row.times_seen - 1} {row.times_seen === 2 ? "volta" : "volte"}</span> : null}
                    <span>
                      ·{" "}
                      {row.last_viewed_at
                        ? `consultata ${row.last_viewed_by_name ? `da ${row.last_viewed_by_name} ` : ""}il ${formatDateTime(row.last_viewed_at)}`
                        : "mai consultata"}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
