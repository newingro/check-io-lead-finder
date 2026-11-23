"use client";

import { useState, useTransition } from "react";
import { Copy, KeyRound, MessageCircle, Pencil, ShieldOff, UserPlus } from "lucide-react";
import {
  addPerson,
  createAccount,
  createTelegramCode,
  resetPassword,
  resetTwoFactor,
  setMemberActive,
  updateMember,
} from "@/app/(app)/actions";
import { Badge, Button, cn, Notice } from "@/components/ui";
import type { TeamRow } from "@/lib/data";
import { DAYS, formatShifts } from "@/lib/shifts";

type Secret = { title: string; value: string; instructions: string };

function SecretPanel({ secret, onClose }: { secret: Secret; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div role="status" className="rounded-lg border border-turq-500/40 bg-ok-soft p-4">
      <p className="font-semibold text-navy-900">{secret.title}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <code className="rounded bg-white px-3 py-1.5 font-mono text-lg tracking-wider text-navy-900">{secret.value}</code>
        <Button
          type="button"
          variant="secondary"
          className="min-h-9"
          onClick={async () => {
            await navigator.clipboard.writeText(secret.value).catch(() => undefined);
            setCopied(true);
          }}
        >
          <Copy aria-hidden="true" className="size-4" /> {copied ? "Copiato" : "Copia"}
        </Button>
      </div>
      <p className="mt-2 text-sm text-slate">{secret.instructions}</p>
      <button type="button" onClick={onClose} className="mt-3 text-sm font-semibold text-turq-700 underline">
        Ho preso nota, chiudi
      </button>
    </div>
  );
}

function shiftValues(person: TeamRow) {
  const days = DAYS.filter((d) => person.shifts[d]?.length);
  const first = days.length ? person.shifts[days[0]]![0] : ["09:00", "17:00"];
  return { days: days.length ? days : (["lun", "mar", "mer", "gio", "ven"] as string[]), start: first[0], end: first[1] };
}

function PersonCard({
  person,
  isSelf,
  isOwner,
  botUsername,
  onSecret,
}: {
  person: TeamRow;
  isSelf: boolean;
  isOwner: boolean;
  botUsername: string;
  onSecret: (secret: Secret) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [creatingAccess, setCreatingAccess] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const shifts = shiftValues(person);

  const run = (fn: () => Promise<{ ok: boolean; error?: string }>, after?: () => void) =>
    startTransition(async () => {
      setError(null);
      const result = await fn();
      if (!result.ok) setError(result.error ?? "Operazione non riuscita.");
      else after?.();
    });

  const bot = botUsername ? `@${botUsername}` : "il bot CHECK-iO";

  return (
    <li className={cn("card p-5", !person.is_active && "opacity-70")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-navy-900">
            {person.name} {isSelf ? <span className="text-sm font-normal text-slate">(tu)</span> : null}
          </p>
          <p className="text-sm text-slate">{person.email ?? "nessun account del gestionale"}</p>
          <p className="mt-1 text-sm text-slate">Turni: {formatShifts(person.shifts)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge>{person.role}</Badge>
          <Badge tone={person.has_account ? "ok" : "off"}>{person.has_account ? "Gestionale ✓" : "Gestionale —"}</Badge>
          <Badge tone={person.telegram_linked ? "ok" : "off"}>{person.telegram_linked ? "Telegram ✓" : "Telegram —"}</Badge>
          {!person.is_active ? <Badge tone="warn">sospeso</Badge> : null}
        </div>
      </div>

      {isOwner ? (
        <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-4">
          <Button type="button" variant="secondary" className="min-h-9" onClick={() => setEditing((v) => !v)}>
            <Pencil aria-hidden="true" className="size-4" /> Modifica
          </Button>
          {!person.has_account ? (
            <Button type="button" variant="secondary" className="min-h-9" onClick={() => setCreatingAccess((v) => !v)}>
              <UserPlus aria-hidden="true" className="size-4" /> Crea accesso al gestionale
            </Button>
          ) : null}
          <Button
            type="button"
            variant="secondary"
            className="min-h-9"
            disabled={pending}
            onClick={() =>
              run(async () => {
                const result = await createTelegramCode(person.id);
                if (result.ok)
                  onSecret({
                    title: `Codice Telegram per ${person.name}`,
                    value: result.code,
                    instructions: `${person.name} deve aprire ${bot} su Telegram e scrivere /collega ${result.code} entro 15 minuti. Funziona una sola volta.`,
                  });
                return result;
              })
            }
          >
            <MessageCircle aria-hidden="true" className="size-4" /> Codice Telegram
          </Button>
          {person.has_account && !isSelf ? (
            <>
              <Button
                type="button"
                variant="secondary"
                className="min-h-9"
                disabled={pending}
                onClick={() =>
                  confirm(`Reimpostare la password di ${person.name}?`) &&
                  run(async () => {
                    const result = await resetPassword(person.id);
                    if (result.ok)
                      onSecret({
                        title: `Password temporanea di ${person.name}`,
                        value: result.password,
                        instructions: "Comunicala di persona o al telefono. Al primo accesso verrà chiesto di sceglierne una nuova.",
                      });
                    return result;
                  })
                }
              >
                <KeyRound aria-hidden="true" className="size-4" /> Reimposta password
              </Button>
              <Button
                type="button"
                variant="secondary"
                className="min-h-9"
                disabled={pending}
                onClick={() =>
                  confirm(`Reimpostare la verifica in due passaggi di ${person.name}? Al prossimo accesso dovrà configurarla di nuovo.`) &&
                  run(() => resetTwoFactor(person.id))
                }
              >
                <ShieldOff aria-hidden="true" className="size-4" /> Reimposta 2FA
              </Button>
            </>
          ) : null}
          {!isSelf ? (
            <Button
              type="button"
              variant={person.is_active ? "danger" : "secondary"}
              className="min-h-9"
              disabled={pending}
              onClick={() =>
                (!person.is_active || confirm(`Sospendere ${person.name}? Non potrà più accedere né usare il bot.`)) &&
                run(() => setMemberActive(person.id, !person.is_active))
              }
            >
              {person.is_active ? "Sospendi" : "Riattiva"}
            </Button>
          ) : null}
        </div>
      ) : null}

      {editing ? (
        <form
          className="mt-4 grid gap-4 rounded-md bg-paper p-4 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            run(
              () =>
                updateMember({
                  memberId: person.id,
                  name: String(form.get("name") ?? ""),
                  role: String(form.get("role")) as "titolare" | "commerciale",
                  days: form.getAll("days").map(String) as (typeof DAYS)[number][],
                  start: String(form.get("start") ?? ""),
                  end: String(form.get("end") ?? ""),
                }),
              () => setEditing(false),
            );
          }}
        >
          <div>
            <label className="label" htmlFor={`name-${person.id}`}>Nome</label>
            <input id={`name-${person.id}`} name="name" defaultValue={person.name} maxLength={80} className="input" />
          </div>
          <div>
            <label className="label" htmlFor={`role-${person.id}`}>Ruolo</label>
            <select id={`role-${person.id}`} name="role" defaultValue={person.role} className="input" disabled={isSelf}>
              <option value="commerciale">Commerciale</option>
              <option value="titolare">Titolare</option>
            </select>
            {isSelf ? <input type="hidden" name="role" value={person.role} /> : null}
          </div>
          <div className="sm:col-span-2">
            <span className="label">Giorni di turno</span>
            <div className="flex flex-wrap gap-2">
              {DAYS.map((day) => (
                <label key={day} className="flex min-h-9 items-center gap-1.5 rounded-md border border-line bg-white px-2.5 text-sm has-[:checked]:border-turq-600">
                  <input type="checkbox" name="days" value={day} defaultChecked={shifts.days.includes(day)} className="accent-turq-600" />
                  {day}
                </label>
              ))}
            </div>
          </div>
          <div>
            <label className="label" htmlFor={`start-${person.id}`}>Dalle</label>
            <input id={`start-${person.id}`} name="start" type="time" defaultValue={shifts.start} className="input" />
          </div>
          <div>
            <label className="label" htmlFor={`end-${person.id}`}>Alle</label>
            <input id={`end-${person.id}`} name="end" type="time" defaultValue={shifts.end} className="input" />
          </div>
          <div className="flex gap-2 sm:col-span-2">
            <Button type="submit" disabled={pending}>Salva</Button>
            <Button type="button" variant="ghost" onClick={() => setEditing(false)}>Annulla</Button>
          </div>
        </form>
      ) : null}

      {creatingAccess ? (
        <form
          className="mt-4 flex flex-col gap-3 rounded-md bg-paper p-4 sm:flex-row sm:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            const email = String(new FormData(event.currentTarget).get("email") ?? "");
            run(async () => {
              const result = await createAccount({ name: person.name, email, role: person.role, memberId: person.id });
              if (result.ok) {
                setCreatingAccess(false);
                onSecret({
                  title: `Password temporanea di ${person.name}`,
                  value: result.password,
                  instructions: `Accesso: admin.check-io.it con ${email}. Comunicala di persona: al primo accesso sceglierà una password sua e attiverà la verifica in due passaggi.`,
                });
              }
              return result;
            });
          }}
        >
          <div className="flex-1">
            <label className="label" htmlFor={`email-${person.id}`}>Email per l&apos;accesso</label>
            <input id={`email-${person.id}`} name="email" type="email" required className="input" />
          </div>
          <Button type="submit" disabled={pending}>Crea accesso</Button>
        </form>
      ) : null}

      {error ? <div className="mt-3"><Notice tone="error">{error}</Notice></div> : null}
    </li>
  );
}

export function TeamManager({
  team,
  selfId,
  isOwner,
  botUsername,
}: {
  team: TeamRow[];
  selfId: string;
  isOwner: boolean;
  botUsername: string;
}) {
  const [secret, setSecret] = useState<Secret | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  return (
    <div className="space-y-6">
      {secret ? <SecretPanel secret={secret} onClose={() => setSecret(null)} /> : null}

      {isOwner ? (
        <form
          className="card grid gap-4 p-5 sm:grid-cols-[1fr_1fr_10rem_auto] sm:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            const formEl = event.currentTarget;
            const form = new FormData(formEl);
            const name = String(form.get("name") ?? "");
            const email = String(form.get("email") ?? "").trim();
            const role = String(form.get("role") ?? "commerciale") as "titolare" | "commerciale";
            startTransition(async () => {
              setError(null);
              if (email) {
                const result = await createAccount({ name, email, role });
                if (!result.ok) return setError(result.error);
                setSecret({
                  title: `Password temporanea di ${name}`,
                  value: result.password,
                  instructions: `Accesso: admin.check-io.it con ${email}. Comunicala di persona: al primo accesso sceglierà una password sua e attiverà la verifica in due passaggi.`,
                });
              } else {
                const result = await addPerson({ name, role });
                if (!result.ok) return setError(result.error);
              }
              formEl.reset();
            });
          }}
        >
          <div>
            <label className="label" htmlFor="new-name">Nome e cognome</label>
            <input id="new-name" name="name" required maxLength={80} className="input" />
          </div>
          <div>
            <label className="label" htmlFor="new-email">Email (per il gestionale)</label>
            <input id="new-email" name="email" type="email" placeholder="facoltativa" className="input" />
          </div>
          <div>
            <label className="label" htmlFor="new-role">Ruolo</label>
            <select id="new-role" name="role" defaultValue="commerciale" className="input">
              <option value="commerciale">Commerciale</option>
              <option value="titolare">Titolare</option>
            </select>
          </div>
          <Button type="submit" disabled={pending}>
            <UserPlus aria-hidden="true" className="size-4" /> Aggiungi
          </Button>
          <p className="hint sm:col-span-4">
            Con l&apos;email viene creato anche l&apos;accesso al gestionale, con una password temporanea. Senza email la persona
            potrà usare solo il bot Telegram.
          </p>
        </form>
      ) : null}
      {error ? <Notice tone="error">{error}</Notice> : null}

      <ul className="space-y-4">
        {team.map((person) => (
          <PersonCard
            key={person.id}
            person={person}
            isSelf={person.id === selfId}
            isOwner={isOwner}
            botUsername={botUsername}
            onSecret={setSecret}
          />
        ))}
      </ul>
      {!isOwner ? <Notice tone="info">Per cambiare turni o collegare Telegram rivolgiti al titolare.</Notice> : null}
    </div>
  );
}
