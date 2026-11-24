"use client";

import { useState, useTransition } from "react";
import { saveSettings } from "@/app/(app)/actions";
import { Button, Notice } from "@/components/ui";
import type { SettingsInput } from "@/lib/settings";
import { DAYS } from "@/lib/shifts";

const DAY_LABELS: Record<string, string> = { lun: "Lun", mar: "Mar", mer: "Mer", gio: "Gio", ven: "Ven", sab: "Sab", dom: "Dom" };

function NumberField({ name, label, hint, min, max, step = 1, value, disabled }: {
  name: keyof SettingsInput; label: string; hint?: string; min: number; max: number; step?: number; value: number; disabled: boolean;
}) {
  return (
    <div>
      <label className="label" htmlFor={name}>{label}</label>
      <input id={name} name={name} type="number" min={min} max={max} step={step} defaultValue={value} disabled={disabled} className="input tabular-nums" />
      {hint ? <p className="hint">{hint}</p> : null}
    </div>
  );
}

export function SettingsForm({ settings, canEdit }: { settings: SettingsInput; canEdit: boolean }) {
  const [pending, startTransition] = useTransition();
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const disabled = !canEdit || pending;

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const num = (key: string) => Number(String(form.get(key) ?? "").replace(",", "."));
    const list = (key: string) => String(form.get(key) ?? "").split("\n").map((s) => s.trim()).filter(Boolean);
    const input: SettingsInput = {
      property_types: list("property_types"),
      search_queries: list("search_queries"),
      min_score: num("min_score"),
      cards_per_run: num("cards_per_run"),
      searches_per_run: num("searches_per_run"),
      run_days: form.getAll("run_days").map(String) as SettingsInput["run_days"],
      run_times: String(form.get("run_times") ?? "").split(/[,\s]+/).map((s) => s.trim()).filter(Boolean),
      followup_days: num("followup_days"),
      max_followups: num("max_followups"),
      archive_after_days: num("archive_after_days"),
      max_call_attempts: num("max_call_attempts"),
      call_retry_minutes: num("call_retry_minutes"),
      monthly_ai_budget_eur: num("monthly_ai_budget_eur"),
      monthly_search_budget_eur: num("monthly_search_budget_eur"),
      google_monthly_requests: num("google_monthly_requests"),
      data_retention_months: num("data_retention_months"),
    };
    startTransition(async () => {
      const result = await saveSettings(input);
      setMessage(result.ok ? { tone: "ok", text: "Impostazioni salvate. Il bot le applica entro 5 minuti." } : { tone: "error", text: result.error });
    });
  }

  return (
    <form onSubmit={onSubmit} className="space-y-6">
      <fieldset disabled={disabled} className="card grid gap-5 p-6 sm:grid-cols-2">
        <legend className="sr-only">Ricerca</legend>
        <h2 className="text-lg font-semibold text-navy-900 sm:col-span-2">Ricerca e punteggio</h2>
        <div>
          <label className="label" htmlFor="property_types">Tipi di struttura</label>
          <textarea id="property_types" name="property_types" rows={6} defaultValue={settings.property_types.join("\n")} className="input" />
          <p className="hint">Uno per riga.</p>
        </div>
        <div>
          <label className="label" htmlFor="search_queries">Ricerche su Google</label>
          <textarea id="search_queries" name="search_queries" rows={6} defaultValue={settings.search_queries.join("\n")} className="input" />
          <p className="hint">Una per riga, per esempio &quot;casa vacanze&quot;.</p>
        </div>
        <NumberField name="min_score" label="Punteggio minimo (0–100)" hint="Sotto questo valore la struttura viene scartata." min={0} max={100} value={settings.min_score} disabled={disabled} />
        <NumberField name="cards_per_run" label="Schede per giro" min={1} max={50} value={settings.cards_per_run} disabled={disabled} />
        <NumberField name="searches_per_run" label="Ricerche Google per giro" hint="Ogni ricerca è una cella del radar con una parola: costa, quindi parti basso (0 = nessuna ricerca)." min={0} max={50} value={settings.searches_per_run} disabled={disabled} />
      </fieldset>

      <fieldset disabled={disabled} className="card grid gap-5 p-6 sm:grid-cols-2">
        <legend className="sr-only">Giri</legend>
        <h2 className="text-lg font-semibold text-navy-900 sm:col-span-2">Giri programmati</h2>
        <div className="sm:col-span-2">
          <span className="label">Giorni</span>
          <div className="flex flex-wrap gap-2">
            {DAYS.map((day) => (
              <label key={day} className="flex min-h-10 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm has-[:checked]:border-turq-600 has-[:checked]:bg-turq-500/10">
                <input type="checkbox" name="run_days" value={day} defaultChecked={settings.run_days.includes(day)} className="accent-turq-600" />
                {DAY_LABELS[day]}
              </label>
            ))}
          </div>
        </div>
        <div className="sm:col-span-2">
          <label className="label" htmlFor="run_times">Orari</label>
          <input id="run_times" name="run_times" defaultValue={settings.run_times.join(", ")} className="input" />
          <p className="hint">Separati da virgola, per esempio 10:00, 12:30, 15:00.</p>
        </div>
      </fieldset>

      <fieldset disabled={disabled} className="card grid gap-5 p-6 sm:grid-cols-2">
        <legend className="sr-only">Contatti</legend>
        <h2 className="text-lg font-semibold text-navy-900 sm:col-span-2">Follow-up e telefonate</h2>
        <NumberField name="followup_days" label="Follow-up dopo (giorni)" min={1} max={60} value={settings.followup_days} disabled={disabled} />
        <NumberField name="max_followups" label="Follow-up massimi" min={0} max={5} value={settings.max_followups} disabled={disabled} />
        <NumberField name="archive_after_days" label="Archivio dopo (giorni senza risposta)" min={1} max={365} value={settings.archive_after_days} disabled={disabled} />
        <NumberField name="max_call_attempts" label="Tentativi di chiamata" min={1} max={10} value={settings.max_call_attempts} disabled={disabled} />
        <NumberField name="call_retry_minutes" label="Richiamo dopo (minuti)" hint="Almeno 120 minuti per chi non risponde." min={30} max={1440} value={settings.call_retry_minutes} disabled={disabled} />
      </fieldset>

      <fieldset disabled={disabled} className="card grid gap-5 p-6 sm:grid-cols-2">
        <legend className="sr-only">Costi e dati</legend>
        <h2 className="text-lg font-semibold text-navy-900 sm:col-span-2">Costi e conservazione dei dati</h2>
        <NumberField name="monthly_ai_budget_eur" label="Tetto mensile AI (€)" min={0} max={10000} step={0.01} value={settings.monthly_ai_budget_eur} disabled={disabled} />
        <NumberField name="monthly_search_budget_eur" label="Tetto mensile ricerche (€)" min={0} max={10000} step={0.01} value={settings.monthly_search_budget_eur} disabled={disabled} />
        <NumberField
          name="google_monthly_requests"
          label="Massimo richieste Google al mese"
          hint="Le richieste gratuite di Google: pagina prezzi di Google Maps Platform → Places API → «Text Search Enterprise + Atmosphere» → richieste gratuite al mese. Raggiunto il numero il bot si ferma da solo. 0 = ricerca solo col prezzo impostato sul server."
          min={0}
          max={1000000}
          value={settings.google_monthly_requests}
          disabled={disabled}
        />
        <NumberField name="data_retention_months" label="Conservazione dati (mesi)" hint="Dopo questo periodo le strutture vengono archiviate." min={1} max={60} value={settings.data_retention_months} disabled={disabled} />
      </fieldset>

      {message ? <Notice tone={message.tone}>{message.text}</Notice> : null}
      {canEdit ? (
        <Button type="submit" disabled={pending}>{pending ? "Salvataggio…" : "Salva le impostazioni"}</Button>
      ) : (
        <Notice tone="info">Le impostazioni le modifica il titolare. Tu puoi consultarle.</Notice>
      )}
    </form>
  );
}
