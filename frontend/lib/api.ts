export const API = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

// ---------- types (mirror the FastAPI responses) ----------
export type Change = { value: number | null; note: string | null };

export type MetricBlock = {
  current_cr: number | null;
  prev_cr: number | null;
  year_ago_cr: number | null;
  qoq: Change;
  yoy: Change;
};

export type Results = {
  period: string;
  prev_period: string | null;
  year_ago_period: string | null;
  basis: string;
  page: number | null;
  metrics: Record<"revenue" | "ebitda" | "pbt" | "pat", MetricBlock>;
  margins: Record<"ebitda" | "pat", { current_pct: number | null; year_ago_pct: number | null; change_pp: number | null }>;
  ebitda_definition: string | null;
  notes: string[];
  line: string;
  verdict: string;
  verified_in_text: number | null;
  source: { url: string };
  attempts: { model: string; cost_usd: number; cached: boolean }[];
};

export type PersonChange = {
  name: string;
  role: string;
  direction: "appointment" | "exit" | "redesignation";
  effective_date?: string | null;
  reason?: string | null;
  background?: { bio: string | null; source: string; verified: boolean; note?: string; source_url?: string };
};

export type Reaction =
  | { status: "ok"; session: string; change_pct: number | null; relative_volume: number | null }
  | { status: "pending"; from_session: string }
  | { status: "unavailable" };

export type Card = {
  id: number;
  company: { symbol: string; name: string; sector: string | null };
  category: string;
  subtype: string | null;
  category_label: string;
  label: string;
  headline: string | null;
  summary: string | null;
  why_it_matters: string | null;
  priority: "high" | "medium" | "low";
  score: number;
  reasons: string[];
  published_at: string;
  exchange_category: string | null;
  document_url: string | null;
  source_url: string | null;
  reaction: Reaction | null;
  results: Results | null;
  people: { changes: PersonChange[]; line: string | null } | null;
  related: { id: number; label: string; summary: string | null; published_at: string; url: string | null }[];
};

export type Digest = {
  window: { start: string; end: string; hours: number };
  generated_at: string;
  counts: { filings: number; events: number; high: number; medium: number; low: number };
  cards: Card[];
  routine: {
    count: number;
    line: string | null;
    companies: { symbol: string; name: string; count: number; labels: string[] }[];
  };
};

export type Alert = {
  id: number;
  symbol: string;
  name: string;
  rule: "price_move" | "volume_spike" | "announcement_category";
  message: string;
  observed: number | null;
  threshold: number | null;
  as_of: string | null;
  triggered_at: string;
  source: { type: string; announcement_id?: number; url?: string; trading_date?: string } | null;
  seen: boolean;
};

export type Rule = {
  rule_type: "price_move" | "volume_spike" | "announcement_category";
  threshold: number | null;
  config: { categories?: string[]; min_score?: number; lookback?: number };
  enabled: boolean;
};

export type Holding = {
  symbol: string;
  name: string;
  sector: string | null;
  is_financial: boolean;
  market:
    | { available: false; reason: string }
    | {
        available: true;
        as_of: string;
        stale_days: number;
        close: number;
        day_change_pct: Change;
        volume: number;
        relative_volume: number | null;
        volume_lookback: number;
      };
  spark?: number[];
};

export type GuidanceRow = {
  id: number;
  stated_in: string | null;
  quote: string;
  metric: string;
  type: string;
  target: string | null;
  target_period: string | null;
  scope: string | null;
  segment: string | null;
  status: "met" | "missed" | "exceeded" | "on_track" | "behind" | "pending" | "not_comparable";
  actual?: number;
  measured_over?: string;
  reason?: string;
  source: { title: string; page: string | null; url: string };
};

export type Research = {
  company: { symbol: string; name: string; sector: string | null; in_portfolio: boolean };
  status: "ready" | "preparing" | "not_started";
  documents: { title: string; type: string; period: string | null; status: string; url: string; error: string | null }[];
  financials: {
    basis: string | null;
    unit: string;
    quarters: { period: string; revenue?: number; operating_profit?: number; ebitda?: number; pat?: number; pbt?: number }[];
  };
  guidance: { rows: GuidanceRow[]; counts: Record<string, number>; calls: { period: string; title: string; url: string }[]; margin_definition: string };
  narrative: { verdict: "delivers" | "mixed" | "over_promises" | "too_early"; summary: string; highlights: { row_ids: number[]; point: string }[] } | null;
};

export type Answer = {
  found: boolean;
  answer: string;
  sources: { n: number; title: string; page: number | string | null; url: string | null; kind?: string; excerpt: string }[];
  cached: boolean;
};
