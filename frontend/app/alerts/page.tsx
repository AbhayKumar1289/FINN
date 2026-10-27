"use client";

import { useState } from "react";
import { api, type Alert, type Rule } from "@/lib/api";
import { ago } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const CATEGORY_LABELS: Record<string, string> = {
  results: "Results", management_change: "Management change", m_and_a: "M&A", fund_raise: "Fund raise",
  litigation: "Legal / regulatory", credit_rating: "Credit rating", pledging: "Promoter pledge",
  "press_release:order_win": "Order wins", dividend: "Dividend", bonus_split: "Bonus / split", capex: "Capex",
  insider_trading: "Insider trades", earnings_call: "Earnings calls",
};
const ICON: Record<Alert["rule"], string> = { price_move: "±", volume_spike: "▮▮", announcement_category: "§" };

export default function AlertsPage() {
  const { data: alerts, reload, setData } = useApi<Alert[]>("/api/alerts?limit=100");
  const { data: rulesResp, reload: reloadRules } = useApi<{ rules: Rule[] }>("/api/alert-rules");
  const rules = Object.fromEntries((rulesResp?.rules ?? []).map((r) => [r.rule_type, r])) as Record<Rule["rule_type"], Rule>;

  async function markSeen(a: Alert) {
    if (a.seen) return;
    setData((list) => list?.map((x) => (x.id === a.id ? { ...x, seen: true } : x)) ?? null);
    await api(`/api/alerts/${a.id}/seen`, { method: "POST" });
  }

  async function save(rule: Rule["rule_type"], body: object) {
    await api(`/api/alert-rules/${rule}`, { method: "PUT", body: JSON.stringify(body) });
    reloadRules();
    reload();
  }

  const unseen = alerts?.filter((a) => !a.seen).length ?? 0;

  return (
    <>
      <header className="topbar">
        <div className="caps">Push</div>
        <h1>Alerts</h1>
        <p className="sub">FINN watches end-of-day prices and every filing. You decide what counts as unusual.</p>
      </header>

      <section className="section">
        <div className="section-head">
          <span className="caps">{unseen ? `${unseen} new` : "All caught up"}</span>
          {unseen > 0 && (
            <button className="tiny link" onClick={async () => { await api("/api/alerts/seen-all", { method: "POST" }); reload(); }}>
              Mark all read
            </button>
          )}
        </div>
        <div className="card">
          {!alerts && <div className="skeleton" style={{ height: 160 }} />}
          {alerts?.length === 0 && <div className="empty">No alerts yet.</div>}
          {alerts?.map((a, i) => (
            <button key={a.id} className={`alert-item ${a.seen ? "" : "unseen"}`} onClick={() => markSeen(a)}
                    style={{ width: "100%", textAlign: "left", borderTop: i ? "1px solid var(--line)" : undefined }}>
              <span className="alert-icon tiny mono" aria-hidden>{ICON[a.rule]}</span>
              <span className="grow">
                <span className="small" style={{ fontWeight: a.seen ? 450 : 600, display: "block" }}>{a.message}</span>
                <span className="tiny muted">
                  {a.rule === "announcement_category" ? "Filing" : "End-of-day"} · {a.as_of ?? ""} · {ago(a.triggered_at)}
                  {a.source?.url && <> · <a className="link" href={a.source.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>filing</a></>}
                </span>
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="section">
        <div className="section-head"><span className="caps">What counts as unusual</span></div>
        <div className="card">
          {rules.price_move && (
            <Threshold key={`p${rules.price_move.threshold}`} rule={rules.price_move} label="Daily price move" min={1} max={15} step={0.5}
                       fmt={(v) => `±${v}%`} hint="Split- and dividend-adjusted close vs previous close"
                       onSave={(body) => save("price_move", body)} />
          )}
          {rules.volume_spike && (
            <div style={{ borderTop: "1px solid var(--line)" }}>
              <Threshold key={`v${rules.volume_spike.threshold}`} rule={rules.volume_spike} label="Volume spike" min={1.2} max={6} step={0.1}
                         fmt={(v) => `${v.toFixed(1)}× average`} hint={`vs the previous ${rules.volume_spike.config.lookback ?? 20} sessions`}
                         onSave={(body) => save("volume_spike", body)} />
            </div>
          )}
          {rules.announcement_category && (
            <div style={{ borderTop: "1px solid var(--line)" }}>
              <div className="slider-row between">
                <div>
                  <div style={{ fontWeight: 600 }}>Filings that alert me</div>
                  <div className="tiny muted">Routine paperwork never alerts, whatever its type</div>
                </div>
                <Switch on={rules.announcement_category.enabled} onChange={(v) => save("announcement_category", { enabled: v })} />
              </div>
              <div className="toggle-grid">
                {Object.entries(CATEGORY_LABELS).map(([key, label]) => {
                  const cats = rules.announcement_category.config.categories ?? [];
                  const on = cats.includes(key);
                  return (
                    <button key={key} className="toggle" aria-pressed={on}
                            onClick={() => save("announcement_category", { categories: on ? cats.filter((c) => c !== key) : [...cats, key] })}>
                      {label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
        <p className="tiny muted" style={{ margin: "10px 4px" }}>
          Data is end-of-day (NSE close, via Yahoo Finance), never live. Changes apply to the latest session straight away.
        </p>
      </section>
    </>
  );
}

function Threshold({ rule, label, min, max, step, fmt, hint, onSave }: {
  rule: Rule; label: string; min: number; max: number; step: number;
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
        <div className="row">
          <span className="num" style={{ fontWeight: 650 }}>{fmt(v)}</span>
          <Switch on={rule.enabled} onChange={(on) => onSave({ enabled: on })} />
        </div>
      </div>
      <input type="range" min={min} max={max} step={step} value={v} disabled={!rule.enabled}
             aria-label={label} onChange={(e) => setV(Number(e.target.value))}
             onPointerUp={commit} onKeyUp={commit} onBlur={commit} />
    </div>
  );
}

function Switch({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button role="switch" aria-checked={on} onClick={() => onChange(!on)}
            style={{ width: 40, height: 24, borderRadius: 12, padding: 2, flex: "none",
                     background: on ? "var(--accent)" : "var(--line)", transition: "background .15s" }}>
      <span style={{ display: "block", width: 20, height: 20, borderRadius: 10, background: "#fff",
                     transform: `translateX(${on ? 16 : 0}px)`, transition: "transform .15s" }} />
    </button>
  );
}
