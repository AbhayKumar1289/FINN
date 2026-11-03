"use client";

import Link from "next/link";
import { useState } from "react";
import type { Card, Results } from "@/lib/api";
import { ago, change, crore, pct, tone } from "@/lib/format";

const SECTION = { high: "Needs you", medium: "Worth a look", low: "Routine" } as const;

/** One story in the briefing. Three layers: what happened (always visible) → why it matters
 * and the evidence (tap the headline) → Ask FINN (a research thread scoped to this event). */
export default function EventCard({ card, index, reviewed, onReview, onAsk, onFollowUp, followed }: {
  card: Card;
  index: number;
  reviewed: boolean;
  onReview: () => void;
  onAsk: () => void;
  onFollowUp: () => void;
  followed: boolean;
}) {
  // every story starts closed: the headline is the first layer; tap for the evidence
  const [open, setOpen] = useState(false);
  const r = card.results;
  const headline = card.story?.headline ?? card.headline ?? card.label;
  const standfirst = r
    ? `${r.period.replace("FY", " FY")} results · ${card.company.name}`
    : card.people?.line ?? card.summary;

  return (
    <article className={`event ${card.priority} ${open ? "" : "collapsed"} ${reviewed ? "reviewed" : ""}`}
             aria-labelledby={`h-${card.id}`} onClick={() => { if (!open) setOpen(true); }}>
      <div className="meta">
        <span className={`eyebrow ${card.priority}`}>
          <span className={`dot ${card.priority}`} aria-hidden />
          {String(index).padStart(2, "0")} / {SECTION[card.priority]}
        </span>
        <time className="tiny muted" dateTime={card.published_at} title={new Date(card.published_at).toString()}>
          {ago(card.published_at)}
        </time>
      </div>
      <div className="company ticker">{card.company.symbol}</div>
      <h3 id={`h-${card.id}`}>
        <button className="event-toggle headline" aria-expanded={open}
                onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}>
          {headline}
        </button>
      </h3>
      {standfirst && <p className="standfirst">{standfirst}</p>}
      {r && !open && <Glance r={r} />}
      {!open && <span className="more" aria-hidden>Read more ⌄</span>}

      {open && (
        <div onClick={(e) => e.stopPropagation()}>
          {r && <Kpis r={r} />}
          {card.why_it_matters && (
            <div className={`callout ${card.priority === "high" ? "" : "calm"}`}>
              <div className="t">{card.story?.callout_title ?? "Why it matters"}</div>
              <p>{card.why_it_matters}</p>
            </div>
          )}
          {card.people && <People people={card.people} />}
          {card.brief && card.brief.key_points.length > 0 && (
            <ul className="small ink2" style={{ margin: "12px 0 0 18px" }}>
              {card.brief.key_points.map((p) => <li key={p} style={{ marginTop: 3 }}>{p}</li>)}
            </ul>
          )}
          {card.transcript && (
            <Link href={`/research/${encodeURIComponent(card.company.symbol)}`} className="person">
              <span className="small"><b>{card.transcript.guidance_count} guidance statement{card.transcript.guidance_count === 1 ? "" : "s"}</b>
                <span className="ink2"> from the {card.transcript.period} call, scored against reported numbers.</span></span>
              <span className="link small" style={{ display: "block", marginTop: 6 }}>Open research</span>
            </Link>
          )}
          <div className="reasons">
            <Size card={card} />
            <Reaction card={card} />
          </div>
          <div className="sources">
            {(card.document_url || card.source_url) && (
              <a className="link" href={card.document_url ?? card.source_url!} target="_blank" rel="noreferrer">
                {r ? "Results filing" : card.label} ↗
              </a>
            )}
            {r?.page && <a className="link" href={`${card.document_url}#page=${r.page}`} target="_blank" rel="noreferrer">p.{r.page}</a>}
            {card.related.map((x) => x.url && (
              <a key={x.id} className="link" href={x.url} target="_blank" rel="noreferrer">{x.label} ↗</a>
            ))}
          </div>
          {r && (
            <p className="tiny muted" style={{ marginTop: 8 }}>
              {r.basis} · ₹ crore ·{" "}
              {r.verified_in_text != null && r.verified_in_text >= 0.5
                ? `${Math.round(r.verified_in_text * 100)}% of figures matched the PDF text`
                : "scanned filing, read from the page image"}
            </p>
          )}
          <div className="actions">
            <button className="btn block" onClick={onAsk}>Ask FINN about this ↗</button>
            <div className="secondary-row">
              <button className="plain-link" onClick={onReview}>{reviewed ? "Move back to the briefing" : "Mark reviewed ✓"}</button>
              <button className="plain-link" onClick={onFollowUp} disabled={followed}>{followed ? "Follow-up saved" : "Follow up"}</button>
              <button className="plain-link" onClick={() => setOpen(false)} aria-label="Collapse this story">Show less ⌃</button>
            </div>
          </div>
        </div>
      )}
    </article>
  );
}

/** Closed-card glance: the two numbers that matter, year on year. */
function Glance({ r }: { r: Results }) {
  const items: [string, keyof Results["metrics"]][] = [["Revenue", "revenue"], ["PAT", "pat"]];
  return (
    <div className="glance num">
      {items.map(([label, key]) => (
        <span key={key}>{label} <span className={tone(r.metrics[key].yoy.value)}>{change(r.metrics[key].yoy)}</span>
          <span className="muted" style={{ fontWeight: 400 }}> YoY</span></span>
      ))}
    </div>
  );
}

function Kpis({ r }: { r: Results }) {
  const cells: [string, keyof Results["metrics"]][] = [["Revenue", "revenue"], ["EBITDA", "ebitda"], ["PBT", "pbt"], ["PAT", "pat"]];
  const mg = r.margins.ebitda;
  return (
    <>
      <div className="kpis num">
        {cells.map(([label, key]) => {
          const m = r.metrics[key];
          return (
            <div className="kpi" key={key}>
              <div className="k">{label}</div>
              <div className="v">{m.current_cr == null ? "n/a" : crore(m.current_cr)}</div>
              {m.current_cr != null && <>
                <div className={`d ${tone(m.yoy.value)}`}>{change(m.yoy)} YoY</div>
                <div className="q">{change(m.qoq)} QoQ</div>
              </>}
            </div>
          );
        })}
      </div>
      {mg.current_pct != null && (
        <p className="small ink2 num" style={{ marginTop: 8 }}>
          EBITDA margin <b>{mg.current_pct}%</b>
          {mg.year_ago_pct != null && <> vs {mg.year_ago_pct}% a year ago{" "}
            <span className={tone(mg.change_pp)}>({mg.change_pp! > 0 ? "+" : ""}{mg.change_pp}pp)</span></>}
        </p>
      )}
    </>
  );
}

function People({ people }: { people: NonNullable<Card["people"]> }) {
  return (
    <>
      {people.changes.filter((c) => c.direction !== "exit").map((c) => (
        <div className="person" key={c.name}>
          <div className="between">
            <span className="name">{c.name}</span>
            <span className="tiny muted">{c.role}{c.effective_date && ` · from ${c.effective_date}`}</span>
          </div>
          {c.background?.bio ? (
            <>
              <p className="small ink2" style={{ marginTop: 6 }}>{c.background.bio}</p>
              <p className="row" style={{ marginTop: 8, flexWrap: "wrap" }}>
                <span className={`source-tag ${c.background.verified ? "ok" : ""}`}>
                  {c.background.source === "filing" ? "From the filing" : c.background.source === "wikipedia" ? "Wikipedia" : "Unverified"}
                </span>
                {c.background.note && <span className="tiny muted">{c.background.note}</span>}
              </p>
            </>
          ) : (
            <p className="small muted" style={{ marginTop: 6 }}>{c.background?.note ?? "No background available."}</p>
          )}
        </div>
      ))}
      {people.changes.filter((c) => c.direction === "exit").map((c) => (
        <p key={c.name} className="small muted" style={{ marginTop: 8 }}>
          Outgoing: {c.name}, {c.role}{c.reason && ` (${c.reason})`}
        </p>
      ))}
    </>
  );
}

function Size({ card }: { card: Card }) {
  const b = card.brief;
  if (!b || (b.value_low_cr == null && b.value_high_cr == null && !b.value_note)) return null;
  const value = b.value_low_cr != null && b.value_high_cr != null && b.value_high_cr !== b.value_low_cr
    ? `${crore(b.value_low_cr)}–${crore(b.value_high_cr).replace("₹", "")}`
    : b.value_low_cr != null || b.value_high_cr != null ? crore(b.value_low_cr ?? b.value_high_cr) : b.value_note;
  const p = b.materiality?.pct_of_revenue;
  return (
    <span className="chip num">
      {value}
      {p != null && <span className="muted">· {p < 0.1 ? "<0.1" : p.toFixed(1)}% of annual revenue</span>}
    </span>
  );
}

function Reaction({ card }: { card: Card }) {
  const r = card.reaction;
  if (!r || r.status === "unavailable") return null;
  if (r.status === "pending") return <span className="chip">Market reacts next session</span>;
  return (
    <span className="chip num">
      Stock <span className={tone(r.change_pct)}>{pct(r.change_pct)}</span>
      {r.relative_volume != null && <> · {r.relative_volume}× vol</>}
    </span>
  );
}
