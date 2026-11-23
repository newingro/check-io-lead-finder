import { Shell } from "@/components/Shell";
import { requireMember } from "@/lib/member";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const member = await requireMember();
  return (
    <Shell name={member.name} role={member.role === "titolare" ? "Titolare" : "Commerciale"}>
      {children}
    </Shell>
  );
}
