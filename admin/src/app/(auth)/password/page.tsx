import type { Metadata } from "next";
import { AuthShell } from "@/components/AuthShell";
import { PasswordForm } from "./PasswordForm";

export const metadata: Metadata = { title: "Nuova password" };

export default function PasswordPage() {
  return (
    <AuthShell
      title="Scegli la tua password"
      description="Stai usando una password temporanea. Scegline una personale: la userai dai prossimi accessi."
    >
      <PasswordForm />
    </AuthShell>
  );
}
