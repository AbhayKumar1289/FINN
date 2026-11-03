"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Masthead from "@/components/Masthead";
import { Loading } from "@/components/Status";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";

type Ready = { symbol: string; name?: string; sector?: string | null; documents?: number; status: string;
  record?: Partial<Record<"met" | "exceeded" | "missed" | "on_track" | "behind", number>> };
const RECORD: [keyof NonNullable<Ready["record"]>, string, string][] = [
  ["met", "met", "up"], ["exceeded", "beat", "up"], ["missed", "missed", "down"], ["on_track", "on track", "ink2"], ["behind", "behind", "down"],
];
type Hit = { symbol: string; name: string };

const DocIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
    <path d="M7 3h8l4 4v14H7zM14.5 3v4.5H19M10 12h6M10 15.5h6" />
  </svg>
);

export default function ResearchIndex() {
  const router = useRouter();
  const { data: ready, reload } = useApi<Ready[]>("/api/research", 15_000);
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
      <Masthead />
      <header className="topbar">
        <h1 className="display">Read deeper.</h1>
        <p className="dek">Answers from the company&apos;s own words.</p>
      </header>

      <form className="search" style={{ marginTop: 18 }} role="search"
            onSubmit={(e) => { e.preventDefault(); if (hits[0]) router.push(`/research/${encodeURIComponent(hits[0].symbol)}`); }}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM20 20l-4-4" /></svg>
        <input placeholder="Company or NSE symbol" value={q} onChange={(e) => setQ(e.target.value)}
               aria-label="Search any NSE company" autoComplete="off" />
      </form>
      {hits.length > 0 && (
        <div className="card" style={{ marginTop: 8 }} role="listbox" aria-label="Matching companies">
          {hits.map((h, i) => (
            <Link key={h.symbol} href={`/research/${encodeURIComponent(h.symbol)}`} className="between" role="option" aria-selected={i === 0}
                  style={{ padding: "12px 14px", borderTop: i ? "1px solid var(--line)" : undefined }}>
              <span className="truncate"><span className="ticker">{h.symbol}</span> <span className="muted small">{h.name}</span></span>
              <span className="muted" aria-hidden>›</span>
            </Link>
          ))}
        </div>
      )}
      {q.trim().length > 1 && found.length === 0 && (
        <p className="small muted" style={{ marginTop: 10 }}>No NSE company matches “{q}”.</p>
      )}

      <section className="section">
        <div className="section-head">
          <span className="caps" style={{ color: "var(--ink)" }}>Your research shelf</span>
          <span className="caps num" style={{ color: "var(--ink)" }}>{ready ? String(ready.length).padStart(2, "0") : ""}</span>
        </div>
        {!ready && <Loading label="Loading your shelf…" heights={[56, 56, 56]} onRetry={reload} />}
        {ready?.length === 0 && <div className="empty">Search for any NSE company and FINN will read its transcripts and annual report.</div>}
        {ready && ready.length > 0 && (
          <div className="shelf">
            {ready.map((r, i) => (
              <Link key={r.symbol} href={`/research/${encodeURIComponent(r.symbol)}`}>
                <span className="idx">{String(i + 1).padStart(2, "0")}</span>
                <span style={{ minWidth: 0 }}>
                  <span className="ticker" style={{ display: "block" }}>{r.symbol}</span>
                  <span className="small muted truncate" style={{ display: "block" }}>{r.name ?? ""}</span>
                  {r.record && Object.keys(r.record).length > 0 && (
                    <span className="tiny num" style={{ display: "block", marginTop: 2 }}>
                      {RECORD.filter(([k]) => r.record?.[k]).map(([k, label, tone], j) => (
                        <span key={k} className={tone}>{j > 0 && <span className="muted"> · </span>}{r.record![k]} {label}</span>
                      ))}
                    </span>
                  )}
                </span>
                <span className="row small muted">
                  {r.status === "preparing" ? "Reading…" : <><DocIcon /> {r.documents} doc{r.documents === 1 ? "" : "s"}</>}
                </span>
                <span className="muted" aria-hidden>›</span>
              </Link>
            ))}
          </div>
        )}
      </section>

      <div className="note">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden style={{ flex: "none", marginTop: 2 }}>
          <path d="m15.5 7.5-6.8 6.8a2 2 0 0 0 2.8 2.8l7.4-7.4a4 4 0 0 0-5.7-5.7l-7.4 7.4a6 6 0 0 0 8.5 8.5l6.2-6.2" />
        </svg>
        <div>
          <div className="t">Primary sources only.</div>
          <p className="small ink2" style={{ marginTop: 2 }}>Annual reports &amp; earnings calls. Every answer traces back to the document.</p>
        </div>
      </div>
    </>
  );
}
