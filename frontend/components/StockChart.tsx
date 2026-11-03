"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export type Bar = { date: string; close: number; adj_close: number; volume: number };
export type ChartEvent = { date: string; id: number; priority: string; headline: string; url: string | null };

export type Point = {
  i: number; date: string; value: number; close: number; volume: number;
  pct: number; bench: number | null; ma: number | null; events: ChartEvent[];
};

const H_PRICE = 210;
const H_VOL = 46;
const GAP = 10;
const PAD_R = 46;   // y-axis labels
const PAD_T = 10;

function niceTicks(lo: number, hi: number, n = 4): number[] {
  const span = hi - lo || Math.abs(hi) || 1;
  const raw = span / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

function fmtAxis(v: number, mode: "price" | "pct"): string {
  if (mode === "pct") return `${v > 0 ? "+" : ""}${v.toFixed(Math.abs(v) < 10 ? 1 : 0)}%`;
  return v >= 10000 ? `${(v / 1000).toFixed(1)}k` : v >= 1000 ? v.toLocaleString("en-IN", { maximumFractionDigits: 0 }) : v.toFixed(v < 100 ? 1 : 0);
}

function fmtDate(d: string, span: number): string {
  const dt = new Date(d + "T12:00:00+05:30");
  if (span <= 7) return dt.toLocaleDateString("en-IN", { weekday: "short", day: "numeric" });
  if (span <= 130) return dt.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  return dt.toLocaleDateString("en-IN", { month: "short", year: "2-digit" }).replace(" ", " '");
}

/**
 * Interactive end-of-day price chart. `history` is the full series (moving averages are computed
 * on it so they're valid from the first visible day); `sessions` is how many to show.
 * Price mode plots the traded close; compare mode plots % change from the range start using
 * split/dividend-adjusted closes, for the stock and for the benchmark.
 */
export default function StockChart({ history, sessions, benchmark, events, compare, maWindow, showEvents, onScrub, label }: {
  history: Bar[];
  sessions: number;
  benchmark: { date: string; adj_close: number }[];
  events: ChartEvent[];
  compare: boolean;
  maWindow: number | null;
  showEvents: boolean;
  onScrub: (p: Point | null, all: Point[]) => void;
  label: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(340);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(260, Math.floor(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const points = useMemo<Point[]>(() => {
    const start = Math.max(0, history.length - sessions);
    const view = history.slice(start);
    const base = view[0]?.adj_close ?? 1;
    const bmap = new Map(benchmark.map((b) => [b.date, b.adj_close]));
    const bBase = view.map((v) => bmap.get(v.date)).find((x) => x != null) ?? null;
    const evByDate = new Map<string, ChartEvent[]>();
    for (const e of events) {
      // a filing after the close lands on the next session: pin it to the first bar on/after its date
      const at = view.find((v) => v.date >= e.date)?.date;
      if (at) evByDate.set(at, [...(evByDate.get(at) ?? []), e]);
    }
    return view.map((v, k) => {
      const i = start + k;
      let ma: number | null = null;
      if (maWindow && i + 1 >= maWindow) {
        let s = 0;
        for (let j = i - maWindow + 1; j <= i; j++) s += history[j].close;
        ma = s / maWindow;
      }
      const b = bmap.get(v.date);
      return {
        i: k, date: v.date, close: v.close, volume: v.volume,
        pct: (v.adj_close / base - 1) * 100,
        value: compare ? (v.adj_close / base - 1) * 100 : v.close,
        bench: b != null && bBase ? (b / bBase - 1) * 100 : null,
        ma: compare ? null : ma,
        events: evByDate.get(v.date) ?? [],
      };
    });
  }, [history, sessions, benchmark, events, compare, maWindow]);

  // keep the parent's header in sync (scrubbed point, or null for "latest")
  const active = hover != null && points[hover] ? points[hover] : null;
  useEffect(() => { onScrub(active, points); }, [active, points, onScrub]);

  if (points.length < 2) return <div className="empty">Not enough history for this range.</div>;

  const mode = compare ? "pct" : "price";
  const w = width - PAD_R;
  const vals = points.flatMap((p) => [p.value, ...(compare && p.bench != null ? [p.bench] : []), ...(p.ma != null ? [p.ma] : [])]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.08 || 1;
  lo -= pad; hi += pad;
  const x = (i: number) => (points.length === 1 ? w / 2 : (i / (points.length - 1)) * w);
  const y = (v: number) => PAD_T + (1 - (v - lo) / (hi - lo)) * (H_PRICE - PAD_T);
  const up = points[points.length - 1].pct >= 0;
  const color = up ? "var(--up)" : "var(--down)";
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join("");
  const area = `${line}L${x(points.length - 1)},${H_PRICE}L0,${H_PRICE}Z`;
  const bench = compare ? points.filter((p) => p.bench != null)
    .map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.bench!).toFixed(1)}`).join("") : "";
  const maPath = points.filter((p) => p.ma != null).map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.ma!).toFixed(1)}`).join("");
  const vmax = Math.max(...points.map((p) => p.volume)) || 1;
  const barW = Math.max(1, (w / points.length) * 0.7);
  const ticks = niceTicks(lo + pad, hi - pad);
  const xLabels = [0, Math.floor((points.length - 1) / 2), points.length - 1];
  const totalH = H_PRICE + GAP + H_VOL + 18;
  const zeroY = compare ? y(0) : null;

  function pick(clientX: number) {
    const r = wrap.current!.getBoundingClientRect();
    const rel = Math.min(Math.max(clientX - r.left, 0), w);
    setHover(Math.round((rel / w) * (points.length - 1)));
  }

  return (
    <div ref={wrap} className="stock-chart">
      <svg width={width} height={totalH} role="img" tabIndex={0}
           aria-label={`${label}. Use left and right arrow keys to move through days.`}
           style={{ touchAction: "none", display: "block", outline: "none" }}
           onPointerDown={(e) => pick(e.clientX)} onPointerMove={(e) => pick(e.clientX)}
           onPointerLeave={() => setHover(null)}
           onPointerUp={(e) => { if (e.pointerType !== "mouse") setHover(null); }}
           onPointerCancel={() => setHover(null)}
           onKeyDown={(e) => {
             if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
               e.preventDefault();
               const d = e.key === "ArrowLeft" ? -1 : 1;
               setHover((h) => Math.min(points.length - 1, Math.max(0, (h ?? points.length - 1) + d)));
             } else if (e.key === "Escape") setHover(null);
           }}>
        <defs>
          <linearGradient id="fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.22} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={0} x2={w} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeDasharray="2 4" />
            <text x={w + 6} y={y(t) + 4} fontSize="10.5" fill="var(--ink-3)" className="num">{fmtAxis(t, mode)}</text>
          </g>
        ))}
        {zeroY != null && <line x1={0} x2={w} y1={zeroY} y2={zeroY} stroke="var(--ink-3)" strokeWidth={0.8} />}
        {!compare && <path d={area} fill="url(#fill)" />}
        {maPath && <path d={maPath} fill="none" stroke="var(--medium)" strokeWidth={1.4} strokeDasharray="4 3" />}
        {bench && <path d={bench} fill="none" stroke="var(--ink-3)" strokeWidth={1.5} />}
        <path d={line} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />

        {/* volume */}
        {points.map((p, i) => (
          <rect key={p.date} x={x(i) - barW / 2} width={barW}
                y={H_PRICE + GAP + H_VOL - (p.volume / vmax) * H_VOL} height={(p.volume / vmax) * H_VOL}
                fill={i === hover ? "var(--ink-2)" : "var(--line)"} />
        ))}

        {/* filings on the timeline */}
        {showEvents && points.filter((p) => p.events.length).map((p) => (
          <g key={`e${p.date}`} onPointerDown={(ev) => { ev.stopPropagation(); setHover(p.i); }} style={{ cursor: "pointer" }}>
            <line x1={x(p.i)} x2={x(p.i)} y1={y(p.value)} y2={H_PRICE} stroke="var(--high)" strokeDasharray="2 3" strokeOpacity={0.5} />
            <circle cx={x(p.i)} cy={H_PRICE - 1} r={6} fill="var(--surface)" stroke={p.events.some((e) => e.priority === "high") ? "var(--high)" : "var(--medium)"} strokeWidth={2} />
            <text x={x(p.i)} y={H_PRICE + 2.5} fontSize="8" textAnchor="middle" fontWeight="700"
                  fill={p.events.some((e) => e.priority === "high") ? "var(--high)" : "var(--medium)"}>F</text>
          </g>
        ))}

        {xLabels.map((i, k) => (
          <text key={k} x={x(i)} y={totalH - 3} fontSize="10.5" fill="var(--ink-3)"
                textAnchor={k === 0 ? "start" : k === 2 ? "end" : "middle"}>{fmtDate(points[i].date, points.length)}</text>
        ))}

        {active && (
          <g pointerEvents="none">
            <line x1={x(active.i)} x2={x(active.i)} y1={PAD_T} y2={H_PRICE + GAP + H_VOL} stroke="var(--ink)" strokeWidth={0.8} />
            <circle cx={x(active.i)} cy={y(active.value)} r={4.5} fill={color} stroke="var(--surface)" strokeWidth={2} />
            {compare && active.bench != null && <circle cx={x(active.i)} cy={y(active.bench)} r={3.5} fill="var(--ink-3)" />}
          </g>
        )}
      </svg>
    </div>
  );
}
