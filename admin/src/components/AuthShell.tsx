import Image from "next/image";
import type { ReactNode } from "react";

/** Cornice delle pagine di accesso. */
export function AuthShell({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <main className="flex min-h-svh items-center justify-center bg-navy-950 px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <Image src="/brand/logo-wordmark-white.png" alt="CHECK-iO" width={1337} height={309} className="h-auto w-40" priority />
          <p className="text-xs font-semibold tracking-[0.2em] text-turq-400 uppercase">Gestionale</p>
        </div>
        <div className="card p-6 sm:p-8">
          <h1 className="text-xl font-semibold text-navy-900">{title}</h1>
          {description ? <div className="mt-2 text-sm text-slate">{description}</div> : null}
          <div className="mt-6">{children}</div>
        </div>
      </div>
    </main>
  );
}
