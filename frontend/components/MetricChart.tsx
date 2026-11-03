"use client";

import { useState } from "react";
import type { Research } from "@/lib/api";

type Q = Research["financials"]["quarters"][number];
type Metric = {
  key: string; label: string; unit: "cr" | "pct"; definition: string;
  value: (q: Q) => number | null;
};

const ratio = (a?: number | null, b?: number | null) => (a != null && b ? (a / b) * 100 : null);

/** Sector-appropriate metrics. Lenders get income and profit, not "operating margin". */
function metricsFor(financial: boolean, quarters: Q[]): Metric[] {
  if (financial) {
    return [
      { key: "rev", label: "Total income", unit: "cr", value: (q) => q.revenue ?? null,
        definition: "Interest earned plus fee and other operating income, ₹ crore." },
      { key: "pat", label: "Net profit", unit: "cr", value: (q) => q.pat ?? null,
        definition: "Profit after tax, ₹ crore." },
      { key: "npm", label: "Net margin", unit: "pct", value: (q) => ratio(q.pat, q.revenue),
        definition: "Net profit as a % of total income. (Operating margin isn't meaningful for a lender.)" },
    ];
  }
  // one operating-profit definition for every quarter (mixing two would invent a margin change)
  const op: "operating_profit" | "ebitda" = quarters.some((q) => q.operating_profit != null) ? "operating_profit" : "ebitda";
  return [
    { key: "rev", label: "Revenue", unit: "cr", value: (q) => q.revenue ?? null,
      definition: "Revenue from operations, ₹ crore." },
    { key: "op", label: "Operating profit", unit: "cr", value: (q) => q[op] ?? null,
      definition: "Revenue minus operating costs, before interest, depreciation and tax, ₹ crore." },
    { key: "pat", label: "Net profit", unit: "cr", value: (q) => q.pat ?? null,
      definition: "Profit after tax, ₹ crore." },
    { key: "opm", label: "Operating margin", unit: "pct", value: (q) => ratio(q[op], q.revenue),
      definition: "Operating profit as a % of revenue. Below zero means costs exceeded revenue." },
  ];
}

function fmt(v: number, unit: "cr" | "pct", short = false) {
  if (unit === "pct") return short && Number.isInteger(v) ? `${v}%` : `${v.toFixed(1)}%`;
  if (short) return Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(Math.abs(v) >= 100000 || v % 1000 === 0 ? 0 : 1)}k` : `${Math.round(v)}`;
  return `₹${Math.round(v).toLocaleString("en-IN")} cr`;
}

function yearAgo(period: string) {
  const m = /^Q([1-4])FY(\d{2})$/.exec(period);
  return m ? `Q${m[1]}FY${String(Number(m[2]) - 1).padStart(2, "0")}` : null;
}

const W = 320, H = 150, PAD_L = 40, TOP = 18;

export default function MetricChart({ financials, financial }: { financials: Research["financials"]; financial: boolean }) {
  const all = financials.quarters;
  const metrics = metricsFor(financial, all);
  const [key, setKey] = useState(metrics[0].key);
  const metric = metrics.find((m) => m.key === key) ?? metrics[0];
  const series = all.map((q) => ({ period: q.period, v: metric.value(q) }));
  const [sel, setSel] = useState<number | null>(null);
  const idx = sel != null && sel < series.length ? sel : series.length - 1;

  const vals = series.map((s) => s.v).filter((v): v is number => v != null);
  if (!vals.length) return null;
  // evenly stepped "nice" ticks (1/2/2.5/5 × 10^n); the axis spans exactly the outer ticks
  const rawLo = Math.min(0, ...vals), rawHi = Math.max(0, ...vals);
  const rough = (rawHi - rawLo) / 3 || 1;
  const pow = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((st) => st >= rough) ?? rough;
  const lo = Math.floor(rawLo / step) * step, hi = Math.ceil(rawHi / step) * step || step;
  const ticks: number[] = [];
  for (let t = lo; t <= hi + step / 2; t += step) ticks.push(+t.toFixed(6));
  const y = (v: number) => TOP + (1 - (v - lo) / (hi - lo)) * (H - TOP);
  const slot = (W - PAD_L) / series.length;
  const xc = (i: number) => PAD_L + slot * (i + 0.5);

  const cur = series[idx];
  const prevPeriod = yearAgo(cur.period);
  const prev = series.find((s) => s.period === prevPeriod)?.v ?? null;
  const yoy = cur.v != null && prev != null
    ? metric.unit === "pct" ? `${cur.v - prev >= 0 ? "+" : "−"}${Math.abs(cur.v - prev).toFixed(1)} pp YoY`
      : prev > 0 ? `${cur.v >= prev ? "+" : "−"}${Math.abs((cur.v / prev - 1) * 100).toFixed(1)}% YoY` : null
    : null;

  return (
    <section className="section" aria-labelledby="metric-h">
      <div className="section-head">
        <span id="metric-h" className="caps" style={{ color: "var(--ink)" }}>Quarterly trend</span>
        <span className="tiny muted">{all.length} quarters · {financials.basis}</span>
      </div>
      <div className="metric-chips" role="tablist" aria-label="Metric">
        {metrics.map((m) => (
          <button key={m.key} role="tab" aria-selected={m.key === metric.key} className="toggle"
                  onClick={() => { setKey(m.key); setSel(null); }}>{m.label}</button>
        ))}
      </div>

      <div className="metric-readout" aria-live="polite">
        <span className="headline-sm num">{cur.v == null ? "–" : fmt(cur.v, metric.unit)}</span>
        <span className="small muted"> {cur.period.replace("FY", " FY")}{yoy && <> · <span className={yoy.startsWith("+") ? "up" : "down"}>{yoy}</span></>}</span>
      </div>

      <svg viewBox={`0 0 ${W} ${H + 22}`} width="100%" role="img" style={{ display: "block", marginTop: 6 }}
           aria-label={`${metric.label} by quarter: ${series.map((s) => `${s.period} ${s.v == null ? "n/a" : fmt(s.v, metric.unit)}`).join(", ")}`}>
        {ticks.map((t, k) => (
          <g key={k}>
            <line x1={PAD_L} x2={W} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeDasharray={t === 0 ? undefined : "2 4"} />
            <text x={PAD_L - 6} y={y(t) + 3.5} fontSize="9.5" textAnchor="end" fill="var(--ink-3)">{fmt(t, metric.unit, true)}</text>
          </g>
        ))}
        {metric.unit === "cr" ? series.map((s, i) => s.v == null ? null : (
          <rect key={s.period} x={xc(i) - slot * 0.32} width={slot * 0.64} rx={2}
                y={Math.min(y(s.v), y(0))} height={Math.max(1, Math.abs(y(s.v) - y(0)))}
                fill={i === idx ? "var(--accent)" : s.v < 0 ? "var(--down)" : "color-mix(in srgb, var(--accent) 38%, var(--surface-2))"}
                onClick={() => setSel(i)} style={{ cursor: "pointer" }} />
        )) : (
          <>
            <path d={series.map((s, i) => s.v == null ? "" : `${i && series[i - 1].v != null ? "L" : "M"}${xc(i)},${y(s.v)}`).join("")}
                  fill="none" stroke="var(--accent)" strokeWidth={2} />
            {series.map((s, i) => s.v == null ? null : (
              <circle key={s.period} cx={xc(i)} cy={y(s.v)} r={i === idx ? 5 : 3.5} onClick={() => setSel(i)}
                      fill={s.v < 0 ? "var(--down)" : i === idx ? "var(--accent)" : "var(--surface)"} stroke="var(--accent)" strokeWidth={1.5}
                      style={{ cursor: "pointer" }} />
            ))}
          </>
        )}
        {series.map((s, i) => (
          <text key={`l${s.period}`} x={xc(i)} y={H + 15} fontSize="9" textAnchor="middle"
                fill={i === idx ? "var(--ink)" : "var(--ink-3)"} fontWeight={i === idx ? 700 : 400}>
            {s.period.replace(/FY(\d\d)/, "'$1")}
          </text>
        ))}
      </svg>
      <p className="tiny muted" style={{ marginTop: 6 }}>
        {metric.definition} Tap a quarter for its value. {series.some((s) => s.v == null) && "– = not yet in the comparable series. "}
        Source: screener.in quarterly table plus FINN&apos;s extraction from the latest results filing.
      </p>
    </section>
  );
}
