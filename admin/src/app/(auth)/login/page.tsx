import type { Metadata } from "next";
import { AuthShell } from "@/components/AuthShell";
import { LoginForm } from "./LoginForm";

export const metadata: Metadata = { title: "Accedi" };

export default function LoginPage() {
  return (
    <AuthShell title="Accedi" description="Area riservata al team CHECK-iO.">
      <LoginForm />
    </AuthShell>
  );
}
