"use client";

import { useNow, useStored } from "@/lib/useApi";

type Theme = "light" | "dark" | "system";
const NEXT: Record<Theme, Theme> = { light: "dark", dark: "system", system: "light" };
const LABEL: Record<Theme, string> = { light: "Light", dark: "Dark", system: "Auto" };

/** Light by default (the designed paper look); Dark; or Auto = follow the device. */
function ThemeToggle() {
  const [theme, setTheme] = useStored<Theme>("finn.theme", "light");
  const choose = () => {
    const next = NEXT[theme];
    setTheme(next);
    document.documentElement.dataset.theme = next;
  };
  return (
    <button className="theme-toggle" onClick={choose}
            aria-label={`Theme: ${LABEL[theme]}. Switch to ${LABEL[NEXT[theme]]}`} title="Change theme">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
        {theme === "light" && <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>}
        {theme === "dark" && <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z" />}
        {theme === "system" && <><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></>}
      </svg>
      {LABEL[theme]}
    </button>
  );
}

/** The paper's nameplate: brand mark left, dateline right. */
export default function Masthead() {
  const now = useNow();
  const date = now?.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
  return (
    <div className="masthead">
      <span className="brand">
        <svg viewBox="0 0 22 16" aria-hidden>
          {[0, 6, 12].map((x) => (
            <line key={x} x1={x + 1} y1={15} x2={x + 8} y2={1} stroke="var(--high)" strokeWidth={2.4} strokeLinecap="round" />
          ))}
        </svg>
        FINN
      </span>
      <span className="row" style={{ gap: 12 }}>
        <span className="dateline">{date ?? " "}</span>
        <ThemeToggle />
      </span>
    </div>
  );
}
