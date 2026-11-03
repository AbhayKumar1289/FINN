"use client";

import type { GuidanceRow } from "@/lib/api";

const METRIC: Record<string, string> = {
  revenue_growth: "Revenue growth", ebitda_margin: "Margin", pat_growth: "Profit growth",
};
const VERDICT: Record<string, string> = {
  met: "Met", exceeded: "Beat", missed: "Missed", on_track: "On track", behind: "Behind",
};
const DONE = new Set(["met", "exceeded", "missed"]);

const fmtPeriod = (p: string | null | undefined) => (p ?? "").replace(/FY(\d\d)/, " FY$1").trim();

/**
 * Promised vs delivered, one row per promise: the guided band, where the reported number
 * landed, and the transcript line it came from. Statuses come from code, not the model.
 */
export default function PromiseScorecard({ rows }: { rows: GuidanceRow[] }) {
  const scored = rows
    .filter((r) => r.same_as == null && r.actual != null && r.target_low != null && VERDICT[r.status])
    // fully reported periods first: those are verdicts, the rest are progress
    .sort((a, b) => Number(DONE.has(b.status)) - Number(DONE.has(a.status)) || (b.target_period ?? "").localeCompare(a.target_period ?? ""));
  if (!scored.length) return null;

  return (
    <section className="section" aria-labelledby="scorecard-h">
      <div className="section-head">
        <span id="scorecard-h" className="caps" style={{ color: "var(--ink)" }}>Promise check</span>
        <span className="tiny muted">{scored.length} promise{scored.length === 1 ? "" : "s"} measured</span>
      </div>
      <div className="stack" style={{ gap: 12 }}>
        {scored.map((r) => <Row key={r.id} r={r} />)}
      </div>
      <p className="tiny muted" style={{ marginTop: 8 }}>
        Shaded band: what management guided. Marker: what was reported. &ldquo;So far&rdquo; means the year
        isn&apos;t over, so it can only be on track or behind, never met.
      </p>
    </section>
  );
}

function Row({ r }: { r: GuidanceRow }) {
  const low = r.target_low!, actual = r.actual!;
  const open = r.target?.startsWith("≥");
  const high = open ? null : (r.target_high ?? low);
  const lo = Math.min(0, actual, low);
  const hi = Math.max(actual, high ?? low * 1.4) * 1.18 || 1;
  const x = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  const done = DONE.has(r.status);
  const metric = METRIC[r.metric] ?? r.metric;
  const said = [r.stated_in, ...(r.reiterated_in ?? [])].filter(Boolean).map(fmtPeriod);
  const gap = high != null && actual > high ? actual - high : actual < low ? actual - low : 0;
  const tone = r.status === "missed" || r.status === "behind" ? "down" : "up";

  return (
    <article className={`scorecard ${r.status}`}>
      <div className="between" style={{ alignItems: "baseline" }}>
        <span className="eyebrow" style={{ color: "var(--ink)" }}>{metric} · {fmtPeriod(r.target_period)}</span>
        <span className={`status ${r.status}`}>{VERDICT[r.status]}</span>
      </div>
      <div className="score-nums num">
        <div><span className="k">Guided</span><span className="v">{r.target}</span></div>
        <span className="arrow" aria-hidden>→</span>
        <div><span className="k">{done ? "Delivered" : "So far"}</span><span className={`v ${tone}`}>{actual.toFixed(1)}%</span></div>
        {gap !== 0 && (
          <div><span className="k">{gap > 0 ? "Above" : "Short by"}</span><span className={`v ${tone}`}>{Math.abs(gap).toFixed(1)} pp</span></div>
        )}
      </div>

      <div className="score-bar" role="img"
           aria-label={`Guided ${r.target}, ${done ? "delivered" : "so far"} ${actual.toFixed(1)}%`}>
        <span className="band" style={{ left: x(low), width: high == null ? `calc(100% - ${x(low)})` : `max(3px, calc(${x(high)} - ${x(low)}))` }} />
        {lo < 0 && <span className="zero" style={{ left: x(0) }} />}
        <span className={`mark ${tone}`} style={{ left: x(actual) }} />
      </div>

      <p className="tiny muted" style={{ marginTop: 8 }}>
        {done ? `Reported for ${r.measured_over}` : `Reported so far: ${r.measured_over?.replace("FY", " FY")}`}
        {r.measured_as && ` · ${r.measured_as}`}
      </p>
      <blockquote className="small ink2 score-quote">&ldquo;{r.quote}&rdquo;</blockquote>
      <p className="tiny muted" style={{ marginTop: 4 }}>
        Said on the {said[0]} call{said.length > 1 && `, reiterated ${said.slice(1).join(", ")}`} ·{" "}
        <a className="link" href={r.source.url} target="_blank" rel="noreferrer">{r.source.page ?? "transcript"} ↗</a>
      </p>
    </article>
  );
}
