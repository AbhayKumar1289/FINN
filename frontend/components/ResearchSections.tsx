"use client";

import { useState } from "react";
import type { Business, Case, Source, Statements } from "@/lib/api";
import { Failure } from "./Status";

type Series = (number | null)[];

const cr = (v: number | null | undefined) =>
  v == null ? "–" : Math.abs(v) >= 100000 ? `${(v / 100000).toFixed(2)} L` : Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0);
const crLong = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")} cr`;
const pctFmt = (v: number | null | undefined) => (v == null ? "–" : `${v.toFixed(1)}%`);
const xFmt = (v: number | null | undefined) => (v == null ? "–" : `${v.toFixed(2)}×`);
const days = (v: number | null | undefined) => (v == null ? "–" : `${v.toFixed(0)}`);

/** Jump list for the research page: the brief's research menu, one tap each. */
export function SectionIndex({ items }: { items: [string, string][] }) {
  return (
    <nav className="section-index" aria-label="Research sections">
      {items.map(([id, label]) => <a key={id} href={`#${id}`} className="toggle">{label}</a>)}
    </nav>
  );
}

function Head({ id, title, note }: { id: string; title: string; note?: string }) {
  return (
    <div className="section-head">
      <h2 id={id} className="caps" style={{ color: "var(--ink)", scrollMarginTop: 16 }}>{title}</h2>
      {note && <span className="tiny muted">{note}</span>}
    </div>
  );
}

function Notes({ notes }: { notes: string[] }) {
  if (!notes.length) return null;
  return <ul className="reads">{notes.map((n) => <li key={n} className="small">{n}</li>)}</ul>;
}

function SourceLine({ s }: { s: Statements }) {
  return <p className="tiny muted" style={{ marginTop: 8 }}>Computed by FINN from {s.source} ({s.basis}). ₹ crore; k = thousand crore, L = lakh crore.</p>;
}

/** Grouped bars by year; values print on the bars' own row below so nothing needs hovering. */
function YearBars({ years, series, fmt = cr }: {
  years: string[]; series: { label: string; values: Series; color: string }[]; fmt?: (v: number | null) => string;
}) {
  const W = 320, H = 110, TOP = 6;
  const all = series.flatMap((s) => s.values).filter((v): v is number => v != null);
  if (!all.length) return null;
  const hi = Math.max(...all, 0), lo = Math.min(...all, 0);
  const y = (v: number) => TOP + (1 - (v - lo) / (hi - lo || 1)) * (H - TOP);
  const slot = W / years.length, bw = (slot * 0.7) / series.length;
  return (
    <figure style={{ margin: "10px 0 0" }}>
      {series.length > 1 && (
        <div className="legend tiny" aria-hidden>
          {series.map((s) => <span key={s.label}><span className="sw" style={{ background: s.color }} /> {s.label}</span>)}
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${H + 16}`} width="100%" role="img" style={{ display: "block" }}
           aria-label={series.map((s) => `${s.label}: ${years.map((yr, i) => `${yr} ${fmt(s.values[i])}`).join(", ")}`).join(". ")}>
        <line x1={0} x2={W} y1={y(0)} y2={y(0)} stroke="var(--line)" />
        {years.map((yr, i) => (
          <g key={yr}>
            {series.map((s, k) => {
              const v = s.values[i];
              if (v == null) return null;
              return <rect key={s.label} x={i * slot + slot * 0.15 + k * bw} width={bw - 1.5} rx={1.5}
                           y={Math.min(y(v), y(0))} height={Math.max(1, Math.abs(y(v) - y(0)))}
                           fill={v < 0 ? "var(--down)" : s.color} />;
            })}
            <text x={i * slot + slot / 2} y={H + 13} fontSize="9.5" textAnchor="middle" fill="var(--ink-3)">{yr}</text>
          </g>
        ))}
      </svg>
    </figure>
  );
}

function YearTable({ years, rows }: { years: string[]; rows: { label: string; values: Series; fmt: (v: number | null) => string; emphasise?: boolean }[] }) {
  return (
    <div className="year-table-wrap">
      <table className="year-table num">
        <thead><tr><th scope="col"><span className="sr-only">Metric</span></th>{years.map((y) => <th key={y} scope="col">{y}</th>)}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className={r.emphasise ? "em" : undefined}>
              <th scope="row">{r.label}</th>
              {r.values.map((v, i) => <td key={i}>{r.fmt(v)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SnapshotSection({ s }: { s: Statements }) {
  if (!s.snapshot.length) return null;
  return (
    <section className="section" aria-labelledby="numbers">
      <Head id="numbers" title="Financial snapshot" note="last 12 months" />
      <div className="stat-grid num">
        {s.snapshot.map((x) => (
          <div key={x.label}>
            <span className="k">{x.label}</span>
            <span className="v">{x.unit === "cr" ? crLong(x.value) : x.unit === "pct" ? pctFmt(x.value) : xFmt(x.value)}</span>
          </div>
        ))}
      </div>
      <SourceLine s={s} />
    </section>
  );
}

export function TrajectorySection({ s, financial, children }: { s: Statements; financial: boolean; children?: React.ReactNode }) {
  const t = s.trajectory;
  if (!s.years.length) return null;
  return (
    <section className="section" aria-labelledby="trajectory">
      <Head id="trajectory" title="Trajectory" note={t.cagr ? `${t.cagr.from}–${t.cagr.to}` : undefined} />
      <Notes notes={t.notes} />
      <YearBars years={s.years} series={[{ label: financial ? "Total income" : "Revenue", values: t.revenue, color: "color-mix(in srgb, var(--accent) 45%, var(--surface-2))" }]} />
      <YearTable years={s.years} rows={[
        { label: financial ? "Income" : "Revenue", values: t.revenue, fmt: cr },
        { label: "Net profit", values: t.pat, fmt: cr },
        ...(t.margin ? [{ label: "Op. margin", values: t.margin, fmt: pctFmt, emphasise: true }] : []),
      ]} />
      <SourceLine s={s} />
      {children}
    </section>
  );
}

export function BalanceSection({ s, financial }: { s: Statements; financial: boolean }) {
  const b = s.balance;
  if (!b.years.length) return null;
  return (
    <section className="section" aria-labelledby="balance">
      <Head id="balance" title="Balance sheet" note={b.interest_cover != null ? `interest cover ${b.interest_cover.toFixed(0)}×` : undefined} />
      <Notes notes={b.notes} />
      <YearBars years={b.years} series={[
        { label: "Net worth", values: b.net_worth, color: "color-mix(in srgb, var(--accent) 45%, var(--surface-2))" },
        ...(financial && b.deposits ? [{ label: "Deposits", values: b.deposits, color: "var(--ink-3)" }]
          : [{ label: "Borrowings", values: b.debt, color: "var(--medium)" }]),
      ]} />
      <YearTable years={b.years} rows={[
        { label: "Net worth", values: b.net_worth, fmt: cr },
        { label: "Borrowings", values: b.debt, fmt: cr },
        ...(financial && b.deposits ? [{ label: "Deposits", values: b.deposits, fmt: cr }] : []),
        ...(b.de ? [{ label: "Debt/equity", values: b.de, fmt: xFmt, emphasise: true }] : []),
        ...(b.ccc?.some((v) => v != null) ? [{ label: "Cash cycle, days", values: b.ccc, fmt: days }] : []),
      ]} />
      <SourceLine s={s} />
    </section>
  );
}

export function CashSection({ s }: { s: Statements }) {
  const c = s.cash;
  return (
    <section className="section" aria-labelledby="cash">
      <Head id="cash" title="Cash quality" note={c.cumulative?.ratio != null ? `cash ÷ profit ${c.cumulative.ratio.toFixed(2)}×` : undefined} />
      <Notes notes={c.notes} />
      {c.applicable && c.years.length > 0 && (
        <>
          <YearBars years={c.years} series={[
            { label: "Operating cash flow", values: c.cfo, color: "var(--accent)" },
            { label: "Net profit", values: c.pat, color: "color-mix(in srgb, var(--ink-3) 55%, var(--surface-2))" },
          ]} />
          <YearTable years={c.years} rows={[
            { label: "Op. cash flow", values: c.cfo, fmt: cr },
            { label: "Net profit", values: c.pat, fmt: cr },
            { label: "Cash ÷ profit", values: c.conversion, fmt: (v) => (v == null ? "–" : `${v.toFixed(2)}×`), emphasise: true },
            ...(c.fcf.some((v) => v != null) ? [{ label: "Free cash flow", values: c.fcf, fmt: cr }] : []),
          ]} />
          <p className="tiny muted" style={{ marginTop: 6 }}>Above 1× means the year&apos;s profit arrived as cash. Persistent readings below 0.7× deserve a question.</p>
        </>
      )}
      <SourceLine s={s} />
    </section>
  );
}

/** Document citations link out; FINN's own computed figures fold into one chip that opens in place. */
function SourceChips({ refs, sources }: { refs: number[]; sources: Source[] }) {
  const [open, setOpen] = useState(false);
  const cited = refs.map((n) => sources.find((x) => x.n === n)).filter((x): x is Source => !!x);
  const calcs = cited.filter((x) => x.kind === "finn_fact" && !x.url);
  // two excerpts from the same page are one citation
  const docs = cited.filter((x, i) => !(x.kind === "finn_fact" && !x.url)
    && cited.findIndex((y) => y.url === x.url && y.page === x.page) === i);
  return (
    <>
      <span className="row" style={{ flexWrap: "wrap", gap: 6, marginTop: 4 }}>
        {calcs.length > 0 && (
          <button className="chip tiny" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            FINN figures{calcs.length > 1 ? ` ×${calcs.length}` : ""} {open ? "▴" : "▾"}
          </button>
        )}
        {docs.map((src) => {
          const page = src.page == null ? "" : String(src.page).startsWith("p.") ? `, ${src.page}` : `, p.${src.page}`;
          return <a key={src.n} className="chip tiny" href={src.url ?? undefined} target="_blank" rel="noreferrer"
                    title={src.excerpt}>{src.title.replace("Concall transcript, ", "Concall ")}{page} ↗</a>;
        })}
      </span>
      {open && <ul className="calc-list tiny ink2">{calcs.map((c) => <li key={c.n}>{c.excerpt}</li>)}</ul>}
    </>
  );
}

const SEG_COLORS = ["var(--accent)", "var(--medium)", "var(--ink-3)", "var(--high)", "var(--up)"];

export function BusinessSection({ data, error, retry }: { data: Business | null | undefined; error: string | null; retry: () => void }) {
  return (
    <section className="section" aria-labelledby="business">
      <Head id="business" title="Business snapshot" note="from the annual report" />
      {error && !data ? <Failure message={error} onRetry={retry} />
        : data === undefined ? <div className="skeleton" style={{ height: 120 }} aria-label="Reading the annual report…" />
        : data === null ? <p className="small muted">No annual report or transcript has been read yet.</p>
        : (
          <>
            <p className="ink2" style={{ fontSize: 16, lineHeight: 1.5 }}>{data.summary}</p>
            {data.segments.some((x) => x.share_pct != null) && (
              <div className="mix-bar" role="img" aria-label={`Revenue mix: ${data.segments.filter((x) => x.share_pct != null).map((x) => `${x.name} ${x.share_pct}%`).join(", ")}`}>
                {data.segments.filter((x) => x.share_pct != null).map((x, i) => (
                  <span key={x.name} style={{ width: `${x.share_pct}%`, background: SEG_COLORS[i % SEG_COLORS.length] }} />
                ))}
              </div>
            )}
            <ul className="segments">
              {data.segments.map((x, i) => (
                <li key={x.name}>
                  <div className="between" style={{ alignItems: "baseline" }}>
                    <span className="small" style={{ fontWeight: 600 }}>
                      {x.share_pct != null && <span className="sw" style={{ background: SEG_COLORS[i % SEG_COLORS.length], marginRight: 6 }} aria-hidden />}
                      {x.name}
                    </span>
                    {x.share_pct != null && <span className="num small" style={{ fontWeight: 600 }}>{x.share_pct}%</span>}
                  </div>
                  <p className="tiny ink2" style={{ marginTop: 2 }}>{x.detail}</p>
                  <SourceChips refs={[x.ref]} sources={data.sources} />
                </li>
              ))}
            </ul>
            {data.facts.length > 0 && (
              <ul className="reads" style={{ marginTop: 12 }}>
                {data.facts.map((f) => <li key={f.text} className="small">{f.text} <SourceChips refs={[f.ref]} sources={data.sources} /></li>)}
              </ul>
            )}
            <p className="tiny muted" style={{ marginTop: 8 }}>Written by AI from the cited pages only. A revenue share appears only when the page prints it.</p>
          </>
        )}
    </section>
  );
}

export function CaseSection({ data, error, retry }: { data: Case | null | undefined; error: string | null; retry: () => void }) {
  return (
    <section className="section" aria-labelledby="case">
      <Head id="case" title="Bull vs bear" note="not a recommendation" />
      {error && !data ? <Failure message={error} onRetry={retry} />
        : data === undefined ? <div className="skeleton" style={{ height: 160 }} aria-label="Weighing both sides…" />
        : data === null ? <p className="small muted">Not enough material read yet to argue either side.</p>
        : (
          <div className="case-grid">
            {(["bull", "bear"] as const).map((side) => (
              <div key={side} className={`case ${side}`}>
                <div className="eyebrow">{side === "bull" ? "▲ Bull case" : "▼ Bear case"}</div>
                <ol>
                  {data[side].map((p) => (
                    <li key={p.point} className="small">
                      {p.point}
                      <SourceChips refs={p.refs} sources={data.sources} />
                    </li>
                  ))}
                </ol>
              </div>
            ))}
            <p className="tiny muted">Every point cites FINN&apos;s computed figures or the company&apos;s own transcripts and annual report; uncited points are dropped.</p>
          </div>
        )}
    </section>
  );
}
