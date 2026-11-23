"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Notice } from "@/components/ui";
import { createClient } from "@/lib/supabase/client";
import { clearPasswordChangeFlag } from "./actions";

export function PasswordForm({ redirectTo = "/" }: { redirectTo?: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formEl = event.currentTarget;
    const form = new FormData(formEl);
    const password = String(form.get("password") ?? "");
    const confirm = String(form.get("confirm") ?? "");
    if (password.length < 12) return setError("La password deve avere almeno 12 caratteri.");
    if (password !== confirm) return setError("Le due password non coincidono.");
    setPending(true);
    setError(null);
    const supabase = createClient();
    const { error: updateError } = await supabase.auth.updateUser({ password });
    if (updateError) {
      setPending(false);
      setError(
        updateError.code === "same_password"
          ? "La nuova password deve essere diversa da quella attuale."
          : "Non è stato possibile cambiare la password. Riprova.",
      );
      return;
    }
    const result = await clearPasswordChangeFlag();
    await supabase.auth.refreshSession();
    setPending(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    formEl.reset();
    setDone(true);
    router.replace(redirectTo);
    router.refresh();
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate>
      <div>
        <label className="label" htmlFor="password">
          Nuova password
        </label>
        <input id="password" name="password" type="password" autoComplete="new-password" minLength={12} required className="input" />
        <p className="hint">Almeno 12 caratteri. Meglio una frase facile da ricordare.</p>
      </div>
      <div>
        <label className="label" htmlFor="confirm">
          Ripeti la password
        </label>
        <input id="confirm" name="confirm" type="password" autoComplete="new-password" required className="input" />
      </div>
      {error ? <Notice tone="error">{error}</Notice> : null}
      {done ? <Notice tone="ok">Password aggiornata.</Notice> : null}
      <Button type="submit" disabled={pending} className="w-full">
        {pending ? "Salvataggio…" : "Salva la password"}
      </Button>
    </form>
  );
}
