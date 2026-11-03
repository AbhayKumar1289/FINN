"use client";

import Link from "next/link";
import { useState } from "react";
import AskSheet from "@/components/AskSheet";
import FollowUpSheet from "@/components/FollowUpSheet";
import { Failure, Loading } from "@/components/Status";
import { api, type Card, type Digest } from "@/lib/api";
import { contextFor, digestPath, useFollowUps } from "@/lib/followups";
import { change, crore, pct, tone } from "@/lib/format";
import { useApi, useStored } from "@/lib/useApi";

const ASK: Record<string, string> = {
  results: "How much of this is likely to recur?",
  management_change: "What has management said about leadership and succession?",
  press_release: "How does this fit management's growth plans?",
};

/** Focused review: the briefing's priority items one at a time, then "you're caught up".
 * Shares the same window, reviewed-list and follow-ups as Today. */
export default function ReviewPage() {
  const [win] = useStored("finn.window", "24");
  const [since] = useStored("finn.since", "");
  const { data, error, reload } = useApi<Digest>(digestPath(win, since));
  const [reviewed, setReviewed] = useStored<number[]>("finn.reviewed", []);
  const followups = useFollowUps();
  const [queue, setQueue] = useState<number[] | null>(null);
  // urgent first: "need you" items; "worth a look" is offered afterwards, not mixed in
  const [scope, setScope] = useState<"high" | "medium" | null>(null);
  const [idx, setIdx] = useState(0);
  const [asking, setAsking] = useState<string | null>(null);
  const [following, setFollowing] = useState(false);

  // freeze the queue when the briefing arrives, so marking items reviewed doesn't reshuffle it
  const pending = (p: string) => (data?.cards ?? []).filter((c) => c.priority === p && !reviewed.includes(c.id));
  if (data && queue === null) {
    const s = scope ?? (pending("high").length ? "high" : "medium");
    setScope(s);
    setQueue(pending(s).map((c) => c.id));
  }
  function reviewMore() {
    setScope("medium");
    setQueue(null);
    setIdx(0);
    window.scrollTo({ top: 0 });
  }

  if (error && !data) return <Failure message={error} onRetry={reload} />;
  if (!data || queue === null) return <Loading label="Preparing your review…" heights={[60, 220, 120]} onRetry={reload} />;

  const cards = queue.map((id) => data.cards.find((c) => c.id === id)).filter((c): c is Card => !!c);
  if (idx >= cards.length) {
    const more = scope === "high" ? pending("medium").length : 0;
    return <CaughtUp reviewedNow={cards.length} routine={data.routine.count} open={followups.open}
                     scope={scope ?? "high"} more={more} onMore={reviewMore} />;
  }
  const card = cards[idx];

  function next() {
    if (!reviewed.includes(card.id)) {
      setReviewed((r) => [...r, card.id]);
      api(`/api/announcements/${card.id}/reviewed`, { method: "POST" })
        .then(() => window.dispatchEvent(new Event("finn-alerts"))).catch(() => {});
    }
    setIdx((i) => i + 1);
    window.scrollTo({ top: 0 });
  }

  const r = card.results;
  const savedHere = followups.open.some((f) => f.announcementId === card.id);

  return (
    <>
      <div className="between" style={{ paddingTop: 18 }}>
        <Link href="/" className="row small" style={{ fontWeight: 600 }}>
          <span aria-hidden>←</span> {scope === "medium" ? "Worth a look" : "Needs you"}
        </Link>
        <span className="small muted num" aria-live="polite">{idx + 1} of {cards.length}</span>
      </div>
      <div className="progress" role="progressbar" aria-valuemin={1} aria-valuemax={cards.length} aria-valuenow={idx + 1}
           aria-label="Review progress">
        {cards.map((c, i) => <span key={c.id} className={i <= idx ? "on" : ""} />)}
      </div>

      <article style={{ marginTop: 22 }} aria-labelledby="rv-h">
        <div className="caps" style={{ color: "var(--ink-2)" }}>{card.company.symbol} / {contextFor(card)}</div>
        <h1 id="rv-h" className="display" style={{ fontSize: 40, marginTop: 8 }}>{card.story?.headline ?? card.headline ?? card.label}</h1>
        <p className="dek">{r ? card.story?.callout_title : card.people?.line ?? card.summary}</p>

        {r && (
          <section className="section">
            <div className="caps" style={{ color: "var(--ink)" }}>The quarter at a glance</div>
            <table className="glance-table num">
              <thead><tr><th>Metric</th><th>₹ crore</th><th>YoY</th><th>QoQ</th></tr></thead>
              <tbody>
                {([["Revenue", "revenue"], ["EBITDA", "ebitda"], ["PBT", "pbt"], ["PAT", "pat"]] as const).map(([label, k]) => {
                  const m = r.metrics[k];
                  return (
                    <tr key={k}>
                      <td>{label}</td>
                      <td>{m.current_cr == null ? "n/a" : crore(m.current_cr).replace("₹", "").replace(" cr", "")}</td>
                      <td className={tone(m.yoy.value)}>{change(m.yoy)}</td>
                      <td className="muted">{change(m.qoq)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        )}

        {card.why_it_matters && (
          <div className="explain">
            <div className="t">{r ? "What explains it?" : "Why it matters"}</div>
            <p>{card.why_it_matters}</p>
          </div>
        )}
        {card.brief?.key_points.length ? (
          <ul className="small ink2" style={{ margin: "14px 0 0 18px" }}>
            {card.brief.key_points.map((p) => <li key={p} style={{ marginTop: 3 }}>{p}</li>)}
          </ul>
        ) : null}
        {card.people?.changes.filter((c) => c.direction !== "exit" && c.background?.bio).map((c) => (
          <div className="person" key={c.name}>
            <div className="name">{c.name}</div>
            <p className="small ink2" style={{ marginTop: 4 }}>{c.background!.bio}</p>
            <span className={`source-tag ${c.background!.verified ? "ok" : ""}`} style={{ display: "inline-block", marginTop: 8 }}>
              {c.background!.source === "filing" ? "From the filing" : "Unverified"}
            </span>
          </div>
        ))}

        {(card.document_url || card.source_url) && (
          <p style={{ marginTop: 12 }}>
            <a className="link small" href={r?.page ? `${card.document_url}#page=${r.page}` : card.document_url ?? card.source_url!}
               target="_blank" rel="noreferrer">Open the filing{r?.page ? ` · p.${r.page}` : ""} ↗</a>
          </p>
        )}

        {card.reaction?.status === "ok" && (
          <p className="small between" style={{ marginTop: 16, padding: "12px 0", borderTop: "1px solid var(--line)", borderBottom: "1px solid var(--line)" }}>
            <span className="caps">At the close</span>
            <span className="num"><b className={tone(card.reaction.change_pct)}>{pct(card.reaction.change_pct)}</b> price
              {card.reaction.relative_volume != null && <> · {card.reaction.relative_volume}× volume</>}</span>
          </p>
        )}

        <div className="section">
          <div className="caps">Ask FINN</div>
          <button className="ask-prompt" onClick={() => setAsking(ASK[card.category] ?? "What is management's outlook here?")}>
            <span>{ASK[card.category] ?? "What is management's outlook here?"}</span><span aria-hidden>↗</span>
          </button>
        </div>
      </article>

      <div className="review-actions">
        <button className="btn secondary" onClick={() => setFollowing(true)} disabled={savedHere}
                aria-label={savedHere ? "Follow-up saved" : "Keep a question open"}>
          {savedHere ? "Saved ✓" : "Follow up"}
        </button>
        <button className="btn grow" onClick={next}>
          {idx + 1 === cards.length ? "Reviewed · Finish" : "Reviewed · Next"} <span aria-hidden>→</span>
        </button>
      </div>
      <p style={{ textAlign: "center" }}><Link href="/" className="plain-link">Back to brief</Link></p>

      {following && <FollowUpSheet card={card} onSave={(note) => followups.add(card, note)} onClose={() => setFollowing(false)} />}
      {asking && (
        <AskSheet symbol={card.company.symbol} name={card.company.name} announcementId={card.id}
                  category={card.category} initialQuestion={asking} onClose={() => setAsking(null)} />
      )}
    </>
  );
}

function CaughtUp({ reviewedNow, routine, open, scope, more, onMore }: {
  reviewedNow: number;
  routine: number;
  open: ReturnType<typeof useFollowUps>["open"];
  scope: "high" | "medium";
  more: number;
  onMore: () => void;
}) {
  const two = (n: number) => String(n).padStart(2, "0");
  return (
    <>
      <div className="progress done" style={{ marginTop: 22 }} aria-hidden><span className="on" /></div>
      <div className="check" aria-hidden>✓</div>
      <h1 className="display" style={{ marginTop: 12 }}>{more ? "The urgent part is done." : "You’re caught up."}</h1>
      <p className="dek">
        {more ? `Everything that needed you is reviewed. ${more} more ${more === 1 ? "is" : "are"} worth a look when you have time.`
          : reviewedNow ? (scope === "high" ? "Everything that needed you in this window is reviewed." : "Every item worth a look is reviewed.")
          : "Nothing new needs you in this window."}
      </p>
      {more > 0 && (
        <button className="cta" style={{ width: "100%", textAlign: "left" }} onClick={onMore}>
          <span><span className="t" style={{ display: "block" }}>Review {more} more</span>
            <span className="s">worth a look, one at a time</span></span>
          <span aria-hidden style={{ fontSize: 24 }}>→</span>
        </button>
      )}
      <div className="stats">
        <div className="stat"><div className="n num">{two(reviewedNow)}</div><div className="l">reviewed</div></div>
        <div className="stat"><div className="n num">{two(open.length)}</div><div className="l">follow-ups</div></div>
        <div className="stat"><div className="n num">{two(routine)}</div><div className="l">routine</div></div>
      </div>
      {open.length > 0 && (
        <section className="section">
          <div className="section-head"><span className="caps" style={{ color: "var(--ink)" }}>Still on your mind</span>
            <span className="caps num" style={{ color: "var(--high)" }}>{two(open.length)}</span></div>
          <div style={{ borderTop: "1px solid var(--line)" }}>
            {open.map((f) => (
              <Link key={f.id} href="/followups" className="between" style={{ padding: "12px 0", borderBottom: "1px solid var(--line)" }}>
                <span><span className="caps" style={{ display: "block" }}>{f.symbol}</span>
                  <span className="headline-sm">{f.note}</span></span>
                <span aria-hidden>→</span>
              </Link>
            ))}
          </div>
        </section>
      )}
      <Link href="/" className={`btn block ${more ? "secondary" : ""}`} style={{ marginTop: more ? 12 : 22 }}>Back to brief</Link>
    </>
  );
}
