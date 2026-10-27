"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, type Answer, type Research } from "@/lib/api";

type Turn = { q: string; a?: Answer; error?: string };

const SUGGESTIONS: Record<string, string[]> = {
  results: ["Is this quarter in line with guidance?", "What drove the margin change?", "What did management say about demand?"],
  management_change: ["What has management said about leadership and succession?", "What strategy has the current team laid out?"],
  press_release: ["How big is the order book?", "What is management's order inflow guidance?"],
  m_and_a: ["What has management said about acquisitions?", "How is the company funding growth?"],
  default: ["What is management's outlook?", "What risks has management flagged?", "What is the capex plan?"],
};

/** Pull, opened from Push: a research thread already scoped to the event on the card. */
export default function AskSheet({ symbol, name, announcementId, category, onClose }: {
  symbol: string;
  name: string;
  announcementId?: number;
  category?: string;
  onClose: () => void;
}) {
  const [status, setStatus] = useState<Research["status"] | "checking">("checking");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const suggestions = SUGGESTIONS[category ?? ""] ?? SUGGESTIONS.default;

  useEffect(() => {
    let stop = false;
    const check = async () => {
      try {
        const r = await api<Research>(`/api/research/${encodeURIComponent(symbol)}?narrative=false`);
        if (stop) return;
        setStatus(r.status);
        if (r.status === "preparing") setTimeout(check, 4000);
      } catch {
        if (!stop) setStatus("not_started");
      }
    };
    check();
    return () => { stop = true; };
  }, [symbol]);

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [turns]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function prepare() {
    setStatus("preparing");
    await api(`/api/research/${encodeURIComponent(symbol)}/prepare`, { method: "POST" });
    const poll = async () => {
      const r = await api<Research>(`/api/research/${encodeURIComponent(symbol)}?narrative=false`);
      setStatus(r.status);
      if (r.status !== "ready") setTimeout(poll, 4000);
    };
    setTimeout(poll, 4000);
  }

  async function send(question: string) {
    const text = question.trim();
    if (!text || busy) return;
    setQ("");
    setBusy(true);
    setTurns((t) => [...t, { q: text }]);
    try {
      const a = await api<Answer>(`/api/research/${encodeURIComponent(symbol)}/ask`, {
        method: "POST", body: JSON.stringify({ question: text, announcement_id: announcementId ?? null }),
      });
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, a } : x)));
    } catch (e) {
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error: e instanceof Error ? e.message : "Failed" } : x)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <section className="sheet" role="dialog" aria-label={`Ask about ${name}`}>
        <div className="grip" />
        <div className="between">
          <div>
            <div className="caps">Ask FINN · from transcripts & annual reports</div>
            <div style={{ fontWeight: 650, fontSize: 17, marginTop: 2 }}>{name}</div>
          </div>
          <Link href={`/research/${encodeURIComponent(symbol)}`} className="link small" onClick={onClose}>Full research →</Link>
        </div>

        <div className="thread">
          {status === "checking" && <div className="skeleton" style={{ height: 60 }} />}
          {status === "not_started" && (
            <div className="card" style={{ padding: 14 }}>
              <p className="small ink2">FINN hasn&apos;t read {name}&apos;s concall transcripts and annual report yet.
                It takes about a minute, then every answer cites its source.</p>
              <button className="btn accent small" style={{ marginTop: 10 }} onClick={prepare}>Read the documents</button>
            </div>
          )}
          {status === "preparing" && (
            <div className="card small ink2" style={{ padding: 14 }}>Reading transcripts and the annual report… you can keep browsing.</div>
          )}
          {turns.map((t, i) => (
            <div key={i} className="stack">
              <div className="bubble-q">{t.q}</div>
              {t.error && <div className="error">{t.error}</div>}
              {!t.a && !t.error && <div className="skeleton" style={{ height: 72 }} />}
              {t.a && (
                <div className="bubble-a">
                  <p className={t.a.found ? "" : "ink2"}>{renumber(t.a)}</p>
                  {t.a.sources.length > 0 && (
                    <div className="cites">
                      {t.a.sources.map((s) => (
                        <a key={s.n} className="cite" href={s.url ?? undefined} target="_blank" rel="noreferrer">
                          <b>[{t.a!.sources.indexOf(s) + 1}] {s.title}{s.page ? `, ${String(s.page).startsWith("p.") ? s.page : `p.${s.page}`}` : ""}</b>
                          {s.kind === "finn_fact" ? " · computed by FINN from the filings" : ""}
                          <div className="truncate" style={{ marginTop: 2 }}>{s.excerpt}</div>
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
          <div ref={end} />
        </div>

        {status === "ready" && (
          <>
            {turns.length === 0 && (
              <div className="suggest">
                {suggestions.map((s) => <button key={s} onClick={() => send(s)}>{s}</button>)}
              </div>
            )}
            <form className="composer" onSubmit={(e) => { e.preventDefault(); send(q); }}>
              <input className="input" value={q} onChange={(e) => setQ(e.target.value)}
                     placeholder={`Ask about ${name}…`} aria-label="Question" maxLength={500} />
              <button className="btn" disabled={busy || q.trim().length < 3}>Ask</button>
            </form>
          </>
        )}
      </section>
    </>
  );
}

/** Show citations as [1], [2]… in the order sources are listed, whatever the backend numbered them. */
function renumber(a: Answer): string {
  const order = new Map(a.sources.map((s, i) => [s.n, i + 1]));
  return a.answer.replace(/\[(\d+)\]/g, (m, n) => (order.has(Number(n)) ? `[${order.get(Number(n))}]` : ""));
}
