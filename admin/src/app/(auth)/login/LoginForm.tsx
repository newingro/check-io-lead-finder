"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Notice } from "@/components/ui";
import { createClient } from "@/lib/supabase/client";

export function LoginForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    const { error: signInError } = await createClient().auth.signInWithPassword({
      email: String(form.get("email") ?? "").trim(),
      password: String(form.get("password") ?? ""),
    });
    if (signInError) {
      setPending(false);
      setError(
        signInError.status === 429
          ? "Troppi tentativi. Attendi qualche minuto e riprova."
          : "Email o password non corretti.",
      );
      return;
    }
    router.replace("/mfa");
    router.refresh();
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate>
      <div>
        <label className="label" htmlFor="email">
          Email
        </label>
        <input id="email" name="email" type="email" autoComplete="username" required className="input" />
      </div>
      <div>
        <label className="label" htmlFor="password">
          Password
        </label>
        <input id="password" name="password" type="password" autoComplete="current-password" required className="input" />
      </div>
      {error ? <Notice tone="error">{error}</Notice> : null}
      <Button type="submit" disabled={pending} className="w-full">
        {pending ? "Accesso in corso…" : "Accedi"}
      </Button>
      <p className="text-center text-xs text-slate">
        Password dimenticata? Chiedi al titolare di reimpostarla dal gestionale.
      </p>
    </form>
  );
}
