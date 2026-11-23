"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Gauge, History, Radar, Settings, User, Users } from "lucide-react";
import { cn } from "./ui";

const LINKS = [
  { href: "/", label: "Panoramica", icon: Gauge },
  { href: "/zone", label: "Zone", icon: Radar },
  { href: "/memoria", label: "Memoria", icon: History },
  { href: "/impostazioni", label: "Impostazioni", icon: Settings },
  { href: "/team", label: "Team", icon: Users },
  { href: "/profilo", label: "Profilo", icon: User },
];

export function NavLinks() {
  const pathname = usePathname();
  return (
    <nav aria-label="Sezioni" className="px-3 pb-3 lg:px-3 lg:pb-0">
      <ul className="flex flex-wrap gap-1 lg:flex-col lg:flex-nowrap">
        {LINKS.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex min-h-11 items-center gap-3 rounded-md px-3 text-sm font-medium whitespace-nowrap transition-colors",
                  active ? "bg-white/10 text-white" : "text-white/70 hover:bg-white/5 hover:text-white",
                )}
              >
                <Icon aria-hidden="true" className={cn("size-4", active ? "text-turq-400" : "")} strokeWidth={1.75} />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
