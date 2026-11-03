"use client";

import Link from "next/link";
import { use, useMemo, useState } from "react";
import { api, type Business, type Case, type GuidanceRow, type Research } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import AskSheet from "./AskSheet";
import Masthead from "./Masthead";
import MetricChart from "./MetricChart";
import PromiseScorecard from "./PromiseScorecard";
import { BalanceSection, BusinessSection, CaseSection, CashSection, SectionIndex, SnapshotSection,
  TrajectorySection } from "./ResearchSections";
import { Failure, Loading } from "./Status";

const VERDICT = {
  delivers: "Delivers on guidance",
  mixed: "Mixed record",
  over_promises: "Over-promises",
  too_early: "Too early to judge",
  tracking: "On track so far",
};
const STATUS_LABEL: Record<GuidanceRow["status"], string> = {
  met: "Met", exceeded: "Beat", missed: "Missed", on_track: "On track", behind: "Behind",
  pending: "Pending", not_comparable: "Not scored",
};
const METRIC_LABEL: Record<string, string> = {
  revenue_growth: "Revenue growth", ebitda_margin: "EBITDA margin", pat_growth: "Profit growth",
  order_inflow_growth: "Order inflow", order_book: "Order book", capex: "Capex", volume_growth: "Volume growth",
  other_margin: "Margin (other)", working_capital: "Working capital", other: "Other",
};
const SCORED = new Set(["met", "exceeded", "missed", "on_track", "behind"]);

export default function ResearchView({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol: raw } = use(params);
  const symbol = decodeURIComponent(raw).toUpperCase();
  const [preparing, setPreparing] = useState(false);
  const base = `/api/research/${encodeURIComponent(symbol)}`;
  const { data: first, error, reload } = useApi<Research>(base);
  // while documents are being read, poll; the newest response is the one we show
  const [polledPath, setPolledPath] = useState<string | null>(null);
  const { data: polled } = useApi<Research>(polledPath, 5000);
  const wantsPoll = (preparing || first?.status === "preparing") && polled?.status !== "ready";
  if (wantsPoll !== (polledPath !== null)) setPolledPath(wantsPoll ? `${base}?poll=1` : null);
  const live = wantsPoll;
  const data = polled ?? first;
  const reading = live && data?.status !== "ready";
  const hasRows = !!data?.guidance.rows.length && data.status === "ready";
  const { data: verdict, error: verdictError, reload: retryVerdict } =
    useApi<{ narrative: Research["narrative"] }>(hasRows ? `${base}/verdict` : null);
  // the two read-and-write sections load after the page, so code-computed numbers show instantly
  const isReady = data?.status === "ready";
  const business = useApi<{ business: Business | null }>(isReady ? `${base}/business` : null);
  const bullBear = useApi<{ case: Case | null }>(isReady ? `${base}/case` : null);
  const [asking, setAsking] = useState(false);
  const [showAllChoice, setShowAll] = useState<boolean | null>(null);
  const [showReasoning, setShowReasoning] = useState(false);
  const nothingScored = !!data && !data.guidance.rows.some((r) => SCORED.has(r.status));
  const showAll = showAllChoice ?? nothingScored;

  const byCall = useMemo(() => {
    const rows = (data?.guidance.rows ?? []).filter((r) => showAll || ((SCORED.has(r.status) || r.status === "pending") && r.same_as == null));
    const groups: Record<string, GuidanceRow[]> = {};
    rows.forEach((r) => (groups[r.stated_in ?? "Undated"] ??= []).push(r));
    return Object.entries(groups);
  }, [data, showAll]);

  async function prepare() {
    setPreparing(true);
    await api(`${base}/prepare`, { method: "POST" });
  }

  if (error && !data) {
    const unknown = /not a listed|invalid ticker/i.test(error);
    return (
      <Failure message={unknown ? `${symbol} isn't a listed NSE symbol. Check the ticker and search again.` : error}
               onRetry={unknown ? undefined : reload}>
        <Link href="/research" className="btn secondary small">Search companies</Link>
      </Failure>
    );
  }
  if (!data) return <Loading label={`Loading research on ${symbol}…`} heights={[90, 160, 220]} onRetry={reload} />;

  const { company, guidance, financials } = data;
  const narrative = verdict?.narrative ?? data.narrative;
  // a promise restated on a later call counts once
  const promises = guidance.rows.filter((r) => r.same_as == null);
  const scored = promises.filter((r) => SCORED.has(r.status)).length;
  // why the rest can't be scored yet, in plain words ("3 are for future years · 2 have no numeric target")
  const unscoredWhy = (() => {
    // [singular, plural]: "1 isn't a reported P&L line", "3 aren't reported P&L lines"
    const forms: Record<string, [string, string]> = {
      pending: ["is for a period not yet reported", "are for periods not yet reported"],
      segment: ["is segment-level", "are segment-level"],
      numeric: ["has no numeric target", "have no numeric target"],
      period: ["has no deadline", "have no deadline"],
      line: ["isn't a reported P&L line", "aren't reported P&L lines"],
    };
    const buckets: Record<string, number> = {};
    for (const r of promises) {
      if (SCORED.has(r.status)) continue;
      const key = r.status === "pending" ? "pending" : /segment/.test(r.reason ?? "") ? "segment"
        : /numeric/.test(r.reason ?? "") ? "numeric" : /period/.test(r.reason ?? "") ? "period" : "line";
      buckets[key] = (buckets[key] ?? 0) + 1;
    }
    return Object.entries(buckets).sort((a, b) => b[1] - a[1])
      .map(([k, n]) => `${n} ${forms[k][n === 1 ? 0 : 1]}`).join(" · ");
  })();
  /** Every conclusion links to the transcript page it rests on. */
  const sourcesFor = (ids: number[]) => {
    const seen = new Set<string>();
    return ids.flatMap((id) => {
      const r = guidance.rows.find((x) => x.id === id);
      if (!r) return [];
      const label = `${r.source.title.replace("Concall transcript, ", "Concall ")}${r.source.page ? `, ${r.source.page}` : ""}`;
      if (seen.has(label)) return [];
      seen.add(label);
      return [{ key: `${id}`, label, url: r.source.url, quote: r.quote }];
    });
  };
  const transcripts = data.documents.filter((d) => d.type === "concall_transcript" && ["indexed", "guidance_extracted"].includes(d.status));
  const hasAR = data.documents.some((d) => d.type === "annual_report" && ["indexed", "guidance_extracted"].includes(d.status));

  return (
    <>
      <Masthead />
      <Link href="/research" className="back">‹ Research</Link>
      <header className="topbar" style={{ paddingTop: 10 }}>
        <div className="row">
          <span className="ticker">{company.symbol}</span>
          {company.in_portfolio && <span className="chip">In portfolio</span>}
        </div>
        <h1 className="display" style={{ fontSize: 40, marginTop: 6 }}>{company.name}</h1>
        <p className="sub">{transcripts.length ? `${transcripts.length} concall transcript${transcripts.length === 1 ? "" : "s"}${hasAR ? " and the annual report" : ""} read` : "Not read yet"}</p>
      </header>

      {data.status !== "ready" && (
        <div className="card" style={{ padding: 16 }}>
          {reading ? (
            <>
              <div className="between small">
                <b>Reading documents</b>
                <span className="num muted">{data.progress.read} of {data.progress.total || "…"}</span>
              </div>
              <div style={{ height: 6, borderRadius: 3, background: "var(--line)", marginTop: 10, overflow: "hidden" }}>
                <div style={{ height: "100%", background: "var(--accent)", transition: "width .4s",
                              width: `${data.progress.total ? (100 * data.progress.read) / data.progress.total : 8}%` }} />
              </div>
              <ul className="stack tiny" style={{ listStyle: "none", marginTop: 12 }}>
                {data.documents.map((d) => (
                  <li key={d.url} className="between">
                    <span className="truncate">{d.title}</span>
                    <span className={d.status === "failed" ? "down" : "muted"}>
                      {["indexed", "guidance_extracted"].includes(d.status) ? "✓ read" : d.status === "failed" ? "couldn't read" : "waiting"}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="tiny muted" style={{ marginTop: 10 }}>About a minute. You can keep browsing; this page updates itself.</p>
            </>
          ) : preparing && data.progress.total === 0 ? (
            <p className="small ink2">FINN couldn&apos;t find concall transcripts or annual reports for {company.name} on
              screener.in, so there is nothing to research yet. Results and filings still appear on Today.</p>
          ) : (
            <>
              <p className="small ink2">FINN will read {company.name}&apos;s last five concall transcripts and latest annual report, extract every piece of guidance and check it against reported numbers.</p>
              <button className="btn accent small" style={{ marginTop: 10 }} onClick={prepare}>Read the documents (~1 min)</button>
            </>
          )}
        </div>
      )}

      {isReady && (
        <SectionIndex items={[
          ["business", "Business"], ["numbers", "Numbers"], ["promises", "Promised vs delivered"],
          ...(data.statements ? [["trajectory", "Trajectory"], ["balance", "Balance sheet"], ["cash", "Cash quality"]] as [string, string][] : []),
          ["case", "Bull vs bear"], ["ask", "Ask"],
        ]} />
      )}
      {isReady && <BusinessSection data={business.data?.business} error={business.error} retry={business.reload} />}
      {data.statements && <SnapshotSection s={data.statements} />}
      <span id="promises" style={{ display: "block", scrollMarginTop: 16 }} />

      {hasRows && !narrative && (
        <section className="verdict">
          <div className="caps">Promised vs delivered · last {guidance.calls.length} calls</div>
          {verdictError ? (
            <div className="between" style={{ marginTop: 8 }}>
              <span className="small ink2">Couldn&apos;t write the verdict: {verdictError}</span>
              <button className="btn secondary small" onClick={retryVerdict}>Retry</button>
            </div>
          ) : (
            <>
              <p className="small muted" style={{ marginTop: 8 }}>Weighing {guidance.rows.length} guidance statements against reported numbers…</p>
              <div className="skeleton" style={{ height: 54, marginTop: 10 }} />
            </>
          )}
        </section>
      )}

      {narrative && (
        <section className={`verdict ${narrative.verdict}`}>
          <div className="caps">Promised vs delivered · last {guidance.calls.length} calls</div>
          {scored === 0 && <span className="badge-flag">Not yet assessable</span>}
          <div className="label">{VERDICT[narrative.verdict]}</div>
          <p className="headline-sm" style={{ marginTop: 8 }}>
            {scored} of {promises.length} promise{promises.length === 1 ? "" : "s"} assessable.
          </p>
          {unscoredWhy && <p className="small muted" style={{ marginTop: 2 }}>{unscoredWhy}</p>}
          <button className="link small" style={{ marginTop: 10 }} aria-expanded={showReasoning}
                  onClick={() => setShowReasoning((v) => !v)}>
            {showReasoning ? "Hide reasoning" : "Read reasoning"}
          </button>
          {showReasoning && <p className="small ink2" style={{ marginTop: 6 }}>{narrative.summary}</p>}
          {narrative.highlights.length > 0 && (
            <ul className="stack" style={{ listStyle: "none", marginTop: 12 }}>
              {narrative.highlights.map((h, i) => (
                <li key={i} className="small">
                  <span>{h.point}</span>
                  <span className="row" style={{ flexWrap: "wrap", gap: 6, marginTop: 4 }}>
                    {sourcesFor(h.row_ids).map((src) => (
                      <a key={src.key} className="chip tiny" href={src.url} target="_blank" rel="noreferrer"
                         title={src.quote} aria-label={`Source: ${src.label}`}>{src.label} ↗</a>
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="tiny muted" style={{ marginTop: 12 }}>
            {narrative.verdict_capped && "No guided period has fully reported yet, so FINN won't call it delivered. "}
            Statuses are computed by code from reported numbers, not by the AI.
          </p>
        </section>
      )}

      <PromiseScorecard rows={guidance.rows} />

      {guidance.rows.length > 0 && (
        <section className="section">
          <div className="section-head">
            <span className="caps">What management said</span>
            <div className="seg compact">
              <button aria-pressed={!showAll} onClick={() => setShowAll(false)}>Scored</button>
              <button aria-pressed={showAll} onClick={() => setShowAll(true)}>All {guidance.rows.length}</button>
            </div>
          </div>
          <div className="stack">
            {byCall.map(([call, rows]) => (
              <div key={call}>
                <div className="eyebrow" style={{ color: "var(--ink)", padding: "16px 0 0", borderTop: "1.5px solid var(--rule)" }}>{call} call</div>
                {rows.map((r) => (
                  <div key={r.id} className="promise">
                    <q>{r.quote}</q>
                    <span className={`status ${r.status}`}>{STATUS_LABEL[r.status]}</span>
                    <div className="tiny muted num" style={{ gridColumn: "1 / -1" }}>
                      <span className="mono">#{r.id}</span> · {METRIC_LABEL[r.metric] ?? r.metric}
                      {r.segment && ` (${r.segment})`}
                      {r.target && ` · guided ${r.target}`}{r.target_period && ` for ${r.target_period}`}
                      {r.actual != null && <> · <b className="ink2">actual {r.actual}%</b>{r.measured_over && ` over ${r.measured_over}`}</>}
                      {r.reiterated_in?.length ? ` · reiterated ${r.reiterated_in.join(", ")}` : ""}
                      {r.same_as != null && ` · repeat of #${r.same_as}`}
                      {" · "}<a className="link" href={r.source.url} target="_blank" rel="noreferrer">{r.source.page}</a>
                    </div>
                    {!SCORED.has(r.status) && (
                      <div className="why-not small" style={{ gridColumn: "1 / -1" }}>
                        <b>Why not scored:</b> {r.status === "pending" ? `${r.target_period ?? "the target period"} hasn't been reported yet` : r.reason}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ))}
            {byCall.length === 0 && <div className="empty card">No guidance could be scored against reported numbers yet. <button className="link" onClick={() => setShowAll(true)}>Show all statements</button></div>}
          </div>
        </section>
      )}

      {data.statements ? (
        <>
          <TrajectorySection s={data.statements} financial={!!company.is_financial}>
            {financials.quarters.length > 0 && <MetricChart financials={financials} financial={!!company.is_financial} />}
          </TrajectorySection>
          <BalanceSection s={data.statements} financial={!!company.is_financial} />
          <CashSection s={data.statements} />
        </>
      ) : financials.quarters.length > 0 && <MetricChart financials={financials} financial={!!company.is_financial} />}

      {isReady && <CaseSection data={bullBear.data?.case} error={bullBear.error} retry={bullBear.reload} />}

      <section className="section" id="ask" style={{ scrollMarginTop: 16 }}>
        <button className="btn accent block" onClick={() => setAsking(true)} disabled={data.status !== "ready"}>Ask FINN about {company.name}</button>
      </section>

      {data.documents.length > 0 && (
        <section className="section">
          <div className="section-head"><span className="caps">Sources read</span></div>
          <div style={{ borderTop: "1.5px solid var(--rule)" }}>
            {data.documents.map((d) => (
              <a key={d.url} href={d.url} target="_blank" rel="noreferrer" className="between small"
                 style={{ padding: "11px 0", borderBottom: "1px solid var(--line)" }}>
                <span className="truncate">{d.title}</span>
                <span className={`tiny ${d.status === "failed" ? "down" : "muted"}`} title={d.error ?? undefined}>
                  {d.status === "failed" ? "couldn't read: link moved or expired" : ["indexed", "guidance_extracted"].includes(d.status) ? `✓ ${d.period ?? ""}` : "not read yet"}
                </span>
              </a>
            ))}
          </div>
        </section>
      )}

      {asking && <AskSheet symbol={company.symbol} name={company.name} onClose={() => setAsking(false)} />}
    </>
  );
}
