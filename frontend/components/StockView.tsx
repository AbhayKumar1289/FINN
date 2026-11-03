"use client";

import Link from "next/link";
import { use, useCallback, useMemo, useState } from "react";
import Masthead from "./Masthead";
import StockChart, { type Bar, type ChartEvent, type Point } from "./StockChart";
import { Failure, Loading } from "./Status";
import { pct, price, tone } from "@/lib/format";
import { useApi } from "@/lib/useApi";

type ChartData = {
  symbol: string; name: string; sector: string | null; as_of: string;
  rows: (Bar & { high: number; low: number })[];
  events: (ChartEvent & { category: string })[];
  benchmark: { symbol: string; name: string; rows: { date: string; adj_close: number }[] };
  week52: { high: number; low: number };
};

const RANGES = [["1W", 5], ["1M", 21], ["3M", 63], ["6M", 126], ["1Y", 252]] as const;
const MAS = [[null, "Off"], [20, "20D"], [50, "50D"]] as const;

function longDate(d: string) {
  return new Date(d + "T12:00:00+05:30").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}
function compactVol(v: number) {
  return v >= 1e7 ? `${(v / 1e7).toFixed(2)} cr` : v >= 1e5 ? `${(v / 1e5).toFixed(1)} L` : v.toLocaleString("en-IN");
}

export default function StockView({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol: raw } = use(params);
  const symbol = decodeURIComponent(raw).toUpperCase();
  const { data, error, reload } = useApi<ChartData>(`/api/companies/${encodeURIComponent(symbol)}/chart?days=400`);
  const [range, setRange] = useState<(typeof RANGES)[number][0]>("3M");
  const [compare, setCompare] = useState(false);
  const [ma, setMa] = useState<number | null>(null);
  const [showEvents, setShowEvents] = useState(true);
  const [scrub, setScrub] = useState<{ p: Point | null; all: Point[] }>({ p: null, all: [] });
  const onScrub = useCallback((p: Point | null, all: Point[]) => setScrub({ p, all }), []);

  const sessions = RANGES.find(([r]) => r === range)![1];
  const stats = useMemo(() => {
    if (!data) return null;
    const view = data.rows.slice(-sessions);
    const first = view[0], last = view[view.length - 1];
    const ret = (last.adj_close / first.adj_close - 1) * 100;
    const bmap = new Map(data.benchmark.rows.map((b) => [b.date, b.adj_close]));
    // first/last days both series traded (index and stock calendars can differ by a holiday)
    const common = view.filter((r) => bmap.has(r.date));
    const b0 = common.length ? bmap.get(common[0].date) : undefined;
    const b1 = common.length ? bmap.get(common[common.length - 1].date) : undefined;
    const bret = b0 && b1 ? (b1 / b0 - 1) * 100 : null;
    const daily = view.slice(1).map((r, i) => Math.abs(r.adj_close / view[i].adj_close - 1) * 100).sort((a, b) => a - b);
    const typical = daily.length ? daily[Math.floor(daily.length / 2)] : null;
    const avgVol = view.reduce((s, r) => s + r.volume, 0) / view.length;
    return {
      ret, bret, excess: bret != null ? ret - bret : null,
      high: Math.max(...view.map((r) => r.high)), low: Math.min(...view.map((r) => r.low)),
      fromHigh52: (last.close / data.week52.high - 1) * 100,
      typical, avgVol, lastVol: last.volume,
      events: data.events.filter((e) => e.date >= first.date),
      first, last,
    };
  }, [data, sessions]);

  if (error && !data) {
    return <><Masthead /><Failure message={error} onRetry={reload}><Link href="/portfolio" className="btn secondary small">Portfolio</Link></Failure></>;
  }
  if (!data || !stats) return <><Masthead /><Loading label={`Loading ${symbol}…`} heights={[60, 270, 120]} onRetry={reload} /></>;

  // header follows the finger: scrubbed day, or the latest close
  const p = scrub.p;
  const shownPrice = p ? p.close : stats.last.close;
  const shownPct = p ? p.pct : stats.ret;
  const shownBench = p ? p.bench : stats.bret;
  const firstClose = stats.first.close;
  const absChange = shownPrice - firstClose; // traded rupees vs the range start; % uses adjusted closes
  const headerDate = p ? longDate(p.date) : `${range} · close ${longDate(data.as_of)}`;
  const scrubEvents = p?.events ?? [];

  return (
    <>
      <Masthead />
      <Link href="/portfolio" className="back">‹ Portfolio</Link>
      <header className="topbar" style={{ paddingTop: 10 }}>
        <div className="row"><span className="ticker">{data.symbol}</span>{data.sector && <span className="chip">{data.sector}</span>}</div>
        <h1 className="headline" style={{ marginTop: 4 }}>{data.name}</h1>
        <div className="quote" aria-live="polite">
          <span className="display num" style={{ fontSize: 40 }}>{compare ? pct(shownPct) : price(shownPrice)}</span>
          {compare ? (
            <div className="small num" style={{ fontWeight: 600 }}>
              <span className="muted" style={{ fontWeight: 500 }}>NIFTY 50 {shownBench != null ? pct(shownBench) : "–"}</span>
              {shownBench != null && (
                <span className={tone(shownPct - shownBench)}>
                  {" · "}{shownPct >= shownBench ? "ahead by" : "behind by"} {Math.abs(shownPct - shownBench).toFixed(1)} pts
                </span>
              )}
            </div>
          ) : (
            <div className={`small num ${tone(shownPct)}`} style={{ fontWeight: 600 }}>
              {absChange >= 0 ? "+" : "−"}₹{Math.abs(absChange).toFixed(2)} ({pct(shownPct)})
            </div>
          )}
          <div className="tiny muted">{headerDate}</div>
        </div>
      </header>

      <div className="seg" role="group" aria-label="Range" style={{ marginTop: 6 }}>
        {RANGES.map(([r]) => <button key={r} aria-pressed={range === r} onClick={() => setRange(r)}>{r}</button>)}
      </div>

      {compare && (
        <div className="legend tiny" style={{ marginTop: 12, marginBottom: 0 }} aria-hidden>
          <span><span className="sw-line" style={{ background: stats.ret >= 0 ? "var(--up)" : "var(--down)", height: 3 }} /> {data.symbol}</span>
          <span><span className="sw-line" style={{ background: "var(--ink-3)", height: 3 }} /> NIFTY 50</span>
        </div>
      )}
      <div style={{ marginTop: compare ? 4 : 14 }}>
        <StockChart history={data.rows} sessions={sessions} benchmark={data.benchmark.rows} events={data.events}
                    compare={compare} maWindow={ma} showEvents={showEvents} onScrub={onScrub}
                    label={`${data.symbol} price, last ${range}: ${pct(stats.ret)}`} />
      </div>

      {scrubEvents.length > 0 && (
        <div className="callout" style={{ marginTop: 10 }}>
          {scrubEvents.map((e) => (
            <p key={e.id} className="small" style={{ marginTop: 0 }}>
              <b>Filing:</b> {e.headline}{e.url && <> · <a className="link" href={e.url} target="_blank" rel="noreferrer">open ↗</a></>}
            </p>
          ))}
        </div>
      )}

      <div className="chart-tools" role="group" aria-label="Chart options">
        <button className="toggle" aria-pressed={compare} onClick={() => setCompare((v) => !v)}>
          <span className="sw-line" style={{ background: "var(--ink-3)" }} aria-hidden /> vs NIFTY 50
        </button>
        <span className="row" style={{ gap: 4 }} role="group" aria-label="Moving average">
          <span className="tiny muted" style={{ marginRight: 2 }}>Avg</span>
          {MAS.map(([w, l]) => (
            <button key={l} className="toggle" aria-pressed={ma === w} disabled={compare && w != null}
                    onClick={() => setMa(w)}>{l}</button>
          ))}
        </span>
        <button className="toggle" aria-pressed={showEvents} onClick={() => setShowEvents((v) => !v)}>
          <span className="f-dot" aria-hidden>F</span> Filings
        </button>
      </div>
      <p className="tiny muted" style={{ marginTop: 6 }}>
        Touch and drag the chart to read any day. {compare ? "Both lines show % change from the start of the range." : ma ? `Dashed line: ${ma}-day average close.` : ""}
      </p>

      <section className="section">
        <div className="caps" style={{ color: "var(--ink)" }}>{range} at a glance</div>
        <div className="stat-grid num">
          <div><span className="k">Return</span><span className={`v ${tone(stats.ret)}`}>{pct(stats.ret)}</span></div>
          <div><span className="k">vs NIFTY 50</span>
            <span className={`v ${tone(stats.excess)}`}>{stats.excess == null ? "–" : `${stats.excess >= 0 ? "+" : "−"}${Math.abs(stats.excess).toFixed(1)} pts`}</span></div>
          <div><span className="k">Range high / low</span><span className="v">{price(stats.high).replace(".00", "")} / {price(stats.low).replace(".00", "")}</span></div>
          <div><span className="k">From 52-week high</span><span className={`v ${tone(stats.fromHigh52)}`}>{pct(stats.fromHigh52)}</span></div>
          <div><span className="k">Typical daily move</span><span className="v">{stats.typical != null ? `±${stats.typical.toFixed(1)}%` : "–"}</span></div>
          <div><span className="k">Avg daily volume</span><span className="v">{compactVol(stats.avgVol)}
            <span className="tiny muted"> · last {(stats.lastVol / stats.avgVol).toFixed(1)}×</span></span></div>
        </div>
      </section>

      {stats.events.length > 0 && (
        <section className="section">
          <div className="caps" style={{ color: "var(--ink)" }}>Filings in this range</div>
          <div style={{ borderTop: "1.5px solid var(--rule)" }}>
            {[...stats.events].reverse().map((e) => (
              <div key={e.id} className="between" style={{ padding: "11px 0", borderBottom: "1px solid var(--line)" }}>
                <span className="small"><span className={`dot ${e.priority}`} style={{ marginRight: 8 }} aria-hidden />{e.headline}</span>
                <span className="tiny muted" style={{ flex: "none" }}>{new Date(e.date + "T12:00:00+05:30").toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="stack section">
        <Link href={`/research/${encodeURIComponent(data.symbol)}`} className="btn block">Research {data.name} →</Link>
        <Link href="/alerts" className="btn secondary block">Alerts and thresholds</Link>
      </div>
      <p className="tiny muted" style={{ marginTop: 12 }}>
        End-of-day prices (NSE close via Yahoo Finance), never live; as of {longDate(data.as_of)}. Returns and comparisons use
        split- and dividend-adjusted closes. NIFTY 50 is the benchmark.
      </p>
    </>
  );
}
