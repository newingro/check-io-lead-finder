import type { Metadata } from "next";
import { AuthShell } from "@/components/AuthShell";
import { MfaForm } from "./MfaForm";

export const metadata: Metadata = { title: "Verifica in due passaggi" };

export default function MfaPage() {
  return (
    <AuthShell title="Verifica in due passaggi">
      <MfaForm />
    </AuthShell>
  );
}
