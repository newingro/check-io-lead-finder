import type { Metadata } from "next";
import { PasswordForm } from "@/app/(auth)/password/PasswordForm";
import { Badge, PageHeader } from "@/components/ui";
import { requireMember } from "@/lib/member";
import { formatShifts } from "@/lib/shifts";

export const metadata: Metadata = { title: "Profilo" };

export default async function ProfilePage() {
  const member = await requireMember();
  return (
    <>
      <PageHeader title="Profilo" description="I dati del tuo account e il cambio password." />
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card space-y-3 p-6 text-sm">
          <h2 className="text-lg font-semibold text-navy-900">Il tuo account</h2>
          <p><span className="text-slate">Nome:</span> <strong>{member.name}</strong></p>
          <p><span className="text-slate">Ruolo:</span> {member.role}</p>
          <p><span className="text-slate">Email:</span> {member.email ?? "—"}</p>
          <p><span className="text-slate">Turni:</span> {formatShifts(member.shifts)}</p>
          <p className="flex flex-wrap gap-2">
            <Badge tone="ok">Verifica in due passaggi attiva</Badge>
            <Badge tone={member.telegram_linked ? "ok" : "off"}>{member.telegram_linked ? "Telegram collegato" : "Telegram non collegato"}</Badge>
          </p>
          <p className="hint">Hai cambiato telefono? Chiedi al titolare di reimpostare la verifica in due passaggi.</p>
        </section>
        <section className="card p-6">
          <h2 className="mb-4 text-lg font-semibold text-navy-900">Cambia password</h2>
          <PasswordForm redirectTo="/profilo" />
        </section>
      </div>
    </>
  );
}
