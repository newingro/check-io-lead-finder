"use client";

import { useState, useTransition } from "react";
import { RotateCcw } from "lucide-react";
import { releaseProperty } from "@/app/(app)/actions";
import { Button, Notice } from "@/components/ui";

/** Solo il titolare: la struttura torna «nuova» e il bot potrà riproporla. */
export function ReleaseForm({ propertyId }: { propertyId: string }) {
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [pending, startTransition] = useTransition();

  function submit() {
    startTransition(async () => {
      const result = await releaseProperty(propertyId, reason);
      setConfirming(false);
      setMessage(result.ok ? { tone: "ok", text: "Fatto: la struttura tornerà tra le nuove da proporre." } : { tone: "error", text: result.error });
    });
  }

  return (
    <section className="card space-y-3 p-4" aria-labelledby="rimetti">
      <h2 id="rimetti" className="font-semibold text-navy-900">
        Rimetti in ricerca
      </h2>
      <p className="text-sm text-slate">Di solito il radar non ripropone mai una struttura già vista. Qui puoi farla tornare tra le nuove, per esempio dopo un anno.</p>
      {confirming ? (
        <>
          <label className="label" htmlFor="motivo">
            Motivo (facoltativo)
          </label>
          <input id="motivo" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} className="input" placeholder="Es. nuovo proprietario" />
          <div className="flex gap-2">
            <Button type="button" onClick={submit} disabled={pending}>
              {pending ? "Attendere…" : "Conferma"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setConfirming(false)} disabled={pending}>
              Annulla
            </Button>
          </div>
        </>
      ) : (
        <Button type="button" variant="secondary" onClick={() => setConfirming(true)} className="w-full">
          <RotateCcw aria-hidden="true" className="size-4" /> Rimetti in ricerca
        </Button>
      )}
      {message ? <Notice tone={message.tone}>{message.text}</Notice> : null}
    </section>
  );
}
