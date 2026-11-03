"use client";

import { useState } from "react";
import Masthead from "@/components/Masthead";
import { Failure, Loading } from "@/components/Status";
import { api, type Alert, type Rule } from "@/lib/api";
import { useApi } from "@/lib/useApi";

const CATEGORY_LABELS: Record<string, string> = {
  results: "Results", management_change: "Management", m_and_a: "M&A", fund_raise: "Fund raise",
  litigation: "Legal / regulatory", credit_rating: "Credit rating", pledging: "Promoter pledge",
  "press_release:order_win": "Order wins", "press_release:regulatory_approval": "Approvals",
  dividend: "Dividend", bonus_split: "Bonus / split", capex: "Capex",
  insider_trading: "Insider trades", earnings_call: "Earnings calls",
};
const FIRST = 4;

function when(a: Alert): string {
  if (a.rule === "announcement_category") {
    return new Date(a.triggered_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" });
  }
  return a.as_of ? `${new Date(a.as_of + "T12:00:00+05:30").toLocaleDateString("en-IN", { day: "numeric", month: "short" })}, close` : "";
}

export default function AlertsPage() {
  const { data: alerts, error, reload, setData } = useApi<Alert[]>("/api/alerts?limit=100");
  const { data: rulesResp, reload: reloadRules } = useApi<{ rules: Rule[] }>("/api/alert-rules");
  const rules = Object.fromEntries((rulesResp?.rules ?? []).map((r) => [r.rule_type, r])) as Record<Rule["rule_type"], Rule>;
  const [allTypes, setAllTypes] = useState(false);

  async function markSeen(a: Alert) {
    if (a.seen) return;
    setData((list) => list?.map((x) => (x.id === a.id ? { ...x, seen: true } : x)) ?? null);
    await api(`/api/alerts/${a.id}/seen`, { method: "POST" });
    window.dispatchEvent(new Event("finn-alerts"));
  }

  async function save(rule: Rule["rule_type"], body: object) {
    await api(`/api/alert-rules/${rule}`, { method: "PUT", body: JSON.stringify(body) });
    reloadRules();
    reload();
  }

  const unseenList = alerts?.filter((a) => !a.seen) ?? [];
  const unseen = unseenList.length;
  const kinds = [["announcement_category", "filing"], ["volume_spike", "volume"], ["price_move", "price"]]
    .map(([rule, word]) => [unseenList.filter((a) => a.rule === rule).length, word] as const)
    .filter(([n]) => n > 0).map(([n, w]) => `${n} ${w}`).join(" · ");
  const cats = rules.announcement_category?.config.categories ?? [];
  const entries = Object.entries(CATEGORY_LABELS)
    .sort(([a], [b]) => Number(cats.includes(b)) - Number(cats.includes(a)));
  const shown = allTypes ? entries : entries.slice(0, FIRST);

  return (
    <>
      <Masthead />
      <header className="topbar">
        <h1 className="display">Only what matters.</h1>
        <p className="dek">Your rules. FINN keeps watch.</p>
      </header>

      <section className="rules" aria-label="What counts as unusual">
        {rules.price_move && (
          <Threshold key={`p${rules.price_move.threshold}`} rule={rules.price_move} label="Daily price move"
                     min={1} max={10} step={0.5} ticks={["1%", "3%", "5%", "10%"]} fmt={(v) => `±${v}%`}
                     hint="Adjusted close vs previous close" onSave={(body) => save("price_move", body)} />
        )}
        {rules.volume_spike && (
          <Threshold key={`v${rules.volume_spike.threshold}`} rule={rules.volume_spike} label="Volume spike"
                     min={1.5} max={5} step={0.1} ticks={["1.5×", "2.0×", "3.0×", "5.0×"]} fmt={(v) => `${v.toFixed(1)}×`}
                     hint={`vs the previous ${rules.volume_spike.config.lookback ?? 20} sessions`}
                     onSave={(body) => save("volume_spike", body)} />
        )}
        {rules.announcement_category && (
          <div style={{ borderBottom: "1px solid var(--line)" }}>
            <div className="slider-row between" style={{ borderBottom: 0, paddingBottom: 10 }}>
              <div>
                <div style={{ fontWeight: 600 }}>Filings I care about</div>
                <div className="tiny muted">Routine paperwork never alerts, whatever its type</div>
              </div>
              <Switch label="Filing alerts" on={rules.announcement_category.enabled}
                      onChange={(v) => save("announcement_category", { enabled: v })} />
            </div>
            <div className="toggle-grid">
              {shown.map(([key, label]) => {
                const on = cats.includes(key);
                return (
                  <button key={key} className="toggle" aria-pressed={on}
                          onClick={() => save("announcement_category", { categories: on ? cats.filter((c) => c !== key) : [...cats, key] })}>
                    {label}
                  </button>
                );
              })}
              <button className="toggle" aria-expanded={allTypes} onClick={() => setAllTypes((v) => !v)}>
                {allTypes ? "Fewer" : `+${entries.length - FIRST} types`}
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="section" aria-label="Alerts">
        <div className="section-head">
          <span className="eyebrow high">{unseen ? `${unseen} unread` : "All caught up"}
            {kinds && <span className="muted" style={{ fontWeight: 500, letterSpacing: 0, textTransform: "none" }}> · {kinds}</span>}
          </span>
          {unseen > 0 && (
            <button className="link small" onClick={async () => {
              await api("/api/alerts/seen-all", { method: "POST" });
              reload();
              window.dispatchEvent(new Event("finn-alerts"));
            }}>Mark all read</button>
          )}
        </div>
        {!alerts && !error && <Loading label="Loading alerts…" heights={[90, 90]} onRetry={reload} />}
        {!alerts && error && <Failure message={error} onRetry={reload} />}
        {alerts?.length === 0 && (
          <div className="empty">Nothing has crossed your thresholds yet. FINN checks filings every 15 minutes and prices after the close.</div>
        )}
        <div style={{ borderTop: "1px solid var(--line)" }}>
          {alerts?.map((a) => (
            <button key={a.id} className={`alert-item ${a.seen ? "" : "unseen"}`} onClick={() => markSeen(a)}
                    aria-label={`${a.symbol}: ${a.title}${a.seen ? "" : ", unread"}`}>
              <span className="between" style={{ gridColumn: "1 / -1" }}>
                <span className="ticker">{a.symbol}</span>
                <span className="tiny muted num">{when(a)}</span>
              </span>
              {a.rule !== "announcement_category" && <span className="caps" style={{ fontSize: 10.5, gridColumn: "1 / -1" }}>At close</span>}
              <span className="t">{a.title}</span>
              <span className="muted" aria-hidden style={{ gridRow: "span 2", alignSelf: "center" }}>›</span>
              {a.detail && <span className="small ink2">{a.detail}</span>}
              <span className="tiny muted" style={{ gridColumn: "1 / -1" }}>
                {a.rule === "announcement_category" ? "Filing on NSE" : `Your threshold: ${a.rule === "price_move" ? `±${a.threshold}%` : `${a.threshold}×`}`}
                {a.source?.url && <> · <a className="link" href={a.source.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>read filing</a></>}
              </span>
            </button>
          ))}
        </div>
        <p className="tiny muted" style={{ marginTop: 12 }}>ⓘ Price alerts use end-of-day data (NSE close via Yahoo Finance), never live.</p>
      </section>
    </>
  );
}

function Threshold({ rule, label, min, max, step, ticks, fmt, hint, onSave }: {
  rule: Rule; label: string; min: number; max: number; step: number; ticks: string[];
  fmt: (v: number) => string; hint: string; onSave: (body: object) => Promise<void>;
}) {
  const [v, setV] = useState(rule.threshold ?? min);
  const commit = () => v !== rule.threshold && onSave({ threshold: v });
  return (
    <div className="slider-row">
      <div className="between">
        <div>
          <div style={{ fontWeight: 600 }}>{label}</div>
          <div className="tiny muted">{hint}</div>
        </div>
        <div className="row" style={{ gap: 14 }}>
          <span className="value num">{fmt(v)}</span>
          <Switch label={label} on={rule.enabled} onChange={(on) => onSave({ enabled: on })} />
        </div>
      </div>
      <input type="range" min={min} max={max} step={step} value={v} disabled={!rule.enabled}
             aria-label={`${label} threshold`} aria-valuetext={fmt(v)} onChange={(e) => setV(Number(e.target.value))}
             onPointerUp={commit} onKeyUp={commit} onBlur={commit} />
      <div className="ticks num" aria-hidden>{ticks.map((t) => <span key={t}>{t}</span>)}</div>
    </div>
  );
}

function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button role="switch" aria-checked={on} aria-label={`${label} ${on ? "on" : "off"}`} onClick={() => onChange(!on)}
            className="switch" style={{ background: on ? "var(--accent)" : "var(--line)" }}>
      <span style={{ transform: `translateX(${on ? 18 : 0}px)` }} />
    </button>
  );
}
