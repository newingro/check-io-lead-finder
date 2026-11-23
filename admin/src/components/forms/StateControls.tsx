"use client";

import { useState, useTransition } from "react";
import { setMode, setPaused } from "@/app/(app)/actions";
import { Button, cn, Notice } from "@/components/ui";

const MODE_LABELS = {
  telefonate: "Solo telefonate",
  messaggi: "Solo messaggi",
  misto: "Misto",
} as const;

export function StateControls({ paused, mode, canEdit }: { paused: boolean; mode: keyof typeof MODE_LABELS; canEdit: boolean }) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const run = (fn: () => Promise<{ ok: boolean; error?: string }>) =>
    startTransition(async () => {
      setError(null);
      const result = await fn();
      if (!result.ok) setError(result.error ?? "Operazione non riuscita.");
    });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={cn(
            "inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-semibold",
            paused ? "bg-amber-100 text-amber-800" : "bg-turq-500/15 text-turq-700",
          )}
        >
          <span aria-hidden="true" className={cn("size-2 rounded-full", paused ? "bg-amber-500" : "bg-turq-500")} />
          {paused ? "Giri in pausa" : "Giri attivi"}
        </span>
        {canEdit ? (
          <Button variant="secondary" disabled={pending} onClick={() => run(() => setPaused(!paused))}>
            {paused ? "Riprendi i giri" : "Metti in pausa"}
          </Button>
        ) : null}
      </div>
      <fieldset disabled={!canEdit || pending}>
        <legend className="label">Modalità</legend>
        <div className="flex flex-wrap gap-2">
          {(Object.keys(MODE_LABELS) as (keyof typeof MODE_LABELS)[]).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={mode === value}
              onClick={() => mode !== value && run(() => setMode(value))}
              className={cn(
                "min-h-10 rounded-md border px-3 text-sm font-medium transition-colors disabled:cursor-not-allowed",
                mode === value ? "border-turq-600 bg-turq-500/10 text-navy-900" : "border-line bg-white text-slate hover:border-navy-900/30",
              )}
            >
              {MODE_LABELS[value]}
            </button>
          ))}
        </div>
      </fieldset>
      {error ? <Notice tone="error">{error}</Notice> : null}
      {canEdit ? <p className="hint">Il bot applica le modifiche entro 5 minuti e le comunica su Telegram.</p> : null}
    </div>
  );
}
