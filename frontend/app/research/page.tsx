"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";

type Ready = { symbol: string; name?: string; sector?: string | null; documents?: number; status: string };
type Hit = { symbol: string; name: string };

export default function ResearchIndex() {
  const router = useRouter();
  const { data: ready } = useApi<Ready[]>("/api/research", 15_000);
  const [q, setQ] = useState("");
  const [found, setHits] = useState<Hit[]>([]);
  const hits = q.trim() ? found : [];

  useEffect(() => {
    if (!q.trim()) return;
    const t = setTimeout(() => {
      api<Hit[]>(`/api/symbols/search?q=${encodeURIComponent(q)}`).then(setHits).catch(() => setHits([]));
    }, 180);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <>
      <header className="topbar">
        <div className="caps">Pull</div>
        <h1>Research</h1>
        <p className="sub">Any NSE company, read from its own annual reports and concall transcripts. No news, no broker notes.</p>
      </header>

      <form onSubmit={(e) => { e.preventDefault(); if (hits[0]) router.push(`/research/${encodeURIComponent(hits[0].symbol)}`); }}>
        <input className="input" placeholder="Search a company or NSE symbol" value={q} autoFocus
               onChange={(e) => setQ(e.target.value)} aria-label="Search companies" />
      </form>
      {hits.length > 0 && (
        <div className="card" style={{ marginTop: 8 }}>
          {hits.map((h, i) => (
            <Link key={h.symbol} href={`/research/${encodeURIComponent(h.symbol)}`} className="between"
                  style={{ padding: "11px 14px", borderTop: i ? "1px solid var(--line)" : undefined }}>
              <span className="truncate"><span className="mono" style={{ fontWeight: 650 }}>{h.symbol}</span> <span className="muted small">{h.name}</span></span>
              <span className="muted">›</span>
            </Link>
          ))}
        </div>
      )}

      <section className="section">
        <div className="section-head"><span className="caps">Ready to ask</span></div>
        {!ready && <div className="skeleton" style={{ height: 140 }} />}
        {ready?.length === 0 && <div className="empty">Search for a company to have FINN read its documents.</div>}
        <div className="stack">
          {ready?.map((r) => (
            <Link key={r.symbol} href={`/research/${encodeURIComponent(r.symbol)}`} className="card between" style={{ padding: "13px 16px" }}>
              <div className="grow">
                <div className="row"><span className="mono" style={{ fontWeight: 650 }}>{r.symbol}</span>
                  {r.status === "preparing" && <span className="chip">Reading…</span>}</div>
                <div className="tiny muted truncate">{r.name ?? ""}{r.documents ? ` · ${r.documents} documents read` : ""}</div>
              </div>
              <span className="muted">›</span>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
}
