"use client";

import Link from "next/link";
import { useState } from "react";
import Sparkline from "@/components/Sparkline";
import { api, type Holding } from "@/lib/api";
import { change, dayIST, price, tone } from "@/lib/format";
import { useApi } from "@/lib/useApi";

type Sort = "move" | "volume" | "name";

export default function PortfolioPage() {
  const { data, error, reload } = useApi<Holding[]>("/api/portfolio");
  const [sort, setSort] = useState<Sort>("move");
  const [adding, setAdding] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
    if (!confirm(`Remove ${symbol} from the portfolio?`)) return;
    await api(`/api/portfolio/${encodeURIComponent(symbol)}`, { method: "DELETE" });
    reload();
  }

  return (
    <>
      <header className="topbar">
        <div className="caps">{asOf && asOf.available ? `End of day · ${dayIST(asOf.as_of)}` : "End of day"}</div>
        <h1>Portfolio</h1>
        <p className="sub">{data ? `${data.length} companies` : " "}</p>
      </header>

      <div className="between">
        <div className="seg" role="group" aria-label="Sort">
          {(["move", "volume", "name"] as Sort[]).map((s) => (
            <button key={s} aria-pressed={sort === s} onClick={() => setSort(s)}>
              {s === "move" ? "Biggest move" : s === "volume" ? "Volume" : "A–Z"}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="error section">{error}</div>}
      <div className="card section">
        {!data && <div className="skeleton" style={{ height: 300 }} />}
        {rows.map((h) => {
          const m = h.market.available ? h.market : null;
          return (
            <div key={h.symbol} className="holding">
              <Link href={`/research/${encodeURIComponent(h.symbol)}`} className="grow" style={{ minWidth: 0 }}>
                <div className="row">
                  <span className="mono" style={{ fontWeight: 650 }}>{h.symbol}</span>
                  {m?.relative_volume != null && m.relative_volume >= 2 && <span className="rvol num">{m.relative_volume}× vol</span>}
                </div>
                <div className="tiny muted truncate">{h.name}{h.sector ? ` · ${h.sector}` : ""}</div>
              </Link>
              <Sparkline values={h.spark ?? []} />
              <div style={{ textAlign: "right" }} onDoubleClick={() => remove(h.symbol)}>
                <div className="num small" style={{ fontWeight: 600 }}>{m ? price(m.close) : "–"}</div>
                <div className={`num small ${tone(m?.day_change_pct.value)}`}>{m ? change(m.day_change_pct) : "no data"}</div>
              </div>
            </div>
          );
        })}
      </div>

      <form className="section" onSubmit={add}>
        <div className="caps" style={{ margin: "0 2px 8px" }}>Add an NSE company</div>
        <div className="composer">
          <input className="input mono" placeholder="e.g. TITAN" value={adding} maxLength={20}
                 onChange={(e) => setAdding(e.target.value.toUpperCase())} aria-label="NSE symbol" />
          <button className="btn" disabled={busy || !adding.trim()}>{busy ? "Adding…" : "Add"}</button>
        </div>
        {addError && <div className="error" style={{ marginTop: 8 }}>{addError}</div>}
        <p className="tiny muted" style={{ margin: "8px 2px" }}>FINN starts watching its filings and prices right away. Double-tap a price to remove.</p>
      </form>
    </>
  );
}
