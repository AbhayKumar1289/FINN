"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import type { Alert } from "@/lib/api";
import { useFollowUps } from "@/lib/followups";
import { useApi } from "@/lib/useApi";

const TABS = [
  { href: "/", label: "Today", icon: <path d="M4 11.5 12 4l8 7.5V20h-5.5v-5h-5v5H4z" /> },
  { href: "/alerts", label: "Alerts", icon: <path d="M6 10a6 6 0 1 1 12 0c0 5 2 6.5 2 6.5H4S6 15 6 10M10 19.5a2 2 0 0 0 4 0" /> },
  { href: "/research", label: "Research", icon: <path d="M6 3h9l4 4v14H6zM14.5 3v4.5H19M9 11h7M9 14.5h7M9 18h4" /> },
  { href: "/followups", label: "Follow-ups", icon: <path d="M6.5 3.5h11v17l-5.5-3.8-5.5 3.8z" /> },
  { href: "/portfolio", label: "Portfolio", icon: <path d="M4 20V11h3v9M10.5 20V5h3v15M17 20v-7h3v7M3 20.5h18" /> },
];

export default function Nav() {
  return <NavBar path={usePathname()} />;
}

/** Rendered with path="" as the Suspense fallback, so the bar is in the static shell. */
export function NavBar({ path }: { path: string }) {
  const { data: unseen, reload } = useApi<Alert[]>("/api/alerts?unseen=true", 60_000);
  const { open } = useFollowUps();
  useEffect(() => {
    window.addEventListener("finn-alerts", reload);
    return () => window.removeEventListener("finn-alerts", reload);
  }, [reload]);
  return (
    <nav className="nav" aria-label="Main">
      <div className="nav-inner">
        {TABS.map((t) => {
          const active = t.href === "/" ? path === "/" : path.startsWith(t.href);
          const count = t.href === "/alerts" ? unseen?.length ?? 0 : t.href === "/followups" ? open.length : 0;
          const label = t.href === "/followups" ? "open" : "unread";
          return (
            <Link key={t.href} href={t.href} aria-current={active ? "page" : undefined}
                  aria-label={count ? `${t.label}, ${count} ${label}` : t.label}>
              <svg viewBox="0 0 24 24" fill={active ? "currentColor" : "none"} fillOpacity={active ? 0.16 : 0}
                   stroke="currentColor" strokeWidth={active ? 2 : 1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                {t.icon}
              </svg>
              {t.label}
              {count > 0 && (t.href === "/followups"
                ? <span className="count num" aria-hidden>{count}</span>
                : <span className="ping" aria-hidden />)}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
