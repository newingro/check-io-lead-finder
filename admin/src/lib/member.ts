import "server-only";
import { cache } from "react";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import type { Shifts } from "@/lib/shifts";

export interface Member {
  id: string;
  name: string;
  role: "titolare" | "commerciale";
  email: string | null;
  is_active: boolean;
  shifts: Shifts;
  telegram_linked: boolean;
}

export interface Session {
  userId: string;
  email: string | null;
  member: Member | null;
}

/** Sessione corrente con la persona del team collegata (letta rispettando le regole del database). */
export const getSession = cache(async (): Promise<Session | null> => {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const claims = data?.claims;
  if (!claims || claims.aal !== "aal2") return null;
  const { data: row } = await supabase
    .from("lead_finders")
    .select("id, name, role, email, is_active, shifts, telegram_user_id")
    .eq("auth_user_id", claims.sub)
    .maybeSingle();
  const member: Member | null = row
    ? {
        id: row.id,
        name: row.name,
        role: row.role,
        email: row.email,
        is_active: row.is_active,
        shifts: (row.shifts ?? {}) as Shifts,
        telegram_linked: row.telegram_user_id !== null,
      }
    : null;
  return { userId: claims.sub, email: (claims.email as string | undefined) ?? null, member };
});

export async function requireMember(): Promise<Member> {
  const session = await getSession();
  if (!session) redirect("/login");
  if (!session.member || !session.member.is_active) redirect("/non-abilitato");
  return session.member;
}

export async function requireOwner(): Promise<Member> {
  const member = await requireMember();
  if (member.role !== "titolare") redirect("/");
  return member;
}
