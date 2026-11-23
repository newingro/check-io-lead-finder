"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Notice } from "@/components/ui";
import { SignOutButton } from "@/components/SignOutButton";
import { createClient } from "@/lib/supabase/client";

type Mode =
  | { kind: "loading" }
  | { kind: "verify"; factorId: string }
  | { kind: "enroll"; factorId: string; qr: string; secret: string }
  | { kind: "error"; message: string };

export function MfaForm() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>({ kind: "loading" });
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const supabase = createClient();
      const { data, error: listError } = await supabase.auth.mfa.listFactors();
      if (listError) {
        if (!cancelled) setMode({ kind: "error", message: "Sessione scaduta: accedi di nuovo." });
        return;
      }
      const verified = data.totp.find((f) => f.status === "verified");
      if (verified) {
        if (!cancelled) setMode({ kind: "verify", factorId: verified.id });
        return;
      }
      // Rimuove eventuali attivazioni lasciate a metà, poi ne crea una nuova.
      for (const factor of data.all.filter((f) => f.factor_type === "totp" && f.status !== "verified")) {
        await supabase.auth.mfa.unenroll({ factorId: factor.id });
      }
      const { data: enrolled, error: enrollError } = await supabase.auth.mfa.enroll({
        factorType: "totp",
        friendlyName: `CHECK-iO ${new Date().toISOString().slice(0, 16)}`,
        issuer: "CHECK-iO Gestionale",
      });
      if (cancelled) return;
      if (enrollError || !enrolled) {
        setMode({ kind: "error", message: "Non è stato possibile attivare la verifica. Ricarica la pagina." });
        return;
      }
      setMode({ kind: "enroll", factorId: enrolled.id, qr: enrolled.totp.qr_code, secret: enrolled.totp.secret });
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode.kind !== "verify" && mode.kind !== "enroll") return;
    const code = String(new FormData(event.currentTarget).get("code") ?? "").replace(/\s/g, "");
    if (!/^\d{6}$/.test(code)) {
      setError("Inserisci il codice di 6 cifre mostrato dall'app.");
      return;
    }
    setPending(true);
    setError(null);
    const { error: verifyError } = await createClient().auth.mfa.challengeAndVerify({ factorId: mode.factorId, code });
    if (verifyError) {
      setPending(false);
      setError("Codice non valido o scaduto. Riprova con il codice attuale.");
      return;
    }
    router.replace("/");
    router.refresh();
  }

  if (mode.kind === "loading") return <p className="text-sm text-slate">Caricamento…</p>;
  if (mode.kind === "error")
    return (
      <div className="space-y-4">
        <Notice tone="error">{mode.message}</Notice>
        <a href="/login" className="text-sm font-semibold text-turq-700 underline">
          Torna all&apos;accesso
        </a>
      </div>
    );

  return (
    <div className="space-y-5">
    <form onSubmit={onSubmit} className="space-y-5" noValidate>
      {mode.kind === "enroll" ? (
        <div className="space-y-4 text-sm text-slate">
          <p>
            Per proteggere il gestionale serve un secondo controllo. Installa sul telefono un&apos;app di autenticazione
            (per esempio <strong>Google Authenticator</strong> o <strong>Microsoft Authenticator</strong>) e inquadra
            questo codice QR.
          </p>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={mode.qr} alt="Codice QR per l'app di autenticazione" className="mx-auto size-48 rounded-md border border-line bg-white p-2" />
          <p>
            Non riesci a inquadrarlo? Inserisci a mano questa chiave:
            <br />
            <code className="mt-1 block break-all rounded bg-mist px-2 py-1 font-mono text-xs text-navy-900">{mode.secret}</code>
          </p>
        </div>
      ) : (
        <p className="text-sm text-slate">Apri l&apos;app di autenticazione sul telefono e inserisci il codice di CHECK-iO.</p>
      )}
      <div>
        <label className="label" htmlFor="code">
          Codice di 6 cifre
        </label>
        <input
          id="code"
          name="code"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={7}
          required
          autoFocus
          className="input text-center font-mono text-xl tracking-[0.4em]"
        />
      </div>
      {error ? <Notice tone="error">{error}</Notice> : null}
      <Button type="submit" disabled={pending} className="w-full">
        {pending ? "Verifica in corso…" : mode.kind === "enroll" ? "Attiva e continua" : "Verifica"}
      </Button>
    </form>
    <div className="text-center">
      <SignOutButton />
    </div>
    </div>
  );
}
