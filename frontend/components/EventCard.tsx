"use client";

import { useState } from "react";
import type { Card, Results } from "@/lib/api";
import { ago, change, crore, pct, timeIST, tone } from "@/lib/format";

/** Three layers: what happened (always visible) -> why it matters + evidence (tap) -> Ask (button). */
export default function EventCard({ card, reviewed, onReview, onAsk }: {
  card: Card;
  reviewed: boolean;
  onReview: () => void;
  onAsk: () => void;
}) {
  const [open, setOpen] = useState(card.priority === "high" && !reviewed);
  const what = card.people?.line ?? (card.results ? null : card.summary);

  return (
    <article className={`card event ${card.priority} ${reviewed ? "reviewed" : ""}`}
             onClick={() => setOpen((o) => !o)}>
      <div className="who">
        <span className={`dot ${card.priority}`} aria-label={`${card.priority} priority`} />
        <span className="mono">{card.company.symbol}</span>
        <span className="truncate grow">{card.company.name}</span>
        <span className="tiny" title={new Date(card.published_at).toString()}>{ago(card.published_at)}</span>
      </div>
      <h3>{card.headline ?? card.label}</h3>
      {card.results ? <Kpis r={card.results} /> : what && <p className="what">{what}</p>}

      {open && (
        <div onClick={(e) => e.stopPropagation()}>
          {card.why_it_matters && (
            <div className="why"><span className="caps">Why it matters</span>{card.why_it_matters}</div>
          )}
          {card.people && <People people={card.people} />}
          <div className="reasons">
            <span className="chip">{card.label}</span>
            <Reaction card={card} />
            {card.related.length > 0 && <span className="chip">+{card.related.length} related filing{card.related.length > 1 ? "s" : ""}</span>}
          </div>
          {card.related.length > 0 && (
            <ul className="stack small ink2" style={{ listStyle: "none", marginTop: 10 }}>
              {card.related.map((r) => (
                <li key={r.id} className="between">
                  <span className="truncate">{r.label} · {timeIST(r.published_at)}</span>
                  {r.url && <a className="link" href={r.url} target="_blank" rel="noreferrer">PDF</a>}
                </li>
              ))}
            </ul>
          )}
          {card.results && (
            <p className="tiny muted" style={{ marginTop: 10 }}>
              {card.results.period} · {card.results.basis} · ₹ crore · read from p.{card.results.page} of the filing
              {card.results.verified_in_text != null && card.results.verified_in_text >= 0.5
                ? ` · ${Math.round(card.results.verified_in_text * 100)}% of figures matched the PDF text`
                : " · scanned filing, figures read from the page image"}
              {card.results.ebitda_definition && ` · EBITDA = ${card.results.ebitda_definition}`}
            </p>
          )}
          <div className="actions">
            <button className="btn accent small" onClick={onAsk}>Ask FINN about this</button>
            {(card.document_url || card.source_url) && (
              <a className="btn secondary small" href={card.document_url ?? card.source_url!} target="_blank" rel="noreferrer">Filing</a>
            )}
            <button className="btn secondary small" onClick={onReview}>{reviewed ? "Undo" : "Done"}</button>
          </div>
        </div>
      )}
    </article>
  );
}

function Kpis({ r }: { r: Results }) {
  const cells: [string, keyof Results["metrics"]][] = [["Revenue", "revenue"], ["EBITDA", "ebitda"], ["PBT", "pbt"], ["PAT", "pat"]];
  return (
    <>
      <div className="kpis num">
        {cells.map(([label, key]) => {
          const m = r.metrics[key];
          return (
            <div className="kpi" key={key}>
              <div className="caps">{label}</div>
              <div className="v">{m.current_cr == null ? "n/a" : crore(m.current_cr).replace(" cr", "")}</div>
              <div className={`d ${tone(m.yoy.value)}`}>{change(m.yoy)} <span className="muted">YoY</span></div>
              <div className={`d ${tone(m.qoq.value)}`}>{change(m.qoq)} <span className="muted">QoQ</span></div>
            </div>
          );
        })}
      </div>
      {r.margins.ebitda.current_pct != null && (
        <p className="small ink2 num" style={{ marginTop: 8 }}>
          EBITDA margin <b>{r.margins.ebitda.current_pct}%</b>
          {r.margins.ebitda.year_ago_pct != null && <> vs {r.margins.ebitda.year_ago_pct}% a year ago
            <span className={tone(r.margins.ebitda.change_pp)}> ({r.margins.ebitda.change_pp! > 0 ? "+" : ""}{r.margins.ebitda.change_pp}pp)</span></>}
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
              <p className="row" style={{ marginTop: 8 }}>
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
