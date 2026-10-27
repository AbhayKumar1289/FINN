"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { Alert, Card, Digest } from "@/lib/api";
import { ago, greeting, todayLong } from "@/lib/format";
import { useApi, useNow, useStored } from "@/lib/useApi";
import AskSheet from "./AskSheet";
import EventCard from "./EventCard";

const WINDOWS = [
  { key: "24", label: "24h", hours: 24 },
  { key: "72", label: "3d", hours: 72 },
  { key: "168", label: "7d", hours: 168 },
  { key: "custom", label: "Since…", hours: 0 },
];

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

export default function Today() {
  const [win, setWin] = useStored("finn.window", "24");
  const [since, setSince] = useStored("finn.since", "");
  const [reviewed, setReviewed] = useStored<number[]>("finn.reviewed", []);
  const [asking, setAsking] = useState<Card | null>(null);
  const now = useNow();

  const path = win === "custom" && since
    ? `/api/digest?since=${encodeURIComponent(new Date(since).toISOString())}`
    : `/api/digest?hours=${WINDOWS.find((w) => w.key === win)?.hours || 24}`;
  const { data, error, loading } = useApi<Digest>(path, 5 * 60_000);
  const { data: alerts } = useApi<Alert[]>("/api/alerts?unseen=true", 60_000);
  const marketAlerts = (alerts ?? []).filter((a) => a.rule !== "announcement_category");

  const { open, done } = useMemo(() => {
    const cards = data?.cards ?? [];
    return { open: cards.filter((c) => !reviewed.includes(c.id)), done: cards.filter((c) => reviewed.includes(c.id)) };
  }, [data, reviewed]);
  const high = open.filter((c) => c.priority === "high");
  const medium = open.filter((c) => c.priority === "medium");

  const toggle = (id: number) => setReviewed((r) => (r.includes(id) ? r.filter((x) => x !== id) : [...r, id]));

  return (
    <>
      <header className="topbar">
        <div className="caps">{now ? todayLong(now) : " "}</div>
        <h1>{now ? `${greeting(now)}.` : "Your briefing"}</h1>
        {data && (
          <p className="brief-line">
            {high.length + medium.length === 0 ? (
              <>Nothing needs you right now.</>
            ) : (
              <>
                {high.length > 0 && <><b>{plural(high.length, "thing")} need{high.length === 1 ? "s" : ""} you</b>{medium.length ? ", " : ". "}</>}
                {medium.length > 0 && <>{medium.length} {high.length ? "more" : "items"} worth a look. </>}
              </>
            )}
            {data.routine.count > 0 && <span className="muted">{plural(data.routine.count, "routine filing")} filed away.</span>}
          </p>
        )}
      </header>

      <div className="between" style={{ marginTop: 4 }}>
        <div className="seg" role="group" aria-label="Time window">
          {WINDOWS.map((w) => (
            <button key={w.key} aria-pressed={win === w.key} onClick={() => setWin(w.key)}>{w.label}</button>
          ))}
        </div>
        {data && <span className="tiny muted" style={{ whiteSpace: "nowrap" }}>{ago(data.generated_at)}</span>}
      </div>
      {win === "custom" && (
        <input type="datetime-local" className="input" style={{ marginTop: 10 }} value={since}
               max={now?.toISOString().slice(0, 16)} onChange={(e) => setSince(e.target.value)}
               aria-label="Show filings since" />
      )}

      {marketAlerts.length > 0 && (
        <Link href="/alerts" className="card row" style={{ padding: "11px 14px", marginTop: 14 }}>
          <span className="dot high" />
          <span className="grow small truncate">
            <b>{marketAlerts[0].message}</b>
            {marketAlerts.length > 1 && <span className="muted"> · +{marketAlerts.length - 1} more</span>}
          </span>
          <span className="muted">›</span>
        </Link>
      )}

      {error && <div className="error section">Couldn&apos;t load the briefing: {error}</div>}
      {loading && !data && (
        <div className="stack section">{[120, 90, 90].map((h, i) => <div key={i} className="skeleton" style={{ height: h }} />)}</div>
      )}

      {high.length > 0 && (
        <section className="section">
          <div className="section-head"><span className="caps">Needs you</span></div>
          <div className="stack">
            {high.map((c) => <EventCard key={c.id} card={c} reviewed={false} onReview={() => toggle(c.id)} onAsk={() => setAsking(c)} />)}
          </div>
        </section>
      )}

      {medium.length > 0 && (
        <section className="section">
          <div className="section-head"><span className="caps">Worth a look</span></div>
          <div className="stack">
            {medium.map((c) => <EventCard key={c.id} card={c} reviewed={false} onReview={() => toggle(c.id)} onAsk={() => setAsking(c)} />)}
          </div>
        </section>
      )}

      {data && data.routine.count > 0 && (
        <section className="section">
          <details className="card routine">
            <summary>
              <span><span className="dot low" style={{ display: "inline-block", marginRight: 8 }} />{data.routine.line}</span>
              <span className="muted">Show</span>
            </summary>
            <ul>
              {data.routine.companies.map((r) => (
                <li key={r.symbol} className="between small">
                  <span><span className="mono" style={{ fontWeight: 600 }}>{r.symbol}</span> <span className="muted">{r.labels.join(", ")}</span></span>
                  <span className="muted num">{r.count}</span>
                </li>
              ))}
            </ul>
          </details>
        </section>
      )}

      {done.length > 0 && (
        <section className="section">
          <div className="section-head"><span className="caps">Reviewed</span><button className="tiny link" onClick={() => setReviewed([])}>Reset</button></div>
          <div className="stack">
            {done.map((c) => <EventCard key={c.id} card={c} reviewed onReview={() => toggle(c.id)} onAsk={() => setAsking(c)} />)}
          </div>
        </section>
      )}

      {data && data.cards.length === 0 && data.routine.count === 0 && (
        <div className="empty section">No filings from your portfolio in this window.<br />Try a longer window.</div>
      )}

      {asking && (
        <AskSheet symbol={asking.company.symbol} name={asking.company.name} announcementId={asking.id}
                  category={asking.category} onClose={() => setAsking(null)} />
      )}
    </>
  );
}
