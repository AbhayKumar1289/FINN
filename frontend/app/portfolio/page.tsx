"use client";

import Link from "next/link";
import { useState } from "react";
import Masthead from "@/components/Masthead";
import Sparkline from "@/components/Sparkline";
import { Failure, Loading } from "@/components/Status";
import { api, type Holding } from "@/lib/api";
import { ago, change, dayIST, pct, price, tone } from "@/lib/format";
import { useApi } from "@/lib/useApi";

type Sort = "move" | "volume" | "name";
const SORTS: [Sort, string][] = [["move", "Biggest move"], ["volume", "Volume"], ["name", "A – Z"]];

export default function PortfolioPage() {
  const { data, error, reload } = useApi<Holding[]>("/api/portfolio");
  const [sort, setSort] = useState<Sort>("move");
  const [adding, setAdding] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);

  const rows = [...(data ?? [])].sort((a, b) => {
    const ma = a.market.available ? a.market : null;
    const mb = b.market.available ? b.market : null;
    if (sort === "name") return a.name.localeCompare(b.name);
    if (sort === "volume") return (mb?.relative_volume ?? 0) - (ma?.relative_volume ?? 0);
    return Math.abs(mb?.day_change_pct.value ?? 0) - Math.abs(ma?.day_change_pct.value ?? 0);
  });
  const asOf = data?.find((h) => h.market.available)?.market;

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setAddError(null);
    try {
      await api("/api/portfolio", { method: "POST", body: JSON.stringify({ symbol: adding }) });
      setAdding("");
      reload();
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Could not add");
    } finally {
      setBusy(false);
    }
  }

  async function remove(symbol: string) {
    await api(`/api/portfolio/${encodeURIComponent(symbol)}`, { method: "DELETE" });
    reload();
  }

  return (
    <>
      <Masthead />
      <div style={{ textAlign: "right", marginTop: 10 }}>
        <button className="link small" onClick={() => setEditing((v) => !v)} aria-pressed={editing}>{editing ? "Done" : "Edit"}</button>
      </div>
      <header className="topbar" style={{ paddingTop: 6 }}>
        <h1 className="display">Your companies.</h1>
        <p className="dek num">
          {data ? `${data.length} companies` : " "}
          {asOf && asOf.available && ` · ${dayIST(asOf.as_of)} close`}
        </p>
      </header>

      <div className="tabs" role="group" aria-label="Sort by" style={{ marginTop: 14 }}>
        {SORTS.map(([s, label]) => (
          <button key={s} aria-pressed={sort === s} onClick={() => setSort(s)}>{label}</button>
        ))}
      </div>

      {error && !data && <Failure message={error} onRetry={reload} />}
      {!data && !error && <Loading label="Loading prices…" heights={[56, 56, 56, 56]} onRetry={reload} />}
      <div>
        {rows.map((h) => {
          const m = h.market.available ? h.market : null;
          return (
            <div key={h.symbol} className="holding">
              <Link href={`/stock/${encodeURIComponent(h.symbol)}`} className="grow" style={{ minWidth: 0 }}
                    aria-label={`${h.symbol}, ${h.name}: open chart`}>
                <div className="row">
                  <span className="ticker">{h.symbol}</span>
                </div>
                <div className="small muted truncate row" style={{ gap: 6 }}>
                  {h.sector ?? h.name}
                  {m?.relative_volume != null && m.relative_volume >= 2 && <span className="rvol num">{m.relative_volume}× vol</span>}
                </div>
                {h.latest_filing && (
                  <div className="tiny ink2 truncate" style={{ marginTop: 3 }}>
                    <span className={`dot ${h.latest_filing.priority}`} style={{ marginRight: 5 }} aria-hidden />
                    {h.latest_filing.headline} · {ago(h.latest_filing.published_at)}
                  </div>
                )}
              </Link>
              {editing ? (
                <button className="btn secondary small" style={{ color: "var(--down)" }}
                        onClick={() => remove(h.symbol)} aria-label={`Remove ${h.symbol}`}>Remove</button>
              ) : (
                <Link href={`/stock/${encodeURIComponent(h.symbol)}`} aria-label={`${h.symbol} 30-day chart`} className="spark-link">
                  <Sparkline values={h.spark ?? []} width={76} height={28} />
                  {h.spark && h.spark.length > 1 && (
                    <span className={`tiny num ${tone(h.spark[h.spark.length - 1] - h.spark[0])}`}>
                      30d {pct((h.spark[h.spark.length - 1] / h.spark[0] - 1) * 100)}
                    </span>
                  )}
                </Link>
              )}
              <div style={{ textAlign: "right" }}>
                <div className="num" style={{ fontWeight: 550 }}>{m ? price(m.close) : "–"}</div>
                <div className={`num small ${tone(m?.day_change_pct.value)}`} style={{ fontWeight: 550 }}>
                  {m ? change(m.day_change_pct) : "no data"}
                </div>
                {!!h.unread_alerts && (
                  <Link href="/alerts" className="tiny link" aria-label={`${h.unread_alerts} unread alerts for ${h.symbol}`}>
                    {h.unread_alerts} alert{h.unread_alerts === 1 ? "" : "s"}
                  </Link>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <form className="section" onSubmit={add}>
        <label className="caps" htmlFor="add-symbol" style={{ display: "block", marginBottom: 8 }}>Add an NSE company</label>
        <div className="composer">
          <input id="add-symbol" className="input mono" placeholder="e.g. TITAN" value={adding} maxLength={20}
                 onChange={(e) => setAdding(e.target.value.toUpperCase())} />
          <button className="btn" disabled={busy || !adding.trim()}>{busy ? "Adding…" : "Add"}</button>
        </div>
        {addError && <div className="error" role="alert" style={{ marginTop: 8 }}>{addError}</div>}
        <p className="tiny muted" style={{ marginTop: 8 }}>FINN starts watching its filings and prices right away.</p>
      </form>
    </>
  );
}
