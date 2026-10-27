"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Alert } from "@/lib/api";
import { useApi } from "@/lib/useApi";

const TABS = [
  { href: "/", label: "Today", icon: <path d="M4 5h16M4 12h16M4 19h10" /> },
  { href: "/alerts", label: "Alerts", icon: <path d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6M10 19a2 2 0 0 0 4 0" /> },
  { href: "/research", label: "Research", icon: <path d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM20 20l-4-4" /> },
  { href: "/portfolio", label: "Portfolio", icon: <path d="M4 19V10M10 19V5M16 19v-7M22 19H2" /> },
];

export default function Nav() {
  return <NavBar path={usePathname()} />;
}

/** Rendered with path="" as the Suspense fallback, so the bar is in the static shell. */
export function NavBar({ path }: { path: string }) {
  const { data: unseen } = useApi<Alert[]>("/api/alerts?unseen=true", 60_000);
  return (
    <nav className="nav" aria-label="Main">
      <div className="nav-inner">
        {TABS.map((t) => {
          const active = t.href === "/" ? path === "/" : path.startsWith(t.href);
          return (
            <Link key={t.href} href={t.href} aria-current={active ? "page" : undefined}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={active ? 2.2 : 1.7}
                   strokeLinecap="round" strokeLinejoin="round" aria-hidden>{t.icon}</svg>
              {t.label}
              {t.href === "/alerts" && !!unseen?.length && <span className="badge">{unseen.length}</span>}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
