import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import { SignOutButton } from "./SignOutButton";
import { NavLinks } from "./NavLinks";

export function Shell({ name, role, children }: { name: string; role: string; children: ReactNode }) {
  return (
    <div className="min-h-svh lg:grid lg:grid-cols-[15rem_1fr]">
      <aside className="bg-navy-950 text-white lg:sticky lg:top-0 lg:h-svh">
        <div className="flex items-center justify-between gap-4 px-5 py-4 lg:block lg:px-6 lg:py-7">
          <Link href="/" className="block w-32" aria-label="Gestionale CHECK-iO — Panoramica">
            <Image src="/brand/logo-wordmark-white.png" alt="CHECK-iO" width={1337} height={309} className="h-auto w-full" priority />
          </Link>
          <p className="text-[0.65rem] font-semibold tracking-[0.2em] text-turq-400 uppercase lg:mt-2">Gestionale</p>
        </div>
        <NavLinks />
        <div className="hidden border-t border-white/10 px-6 py-5 text-sm lg:absolute lg:inset-x-0 lg:bottom-0 lg:block">
          <p className="font-semibold">{name}</p>
          <p className="text-white/60">{role}</p>
          <div className="mt-3">
            <SignOutButton className="text-xs text-white/70 underline hover:text-white" />
          </div>
        </div>
      </aside>
      <div className="min-w-0">
        <div className="flex items-center justify-end gap-4 border-b border-line bg-white px-5 py-2 text-sm lg:hidden">
          <span className="text-slate">
            {name} · {role}
          </span>
          <SignOutButton />
        </div>
        <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-10 lg:py-12">{children}</main>
      </div>
    </div>
  );
}
