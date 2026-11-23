import type { Metadata } from "next";
import { TeamManager } from "@/components/team/TeamManager";
import { PageHeader } from "@/components/ui";
import { loadTeam } from "@/lib/data";
import { TELEGRAM_BOT_USERNAME } from "@/lib/env";
import { requireMember } from "@/lib/member";

export const metadata: Metadata = { title: "Team" };

export default async function TeamPage() {
  const member = await requireMember();
  const team = await loadTeam();
  const isOwner = member.role === "titolare";
  return (
    <>
      <PageHeader
        title={isOwner ? "Team" : "Il tuo profilo nel team"}
        description={
          isOwner
            ? "Le persone che usano il bot e il gestionale: account, ruoli, turni e collegamento a Telegram."
            : "Ruolo, turni e collegamenti del tuo account."
        }
      />
      <TeamManager team={team} selfId={member.id} isOwner={isOwner} botUsername={TELEGRAM_BOT_USERNAME} />
    </>
  );
}
