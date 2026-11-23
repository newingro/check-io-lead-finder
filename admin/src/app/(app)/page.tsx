import type { Metadata } from "next";
import Link from "next/link";
import { StateControls } from "@/components/forms/StateControls";
import { Badge, PageHeader } from "@/components/ui";
import { loadRecentActivity, loadSettings, loadState, loadTeam } from "@/lib/data";
import { ACTION_LABELS, formatDateTime } from "@/lib/format";
import { requireMember } from "@/lib/member";

export const metadata: Metadata = { title: "Panoramica" };

export default async function OverviewPage() {
  const member = await requireMember();
  const isOwner = member.role === "titolare";
  const [state, settings, team, activity] = await Promise.all([
    loadState(),
    loadSettings(),
    loadTeam(),
    isOwner ? loadRecentActivity() : Promise.resolve([]),
  ]);
  const activeZones = settings?.zones.filter((z) => z.attiva) ?? [];

  return (
    <>
      <PageHeader title={`Ciao ${member.name.split(" ")[0]}`} description="Lo stato del Lead Finder a colpo d'occhio." />
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card p-6" aria-labelledby="stato-title">
          <h2 id="stato-title" className="text-lg font-semibold text-navy-900">
            Stato dei giri
          </h2>
          <div className="mt-4">
            {state ? <StateControls paused={state.paused} mode={state.mode} canEdit={isOwner} /> : <p className="text-slate">Stato non disponibile.</p>}
          </div>
          {state?.updated_by ? (
            <p className="hint mt-4">
              Ultima modifica: {state.updated_by}, {formatDateTime(state.updated_at)}
            </p>
          ) : null}
        </section>

        <section className="card p-6" aria-labelledby="zone-title">
          <div className="flex items-center justify-between gap-4">
            <h2 id="zone-title" className="text-lg font-semibold text-navy-900">
              Zone attive
            </h2>
            <Link href="/zone" className="text-sm font-semibold text-turq-700 hover:underline">
              {isOwner ? "Gestisci" : "Vedi mappa"}
            </Link>
          </div>
          {activeZones.length === 0 ? (
            <p className="mt-4 text-slate">
              Nessuna zona attiva. {isOwner ? "Aggiungi la prima zona dalla mappa." : "Il titolare non ha ancora impostato le zone."}
            </p>
          ) : (
            <ul className="mt-4 divide-y divide-line">
              {activeZones.map((zone) => (
                <li key={zone.nome} className="flex items-center justify-between py-2.5 text-sm">
                  <span className="font-medium text-navy-900">{zone.nome}</span>
                  <Badge tone="ok">raggio {zone.raggio_km} km</Badge>
                </li>
              ))}
            </ul>
          )}
          {settings ? (
            <p className="hint mt-4">
              Giri: {settings.run_days.join(", ")} alle {settings.run_times.join(", ")} · punteggio minimo {settings.min_score}
            </p>
          ) : null}
        </section>

        <section className="card p-6" aria-labelledby="team-title">
          <div className="flex items-center justify-between gap-4">
            <h2 id="team-title" className="text-lg font-semibold text-navy-900">
              {isOwner ? "Team" : "Il tuo profilo"}
            </h2>
            <Link href="/team" className="text-sm font-semibold text-turq-700 hover:underline">
              Dettagli
            </Link>
          </div>
          <ul className="mt-4 divide-y divide-line">
            {team.map((person) => (
              <li key={person.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
                <span className="font-medium text-navy-900">{person.name}</span>
                <span className="flex gap-2">
                  <Badge>{person.role}</Badge>
                  <Badge tone={person.telegram_linked ? "ok" : "off"}>{person.telegram_linked ? "Telegram ✓" : "Telegram —"}</Badge>
                  {!person.is_active ? <Badge tone="warn">sospeso</Badge> : null}
                </span>
              </li>
            ))}
          </ul>
        </section>

        {isOwner ? (
          <section className="card p-6" aria-labelledby="attivita-title">
            <h2 id="attivita-title" className="text-lg font-semibold text-navy-900">
              Attività recenti
            </h2>
            {activity.length === 0 ? (
              <p className="mt-4 text-slate">Ancora nessuna attività registrata.</p>
            ) : (
              <ul className="mt-4 space-y-3 text-sm">
                {activity.map((item) => (
                  <li key={item.id} className="flex flex-col">
                    <span className="text-navy-900">
                      <strong>{item.actor_label}</strong> {ACTION_LABELS[item.action] ?? item.action}
                    </span>
                    <span className="text-xs text-slate">
                      {formatDateTime(item.created_at)} · da {item.source}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        ) : null}
      </div>
    </>
  );
}
