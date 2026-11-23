"use client";

import { useActionState } from "react";
import { Button, Notice } from "@/components/ui";
import { createOwnerAccount, type SetupState } from "./actions";

export function SetupForm() {
  const [state, action, pending] = useActionState<SetupState, FormData>(createOwnerAccount, { status: "idle" });

  if (state.status === "done") {
    return (
      <div className="space-y-4">
        <Notice tone="ok">Account creato. Ora accedi e attiva la verifica in due passaggi.</Notice>
        <a href="/login" className="inline-flex min-h-11 w-full items-center justify-center rounded-md bg-navy-900 text-sm font-semibold text-white">
          Vai all&apos;accesso
        </a>
      </div>
    );
  }

  return (
    <form action={action} className="space-y-5">
      <div>
        <label className="label" htmlFor="code">
          Codice segreto di configurazione
        </label>
        <input id="code" name="code" type="password" autoComplete="off" required className="input" />
      </div>
      <div>
        <label className="label" htmlFor="name">
          Nome e cognome
        </label>
        <input id="name" name="name" autoComplete="name" required maxLength={80} className="input" />
      </div>
      <div>
        <label className="label" htmlFor="email">
          Email
        </label>
        <input id="email" name="email" type="email" autoComplete="email" required className="input" />
      </div>
      <div>
        <label className="label" htmlFor="password">
          Password
        </label>
        <input id="password" name="password" type="password" autoComplete="new-password" minLength={12} required className="input" />
        <p className="hint">Almeno 12 caratteri.</p>
      </div>
      {state.status === "error" ? <Notice tone="error">{state.message}</Notice> : null}
      <Button type="submit" disabled={pending} className="w-full">
        {pending ? "Creazione in corso…" : "Crea il mio account"}
      </Button>
    </form>
  );
}
