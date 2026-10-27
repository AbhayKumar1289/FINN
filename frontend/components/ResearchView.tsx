"use client";

import Link from "next/link";
import { use, useMemo, useState } from "react";
import { api, type GuidanceRow, type Research } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import AskSheet from "./AskSheet";

const VERDICT = {
  delivers: "Delivers on guidance",
  mixed: "Mixed record",
  over_promises: "Over-promises",
  too_early: "Too early to judge",
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
  const { data, error, reload } = useApi<Research>(`/api/research/${encodeURIComponent(symbol)}`);
  const [asking, setAsking] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [preparing, setPreparing] = useState(false);

  const byCall = useMemo(() => {
    const rows = (data?.guidance.rows ?? []).filter((r) => showAll || SCORED.has(r.status) || r.status === "pending");
    const groups: Record<string, GuidanceRow[]> = {};
    rows.forEach((r) => (groups[r.stated_in ?? "Undated"] ??= []).push(r));
    return Object.entries(groups);
  }, [data, showAll]);

  async function prepare() {
    setPreparing(true);
    await api(`/api/research/${encodeURIComponent(symbol)}/prepare`, { method: "POST" });
    const poll = async () => {
      const r = await api<Research>(`/api/research/${encodeURIComponent(symbol)}?narrative=false`);
      if (r.status === "ready") { setPreparing(false); reload(); } else setTimeout(poll, 5000);
    };
    setTimeout(poll, 5000);
  }

  if (error) return <div className="error section">{error}</div>;
  if (!data) return <div className="stack section">{[90, 160, 220].map((h, i) => <div key={i} className="skeleton" style={{ height: h }} />)}</div>;

  const { company, guidance, narrative, financials } = data;
  const scored = guidance.rows.filter((r) => SCORED.has(r.status)).length;
  const transcripts = data.documents.filter((d) => d.type === "concall_transcript" && d.status !== "failed");

  return (
    <>
      <header className="topbar">
        <Link href="/research" className="tiny link">‹ Research</Link>
        <div className="row" style={{ marginTop: 8 }}>
          <span className="mono caps" style={{ color: "var(--ink)", fontSize: 12 }}>{company.symbol}</span>
          {company.in_portfolio && <span className="chip">In portfolio</span>}
        </div>
        <h1>{company.name}</h1>
        <p className="sub">{transcripts.length ? `${transcripts.length} concall transcripts · ${data.documents.filter((d) => d.type === "annual_report").length} annual report read` : "Not read yet"}</p>
      </header>

      {data.status !== "ready" && (
        <div className="card" style={{ padding: 16 }}>
          {data.status === "preparing" || preparing ? (
            <p className="small ink2">Reading the last five concall transcripts and the latest annual report… This page updates when it&apos;s done.</p>
          ) : (
            <>
              <p className="small ink2">FINN will read {company.name}&apos;s last five concall transcripts and latest annual report, extract every piece of guidance and check it against reported numbers.</p>
              <button className="btn accent small" style={{ marginTop: 10 }} onClick={prepare}>Read the documents (~1 min)</button>
            </>
          )}
        </div>
      )}

      {narrative && (
        <section className={`card verdict ${narrative.verdict}`}>
          <div className="caps">Promised vs delivered · last {guidance.calls.length} calls</div>
          <div className="label">{VERDICT[narrative.verdict]}</div>
          <p className="small ink2" style={{ marginTop: 6 }}>{narrative.summary}</p>
          {narrative.highlights.length > 0 && (
            <ul className="stack" style={{ listStyle: "none", marginTop: 12 }}>
              {narrative.highlights.map((h, i) => (
                <li key={i} className="small row" style={{ alignItems: "flex-start" }}>
                  <span className="muted mono tiny" style={{ marginTop: 2 }}>#{h.row_ids.join(",")}</span>
                  <span>{h.point}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="tiny muted" style={{ marginTop: 12 }}>
            Statuses are computed from reported numbers, not by the AI. {scored} of {guidance.rows.length} statements could be scored.
          </p>
        </section>
      )}

      {guidance.rows.length > 0 && (
        <section className="section">
          <div className="section-head">
            <span className="caps">What management said</span>
            <div className="seg">
              <button aria-pressed={!showAll} onClick={() => setShowAll(false)}>Scored</button>
              <button aria-pressed={showAll} onClick={() => setShowAll(true)}>All {guidance.rows.length}</button>
            </div>
          </div>
          <div className="stack">
            {byCall.map(([call, rows]) => (
              <div key={call} className="card">
                <div className="caps" style={{ padding: "12px 14px 0" }}>{call} call</div>
                {rows.map((r) => (
                  <div key={r.id} className="promise">
                    <q>{r.quote}</q>
                    <span className={`status ${r.status}`}>{STATUS_LABEL[r.status]}</span>
                    <div className="tiny muted num" style={{ gridColumn: "1 / -1" }}>
                      <span className="mono">#{r.id}</span> · {METRIC_LABEL[r.metric] ?? r.metric}
                      {r.segment && ` (${r.segment})`}
                      {r.target && ` · guided ${r.target}`}{r.target_period && ` for ${r.target_period}`}
                      {r.actual != null && <> · <b className="ink2">actual {r.actual}%</b>{r.measured_over && ` over ${r.measured_over}`}</>}
                      {r.reason && !SCORED.has(r.status) && ` · ${r.reason}`}
                      {" · "}<a className="link" href={r.source.url} target="_blank" rel="noreferrer">{r.source.page}</a>
                    </div>
                  </div>
                ))}
              </div>
            ))}
            {byCall.length === 0 && <div className="empty card">No guidance could be scored against reported numbers yet. <button className="link" onClick={() => setShowAll(true)}>Show all statements</button></div>}
          </div>
        </section>
      )}

      {financials.quarters.length > 0 && <Trend f={financials} />}

      <section className="section">
        <button className="btn accent block" onClick={() => setAsking(true)} disabled={data.status !== "ready"}>Ask FINN about {company.name}</button>
      </section>

      {data.documents.length > 0 && (
        <section className="section">
          <div className="section-head"><span className="caps">Sources read</span></div>
          <div className="card">
            {data.documents.map((d, i) => (
              <a key={d.url} href={d.url} target="_blank" rel="noreferrer" className="between small"
                 style={{ padding: "10px 14px", borderTop: i ? "1px solid var(--line)" : undefined }}>
                <span className="truncate">{d.title}</span>
                <span className="tiny muted">{d.status === "failed" ? "couldn't read" : d.period ?? ""}</span>
              </a>
            ))}
          </div>
        </section>
      )}

      {asking && <AskSheet symbol={company.symbol} name={company.name} onClose={() => setAsking(false)} />}
    </>
  );
}

function Trend({ f }: { f: Research["financials"] }) {
  const qs = f.quarters.filter((q) => q.revenue != null);
  const max = Math.max(...qs.map((q) => q.revenue!));
  return (
    <section className="section">
      <div className="section-head"><span className="caps">Revenue & margin · last {qs.length} quarters</span><span className="tiny muted">₹ crore · {f.basis}</span></div>
      <div className="card" style={{ padding: "14px 14px 10px" }}>
        <div className="bars">
          {qs.map((q, i) => {
            const op = q.operating_profit ?? q.ebitda;
            const m = op != null && q.revenue ? Math.round((op / q.revenue) * 1000) / 10 : null;
            return (
              <div key={q.period} className={`bar ${i === qs.length - 1 ? "last" : ""}`} title={`${q.period}: ₹${Math.round(q.revenue!).toLocaleString("en-IN")} cr`}>
                <span className="tiny muted num">{m != null ? `${m}%` : ""}</span>
                <i style={{ height: `${Math.max(8, (q.revenue! / max) * 64)}px` }} />
              </div>
            );
          })}
        </div>
        <div className="bars" style={{ height: "auto", marginTop: 4 }}>
          {qs.map((q) => <div key={q.period} className="bar"><span className="tiny muted">{q.period.replace("FY", "·")}</span></div>)}
        </div>
      </div>
    </section>
  );
}
