"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { api, type Alert, type Card, type Digest } from "@/lib/api";
import { ago, dayIST, timeIST } from "@/lib/format";
import { useApi, useNow, useStored } from "@/lib/useApi";
import AskSheet from "./AskSheet";
import EventCard from "./EventCard";
import Masthead from "./Masthead";
import FollowUpSheet from "./FollowUpSheet";
import { Failure, Loading } from "./Status";
import { digestPath, useFollowUps } from "@/lib/followups";

const WINDOWS = [
  { key: "24", label: "24h", hours: 24 },
  { key: "72", label: "3d", hours: 72 },
  { key: "168", label: "7d", hours: 168 },
  { key: "custom", label: "Since…", hours: 0 },
];

function editionTitle(now: Date | null): string {
  if (!now) return "Your brief.";
  const h = Number(now.toLocaleString("en-IN", { hour: "numeric", hour12: false, timeZone: "Asia/Kolkata" }));
  return h < 12 ? "The morning brief." : h < 17 ? "The afternoon brief." : "The evening brief.";
}

const two = (n: number) => String(n).padStart(2, "0");

export default function Today() {
  const [win, setWin] = useStored("finn.window", "24");
  const [since, setSince] = useStored("finn.since", "");
  const [reviewed, setReviewed] = useStored<number[]>("finn.reviewed", []);
  const [asking, setAsking] = useState<Card | null>(null);
  const [showRoutine, setShowRoutine] = useState(false);
  const [openRoutine, setOpenRoutine] = useState<string | null>(null);
  const [showCounts, setShowCounts] = useState(false);
  const [following, setFollowing] = useState<Card | null>(null);
  const [askQuestion, setAskQuestion] = useState<string | undefined>(undefined);
  const followups = useFollowUps();
  const now = useNow();

  const path = digestPath(win, since);
  const { data, error, loading, reload } = useApi<Digest>(path, 5 * 60_000);
  const { data: alerts } = useApi<Alert[]>("/api/alerts?unseen=true", 60_000);
  const marketAlerts = (alerts ?? []).filter((a) => a.rule !== "announcement_category");

  const { open, done } = useMemo(() => {
    const cards = data?.cards ?? [];
    return { open: cards.filter((c) => !reviewed.includes(c.id)), done: cards.filter((c) => reviewed.includes(c.id)) };
  }, [data, reviewed]);
  const high = open.filter((c) => c.priority === "high");
  const medium = open.filter((c) => c.priority === "medium");

  const toggle = (id: number) => {
    const marking = !reviewed.includes(id);
    setReviewed((r) => (r.includes(id) ? r.filter((x) => x !== id) : [...r, id]));
    if (marking) {
      api(`/api/announcements/${id}/reviewed`, { method: "POST" })
        .then(() => window.dispatchEvent(new Event("finn-alerts")))
        .catch(() => {});
    }
  };

  return (
    <>
      <Masthead />
      <header className="topbar">
        <h1 className="display">{editionTitle(now)}</h1>
        {data?.as_of && (
          <p className="sub">
            Filings updated {data.as_of.announcements ? ago(data.as_of.announcements) : "–"} · Prices at close
          </p>
        )}
        {data && (
          <div className="stats" role="group" aria-label="Briefing summary">
            <div className={`stat ${high.length ? "hot" : ""}`}>
              <div className="n num">{two(high.length)}</div><div className="l">need you</div>
            </div>
            <div className="stat"><div className="n num">{two(medium.length)}</div><div className="l">worth a look</div></div>
            <div className="stat"><div className="n num">{two(data.routine.count)}</div><div className="l">filed away</div></div>
          </div>
        )}
        {data && high.length + medium.length > 0 && (
          <Link href="/review" className="cta">
            <span><span className="t" style={{ display: "block" }}>Start my review</span>
              <span className="s">
                {high.length
                  ? `${high.length} that need${high.length === 1 ? "s" : ""} you, one at a time${medium.length ? ` · then ${medium.length} worth a look` : ""}`
                  : `${medium.length} worth a look, one at a time`}
              </span></span>
            <span aria-hidden style={{ fontSize: 24 }}>→</span>
          </Link>
        )}
        {data && data.cards.length > 0 && high.length + medium.length === 0 && (
          <p className="small" style={{ marginTop: 16 }}><b>You&apos;re caught up.</b> <span className="muted">Everything that needed you here is reviewed.</span></p>
        )}
      </header>

      <div style={{ marginTop: 18 }}>
        <div className="seg" role="group" aria-label="Time window">
          {WINDOWS.map((w) => (
            <button key={w.key} aria-pressed={win === w.key} onClick={() => setWin(w.key)}>{w.label}</button>
          ))}
        </div>
        {win === "custom" && (
          <input type="datetime-local" className="input" style={{ marginTop: 10 }} value={since}
                 max={now?.toISOString().slice(0, 16)} onChange={(e) => setSince(e.target.value)} aria-label="Show filings since" />
        )}
        {data && (
          <p className="brief-note num">
            {data.window.widened_from_hours && data.window.latest_day ? (
              <>Quiet stretch: nothing that needs you in the last {data.window.widened_from_hours >= 48
                ? `${Math.round(data.window.widened_from_hours / 24)} days` : `${data.window.widened_from_hours}h`}.
                Showing everything since {dayIST(data.window.latest_day + "T12:00:00+05:30")}, the latest material filing.</>
            ) : (
              <>{dayIST(data.window.start)}, {timeIST(data.window.start)} → now · {data.counts.filings} filing{data.counts.filings === 1 ? "" : "s"} in {data.counts.events} event{data.counts.events === 1 ? "" : "s"}
                {data.span?.oldest && dayIST(data.span.oldest) !== dayIST(data.window.start) && ` · oldest ${dayIST(data.span.oldest)}`}
                {data.counts.filings === 0 && " · nothing filed in this range"}</>
            )}
            {" · "}
            <button className="link tiny" aria-expanded={showCounts} onClick={() => setShowCounts((v) => !v)}>
              {showCounts ? "Hide" : "How counts work"}
            </button>
          </p>
        )}
        {showCounts && data && (
          <div className="note small ink2" style={{ display: "block", marginTop: 10 }}>
            <p><b>Need you / worth a look</b> count <i>events</i>: filings about the same company and topic are one event
              (a results filing, its press release and its slides = 1). {data.counts.filings} filings, {data.counts.events} events here.</p>
            <p style={{ marginTop: 6 }}><b>Filed away</b> counts routine filings one by one.</p>
            <p style={{ marginTop: 6 }}><b>Alerts</b> ({alerts?.length ?? 0} unread) cover every day, not just this window, and include
              end-of-day price and volume moves. <b>Mark reviewed</b> on a story also marks its alert read.</p>
          </div>
        )}
      </div>

      {marketAlerts.length > 0 && (
        <Link href="/alerts" className="between" style={{ marginTop: 16, padding: "12px 0", borderTop: "1px solid var(--line)" }}>
          <span className="grow small truncate">
            <span className="dot high" style={{ marginRight: 8 }} aria-hidden />
            <b>{marketAlerts[0].symbol}</b> {marketAlerts[0].title}
            {marketAlerts.length > 1 && <span className="muted"> · +{marketAlerts.length - 1} more alerts</span>}
          </span>
          <span className="muted" aria-hidden>›</span>
        </Link>
      )}

      {error && !data && <Failure message={error} onRetry={reload} />}
      {loading && !data && <Loading label="Loading your briefing…" heights={[160, 110, 110]} onRetry={reload} />}

      {data && (high.length > 0 || medium.length > 0 || data.routine.count > 0) && (
        <div className="feed">
          {[...high, ...medium].map((c, i) => (
            <EventCard key={c.id} card={c} index={i + 1} reviewed={false} onReview={() => toggle(c.id)}
                       onAsk={() => { setAskQuestion(undefined); setAsking(c); }} onFollowUp={() => setFollowing(c)}
                       followed={followups.open.some((f) => f.announcementId === c.id)} />
          ))}
          {data.routine.count > 0 && (
            <div className="routine">
              <div className="between">
                <span className="small ink2"><span className="dot low" style={{ marginRight: 8 }} aria-hidden />{data.routine.line}</span>
                <button className="btn secondary small" style={{ whiteSpace: "nowrap", flex: "none" }}
                        aria-expanded={showRoutine} aria-controls="routine-list"
                        onClick={() => setShowRoutine((v) => !v)}>
                  {showRoutine ? "Hide routine filings" : "Show routine filings"}
                </button>
              </div>
              {showRoutine && (
                <ul id="routine-list">
                  {data.routine.companies.map((r) => {
                    const isOpen = openRoutine === r.symbol;
                    return (
                      <li key={r.symbol} className="routine-co">
                        <button className="routine-row" aria-expanded={isOpen} aria-controls={`rt-${r.symbol}`}
                                onClick={() => setOpenRoutine(isOpen ? null : r.symbol)}>
                          <span className="small"><span className="ticker">{r.symbol}</span> <span className="muted">{r.labels.join(", ")}</span></span>
                          <span className="row small muted num" style={{ gap: 10 }}>{r.count}
                            <span aria-hidden className={`chev ${isOpen ? "open" : ""}`}>⌄</span></span>
                        </button>
                        {isOpen && (
                          <div id={`rt-${r.symbol}`} className="routine-items">
                            {r.items.map((it) => (
                              <div key={it.id} className="routine-item">
                                <div className="between tiny muted">
                                  <span className="caps" style={{ fontSize: 10.5 }}>{it.label}</span>
                                  <time dateTime={it.published_at}>{dayIST(it.published_at)}, {timeIST(it.published_at)}</time>
                                </div>
                                <p className="small" style={{ marginTop: 3 }}>{it.summary}</p>
                                {it.reasons.length > 1 && (
                                  <p className="tiny muted" style={{ marginTop: 3 }}>Filed away because: {it.reasons.slice(1).join(" · ")}</p>
                                )}
                                {it.url && (
                                  <a className="link tiny" href={it.url} target="_blank" rel="noreferrer" style={{ display: "inline-block", marginTop: 6 }}>
                                    {it.url.toLowerCase().endsWith(".pdf") ? "Open filing PDF ↗" : "Open filing data ↗"}
                                  </a>
                                )}
                              </div>
                            ))}
                            <Link href={`/stock/${encodeURIComponent(r.symbol)}`} className="link tiny">{r.name}: chart and research →</Link>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {followups.open.length > 0 && (
        <Link href="/followups" className="between" style={{ marginTop: 18, padding: "14px 0", borderTop: "1.5px solid var(--rule)", borderBottom: "1px solid var(--line)" }}>
          <span>
            <span className="caps" style={{ color: "var(--ink)", display: "block" }}>Still on your mind</span>
            <span className="headline-sm">{followups.open[0].note}</span>
            {followups.open.length > 1 && <span className="small muted"> · +{followups.open.length - 1} more</span>}
          </span>
          <span className="row small" style={{ color: "var(--accent)", fontWeight: 600, flex: "none" }}>
            <span className="num" style={{ color: "var(--high)" }}>{two(followups.open.length)}</span> open →
          </span>
        </Link>
      )}

      {done.length > 0 && (
        <section className="section">
          <div className="section-head">
            <span className="caps">Reviewed</span>
            <button className="tiny link" onClick={() => setReviewed([])}>Reset</button>
          </div>
          <div className="feed" style={{ marginTop: 0 }}>
            {done.map((c, i) => (
              <EventCard key={c.id} card={c} index={i + 1} reviewed onReview={() => toggle(c.id)}
                         onAsk={() => { setAskQuestion(undefined); setAsking(c); }} onFollowUp={() => setFollowing(c)}
                         followed={followups.open.some((f) => f.announcementId === c.id)} />
            ))}
          </div>
        </section>
      )}

      {data && data.cards.length === 0 && data.routine.count === 0 && (
        <div className="empty section">No filings from your companies in this window.<br />Try a longer window.</div>
      )}

      {following && (
        <FollowUpSheet card={following} onSave={(note) => followups.add(following, note)} onClose={() => setFollowing(null)} />
      )}
      {asking && (
        <AskSheet symbol={asking.company.symbol} name={asking.company.name} announcementId={asking.id}
                  category={asking.category} initialQuestion={askQuestion} onClose={() => setAsking(null)} />
      )}
    </>
  );
}
