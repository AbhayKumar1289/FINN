export const API = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
      signal: init?.signal ?? AbortSignal.timeout(init?.timeoutMs ?? 45_000),
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "TimeoutError") {
      throw new ApiError(504, "This is taking longer than usual. Please try again.");
    }
    throw e;
  }
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
  bridge_yoy?: Record<"operating" | "depreciation" | "finance_costs" | "other_income" | "exceptional" | "tax_and_minorities" | "pat", number> | null;
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
  brief: {
    headline: string | null; summary: string | null; counterparty: string | null; key_points: string[];
    value_low_cr: number | null; value_high_cr: number | null; value_note: string | null;
    materiality?: { value_cr: number; ttm_revenue_cr: number; pct_of_revenue: number };
  } | null;
  transcript: { period: string; guidance_count: number } | null;
  story: { headline: string; callout_title: string } | null;
  related: { id: number; label: string; summary: string | null; published_at: string; url: string | null }[];
};

export type Digest = {
  window: { start: string; end: string; hours: number; widened_from_hours?: number; latest_day?: string };
  generated_at: string;
  counts: { filings: number; events: number; high: number; medium: number; low: number };
  span: { oldest: string | null; newest: string | null };
  as_of?: { announcements: string | null; prices: string | null };
  cards: Card[];
  routine: {
    count: number;
    line: string | null;
    companies: {
      symbol: string; name: string; count: number; labels: string[];
      items: { id: number; label: string; summary: string | null; published_at: string; reasons: string[]; url: string | null }[];
    }[];
  };
};

export type Alert = {
  id: number;
  symbol: string;
  name: string;
  rule: "price_move" | "volume_spike" | "announcement_category";
  title: string;
  detail: string | null;
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
  latest_filing?: { id: number; headline: string; published_at: string; priority: string } | null;
  unread_alerts?: number;
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
  measured_as?: string;
  partial?: boolean;
  gap?: number | null;
  target_low?: number | null;
  target_high?: number | null;
  unit?: string | null;
  /** a later restatement of the same promise points at the first one */
  same_as?: number;
  reiterated_in?: string[];
  reason?: string;
  source: { title: string; page: string | null; url: string };
};

export type Research = {
  company: { symbol: string; name: string; sector: string | null; in_portfolio: boolean; is_financial?: boolean };
  status: "ready" | "preparing" | "not_started";
  progress: { read: number; total: number; failed: number };
  documents: { title: string; type: string; period: string | null; status: string; url: string; error: string | null }[];
  financials: {
    basis: string | null;
    unit: string;
    quarters: { period: string; revenue?: number; operating_profit?: number; ebitda?: number; pat?: number; pbt?: number }[];
  };
  guidance: { rows: GuidanceRow[]; counts: Record<string, number>; calls: { period: string; title: string; url: string }[]; margin_definition: string };
  statements: Statements | null;
  narrative: { verdict: "delivers" | "mixed" | "over_promises" | "too_early" | "tracking"; verdict_capped?: boolean; summary: string; highlights: { row_ids: number[]; point: string }[] } | null;
};

export type Answer = {
  found: boolean;
  answer: string;
  sources: { n: number; title: string; page: number | string | null; url: string | null; kind?: string; excerpt: string }[];
  cached: boolean;
};

type Series = (number | null)[];
export type Statements = {
  years: string[];
  basis: string;
  source: string;
  snapshot: { label: string; value: number; unit: "cr" | "pct" | "x" }[];
  trajectory: { revenue: Series; pat: Series; margin: Series | null; notes: string[];
                cagr?: { revenue: number | null; pat: number | null; from: string; to: string } };
  balance: { years: string[]; net_worth: Series; debt: Series; de?: Series; deposits?: Series;
             wc_days?: Series; ccc?: Series; interest_cover?: number; notes: string[] };
  cash: { years: string[]; cfo: number[]; pat: number[]; fcf: Series; conversion: Series; notes: string[];
          applicable: boolean; cumulative?: { cfo: number; pat: number; ratio: number | null; from: string; to: string } };
};

export type Source = { n: number; title: string; page: number | string | null; url: string | null;
                       kind: "excerpt" | "finn_fact"; excerpt: string };
export type Business = {
  summary: string;
  segments: { name: string; share_pct: number | null; detail: string; ref: number }[];
  facts: { text: string; ref: number }[];
  sources: Source[];
};
export type Case = { bull: { point: string; refs: number[] }[]; bear: { point: string; refs: number[] }[]; sources: Source[] };
