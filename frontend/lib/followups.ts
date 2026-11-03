"use client";

import { useCallback } from "react";
import type { Card } from "./api";
import { useStored } from "./useApi";

/** A question the investor wants to come back to, linked to the filing that raised it.
 * Kept on this device (like "reviewed"): a personal notebook, not shared state. */
export type FollowUp = {
  id: string;
  announcementId: number;
  symbol: string;
  name: string;
  context: string;          // e.g. "Q2 FY27 results" or the story headline
  note: string;
  sourceUrl: string | null;
  createdAt: string;
  resolvedAt: string | null;
};

export const SUGGESTED_NOTE: Record<string, string> = {
  results: "Will these drivers recur next quarter?",
  management_change: "What will the new leadership change?",
  press_release: "How much does this add to growth?",
  m_and_a: "What is it worth, and how is it funded?",
  litigation: "How much is at stake?",
  credit_rating: "Does this change the cost of funding?",
};

const cr = (v: number) => `₹${Math.round(Math.abs(v)).toLocaleString("en-IN")} cr`;

/** Three questions worth keeping open, predicted from what FINN already knows about the event:
 * for results, the biggest line in the profit bridge, the margin move and the growth rate;
 * for other events, the questions an analyst would ask next. Deterministic, no model call. */
export function suggestFollowUps(card: Card): string[] {
  const out: string[] = [];
  const r = card.results;
  if (r) {
    const b = r.bridge_yoy;
    const pat = r.metrics.pat.yoy.value;
    if (b) {
      const dir = pat != null && pat < 0 ? -1 : 1;
      const [key, v] = Object.entries(b)
        .filter(([k, x]) => k !== "pat" && k !== "operating" && x * dir > 0)
        .sort((a, z) => Math.abs(z[1]) - Math.abs(a[1]))[0] ?? [];
      const q = {
        exceptional: `Will the ${cr(v ?? 0)} one-off charge recur, or was it truly one-off?`,
        other_income: `Why did other income ${dir < 0 ? "fall" : "rise"} ${cr(v ?? 0)}, and will it ${dir < 0 ? "recover" : "last"}?`,
        tax_and_minorities: "Is the higher tax charge here to stay?",
        depreciation: "When will the new capacity start earning its keep?",
        finance_costs: `Will interest costs keep ${dir < 0 ? "rising" : "falling"}?`,
      }[key as string];
      if (q) out.push(q);
    }
    const m = r.margins.ebitda;
    if (m.current_pct != null && m.change_pp != null) {
      out.push(m.change_pp < 0 && m.year_ago_pct != null
        ? `Can the EBITDA margin get back to ${m.year_ago_pct}%?`
        : `Can the ${m.current_pct}% EBITDA margin hold next quarter?`);
    }
    const rev = r.metrics.revenue.yoy.value;
    if (rev != null) out.push(rev >= 0 ? `Can revenue keep growing ${Math.round(rev)}% a year?` : "What will it take for revenue to grow again?");
    out.push("Is this quarter in line with management's guidance?");
  } else if (card.category === "management_change") {
    const incoming = card.people?.changes.find((c) => c.direction !== "exit");
    const outgoing = card.people?.changes.find((c) => c.direction === "exit");
    if (incoming) out.push(`What will ${incoming.name} change in the strategy?`);
    if (outgoing) out.push(`Was ${outgoing.name}'s exit planned, and what did they deliver?`);
    out.push("How did the market take the leadership change?", "Does the new team keep the existing guidance?");
  } else if (card.subtype === "order_win") {
    out.push("How big is the order book after this win?", "What margin will this order earn?",
      "When will it start adding to revenue?");
  } else if (card.subtype === "regulatory_approval") {
    out.push("When will this start contributing to revenue?", "How big is the market it opens?",
      "Who else is competing for it?");
  } else if (card.category === "earnings_call") {
    out.push("What did management promise this time?", "Did they change any earlier guidance?",
      "What were analysts most worried about?");
  } else if (card.category === "litigation") {
    out.push("How much money is at stake?", "Is there a provision in the accounts?", "When is the next hearing or decision?");
  } else if (card.category === "m_and_a") {
    out.push("What is the deal worth, and how is it funded?", "What does it add to revenue and profit?",
      "Has management done similar deals before?");
  }
  out.push("What does this change for the business?", "Has management commented on this?",
    "Should I look at this again next quarter?");
  return [...new Set(out)].slice(0, 3);
}

export function contextFor(card: Card): string {
  return card.results ? `${card.results.period.replace("FY", " FY")} results` : card.label;
}

export function useFollowUps() {
  const [items, setItems] = useStored<FollowUp[]>("finn.followups", []);
  const add = useCallback((card: Card, note: string) => {
    setItems((list) => [{
      id: `${card.id}-${Date.now()}`, announcementId: card.id, symbol: card.company.symbol, name: card.company.name,
      context: contextFor(card), note: note.trim(), sourceUrl: card.document_url ?? card.source_url,
      createdAt: new Date().toISOString(), resolvedAt: null,
    }, ...list]);
  }, [setItems]);
  const resolve = useCallback((id: string, resolved = true) => {
    setItems((list) => list.map((f) => (f.id === id ? { ...f, resolvedAt: resolved ? new Date().toISOString() : null } : f)));
  }, [setItems]);
  const remove = useCallback((id: string) => setItems((list) => list.filter((f) => f.id !== id)), [setItems]);
  return { items, open: items.filter((f) => !f.resolvedAt), resolved: items.filter((f) => f.resolvedAt), add, resolve, remove };
}

/** The digest path for the window the investor last chose on Today (shared with Review). */
export function digestPath(win: string, since: string): string {
  if (win === "custom" && since) return `/api/digest?since=${encodeURIComponent(new Date(since).toISOString())}`;
  const hours = ({ "24": 24, "72": 72, "168": 168 } as Record<string, number>)[win] ?? 24;
  return `/api/digest?widen=true&hours=${hours}`;
}
