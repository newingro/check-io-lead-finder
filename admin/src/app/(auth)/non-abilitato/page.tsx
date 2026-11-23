import type { Metadata } from "next";
import { AuthShell } from "@/components/AuthShell";
import { SignOutButton } from "@/components/SignOutButton";

export const metadata: Metadata = { title: "Account non abilitato" };

export default function NotEnabledPage() {
  return (
    <AuthShell title="Account non abilitato">
      <p className="text-sm text-slate">
        Il tuo account non è collegato al team CHECK-iO oppure è stato sospeso. Per informazioni contatta il titolare.
      </p>
      <div className="mt-6">
        <SignOutButton className="text-sm font-semibold text-turq-700 underline" label="Esci" />
      </div>
    </AuthShell>
  );
}
