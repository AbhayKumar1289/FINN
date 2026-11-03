"use client";

import { useState } from "react";
import AskSheet from "@/components/AskSheet";
import Masthead from "@/components/Masthead";
import { type FollowUp, useFollowUps } from "@/lib/followups";
import { ago } from "@/lib/format";

const Bookmark = ({ filled }: { filled: boolean }) => (
  <svg width="14" height="16" viewBox="0 0 14 18" aria-hidden style={{ flex: "none" }}>
    <path d="M1 1h12v16l-6-4-6 4z" fill={filled ? "var(--high)" : "none"} stroke="var(--high)" strokeWidth="1.6" strokeLinejoin="round" />
  </svg>
);

/** Open questions: what the investor wants to come back to, each linked to the filing that raised it. */
export default function FollowUpsPage() {
  const { open, resolved, resolve, remove } = useFollowUps();
  const [tab, setTab] = useState<"open" | "resolved">("open");
  const [asking, setAsking] = useState<FollowUp | null>(null);
  const list = tab === "open" ? open : resolved;

  return (
    <>
      <Masthead />
      <header className="topbar">
        <h1 className="display">Open questions.</h1>
        <p className="dek">The things you want to come back to.</p>
      </header>

      <div className="tabs" role="tablist" aria-label="Follow-ups" style={{ marginTop: 14 }}>
        <button role="tab" aria-selected={tab === "open"} onClick={() => setTab("open")}>
          Open {open.length > 0 && <span className="num">{open.length}</span>}
        </button>
        <button role="tab" aria-selected={tab === "resolved"} onClick={() => setTab("resolved")}>
          Resolved {resolved.length > 0 && <span className="num">{resolved.length}</span>}
        </button>
      </div>

      {list.length === 0 && (
        <div className="empty">
          {tab === "open"
            ? <>No open questions.<br />Tap <b>Follow up</b> on any story, or during your review, to keep a question open.</>
            : "Nothing resolved yet."}
        </div>
      )}

      <div role="tabpanel">
        {list.map((f) => (
          <article key={f.id} className="followup" aria-label={`${f.symbol}: ${f.note}`}>
            <div className="between">
              <span className="row caps" style={{ gap: 10 }}><Bookmark filled={!f.resolvedAt} />{f.symbol} / {f.context}</span>
              <span className="tiny muted">{f.resolvedAt ? `resolved ${ago(f.resolvedAt)}` : `saved ${ago(f.createdAt)}`}</span>
            </div>
            <h2 className="q" style={{ fontWeight: 500 }}>{f.note}</h2>
            <p className="small muted" style={{ marginTop: 4 }}>
              {f.name}
              {f.sourceUrl && <> · <a className="link" href={f.sourceUrl} target="_blank" rel="noreferrer">View source ↗</a></>}
            </p>
            <div className="acts">
              <button className="link" onClick={() => setAsking(f)}>Ask FINN ↗</button>
              {f.resolvedAt ? (
                <span className="row" style={{ gap: 18 }}>
                  <button className="link" onClick={() => resolve(f.id, false)}>Reopen</button>
                  <button className="link" style={{ color: "var(--down)" }} onClick={() => remove(f.id)}>Delete</button>
                </span>
              ) : (
                <button className="link" onClick={() => resolve(f.id)}>Mark resolved ✓</button>
              )}
            </div>
          </article>
        ))}
      </div>

      <div className="note">
        <span aria-hidden style={{ fontSize: 18 }}>ⓘ</span>
        <div>
          <div className="t">Your notes stay linked to the original filing.</div>
          <p className="small ink2" style={{ marginTop: 2 }}>Saved on this device. Follow-ups are questions you keep, not automatic alerts.</p>
        </div>
      </div>

      {asking && (
        <AskSheet symbol={asking.symbol} name={asking.name} announcementId={asking.announcementId}
                  initialQuestion={asking.note} onClose={() => setAsking(null)} />
      )}
    </>
  );
}
