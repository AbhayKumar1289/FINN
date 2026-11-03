# FINN: a financial investment agent

A mobile-first briefing for an investor holding 18 NSE companies. **Push** tells you what changed
and why it matters; **Pull** answers questions from the company's own annual reports and concall
transcripts, with page citations.

The point of view: FINN is a morning briefing you work through, not a dashboard you scan. Each
card opens in three layers: *what happened* → *why it matters* (with evidence) → *Ask FINN*, a
research thread already scoped to that event. Routine filings collapse to one line.

## What it does

| | |
|---|---|
| **Digest** | Every portfolio filing in a window you choose (24h / 3d / 7d / since…), ranked, related filings grouped into one event, routine paperwork folded away |
| **Results** | Revenue, EBITDA, PBT, PAT, QoQ and YoY, read from the results PDF (scans included) |
| **Management change** | Who's in, who's out, effective date, and the appointee's background, labelled by source |
| **Alerts** | Price move ±X%, volume Y× its 20-day average, and filing types you pick; thresholds are yours |
| **Research** | Any NSE ticker, read on demand. The brief's full research menu on one page, with a jump list: **business snapshot** (segments and revenue mix from the annual report, page-cited) · **financial snapshot** (TTM) · **trajectory** (5-year CAGR, margin path, merger-sized jumps flagged) · **balance sheet** (gearing, interest cover, cash cycle; lender-aware) · **cash quality** (operating cash ÷ profit, FCF) · **promised vs delivered** and **guidance** (last four calls, scored by code) · **bull vs bear** (every point cited) · grounded Q&A |

## Architecture

```
NSE RSS feed ─┐                                ┌─ Today (digest cards)
NSE equity list┤   rules: classify, score    │   Alerts (thresholds)
Yahoo EOD ────┼─► SQLite ◄─ LLM: results,   ─┼─► Research (guidance vs delivered, Q&A)
screener.in ──┘   (+FTS5)    bios, guidance   └─ Portfolio
(transcripts, ARs)            ▲ cheap model first, strong on failure; every call cached
```

- **Backend**: FastAPI + SQLAlchemy on SQLite (FTS5 for retrieval). `backend/app/`
  - `ingest/` sources: NSE announcements RSS, NSE equity master, Yahoo EOD prices, screener.in documents
  - `pipeline/` rule-based classifier (the reference doc's 17 categories), priority scoring, card wording
  - `alerts/` threshold engine with dedupe keys (re-running is always safe)
  - `extract/` LLM layer: results numbers, management-change people and bios
  - `research/` FTS index, guidance extraction, promised-vs-delivered, grounded Q&A
  - `finance/calc.py` every number FINN shows; the LLM never does arithmetic
- **Frontend**: Next.js 16 (App Router), no UI library. `frontend/`

## Key decisions

- **Rules before models.** Classification and priority are regex rules: free, instant, explainable
  (each item records the rule that fired). The LLM only reads results filings, senior management
  changes and transcripts.
- **Model routing.** `gemini-flash-lite` copies table rows and quotes; `gemini-3.5-flash` writes the
  guidance verdict and Q&A answers, and re-runs an extraction only if code validation rejects the
  cheap output. Asking the small model to copy rows rather than fill a wide schema made it pass
  first time and cut cost about 20×.
- **Code does the maths and the judging.** Units, periods, EBITDA, growth, margins and every
  met/missed status come from `finance/calc.py` and `research/delivery.py`. The model writes prose
  around a table it cannot change.
- **A promise is scored only when it's the same number.** FINN measures reported, all-in rupee
  figures, so `research/delivery.py` refuses to score a target that is stated on another basis:
  constant currency (Infosys), organic growth (Indus Towers), a price or volume component (HUL),
  an industry figure (HDFC Bank's "system growth"), segment-level, or a growth target whose quote
  never says *what* grows. An "operating margin" target is measured as EBIT (operating profit less
  depreciation), not EBITDA. A promise restated on a later call counts once, as *reiterated*. Each
  unscored statement shows its reason. These rules are unit-tested.
- **Numbers sections are code, reading sections are cited.** Snapshot, trajectory, balance sheet and
  cash quality are arithmetic on the annual statements (`research/fundamentals.py`), including
  their one-line reads. Business snapshot and bull vs bear (`research/perspective.py`) are model-
  written from numbered excerpts and FINN's computed facts. A point without a valid citation is
  dropped, and a revenue share is shown only if the cited page prints it. For banks, leverage and
  cash-conversion tests are replaced by deposit funding, because the usual ratios mislead for lenders.
- **Guards against hallucination.** Results figures are checked against the PDF text layer; guidance
  quotes that can't be found in the transcript are dropped; Q&A cites excerpt ids and invalid ones
  are removed; segment-level guidance is never scored against group numbers.
- **Cost.** Every LLM call is cached by content hash and logged (`/api/llm/usage`). Everything in
  the demo, experiments included, cost about $0.15 over 130 calls at list prices (free tier in
  practice): roughly $0.001 per results filing, $0.0006 per transcript, $0.002 per question.
- **Honest data.** Prices are end-of-day, never "live"; a mid-session bar is not stored. A
  management bio not taken from the filing is labelled *Unverified*.

## Example: promised vs delivered (L&T)

| Said | Guided | Reported | Status |
|---|---|---|---|
| Q2 FY26 call, reiterated Q3 FY26 | FY26 revenue growth 15% | 11.8% (FY26) | **Missed** by 3.2 pp |
| Q4 FY26 call, reiterated Q1 FY27 | FY27 revenue growth 10–12% | 11.4% (H1 FY27) | **On track** (year not over) |

Each row links to the transcript page it came from. The verdict ("Mixed record") is written by
the strong model from this table and cites row ids. It can't mark a company "delivers" until
a guided period has fully reported.

## Reliability and failure handling

- **Idempotent jobs.** Ingest upserts; alerts carry dedupe keys; re-running a cycle is safe. Every
  ingest records an `IngestRun`, and FINN only says "no material filing" for a session it actually polled.
- **Degrades, doesn't break.** A strong-model quota error falls back to the cheap model. A
  transcript link that has moved is marked *couldn't read* and the rest still load. A missing price
  shows "–", never 0.
- **Network flakiness.** The NSE feed is retried (it sometimes serves a truncated cached copy). The
  frontend retries failed requests and shows staged loading messages through a free-tier cold start.
- **Any ticker.** Research is not limited to prepared companies: a new NSE symbol is validated
  against the NSE equity list, then its transcripts, annual report and quarterly table are fetched
  and read on demand. Transcripts are read first (about 90 seconds for five); the annual report index
  follows. Progress is shown throughout. Asian Paints was researched this way from scratch.

## Deliberately left out

Intraday data · news and broker notes (the brief asks for primary sources) · embeddings (BM25 suits
exact financial terms and needs no extra service) · auth and multi-user · BSE ingestion (BSE's API
blocks scripted access; NSE's official RSS is used instead) · segment-level guidance scoring.

## Known limitations

- NSE's RSS holds about one day, so history builds up by polling; the demo snapshot starts on 27 Oct 2026.
- Free hosting sleeps when idle, which pauses polling; a free uptime pinger on `/api/health` keeps it awake.
- Bank results are supported (EBITDA is skipped) but untested on a live bank filing.
- Bios use model knowledge unless the filing has a profile or `WIKI_CONTACT` is set (Wikimedia's bot
  policy requires a contact).

## Where next

Scoring segment and order-inflow guidance from later calls · an alert digest by WhatsApp or email at
8 am · comparing management's tone across quarters · a portfolio-level "what changed this week" view.

## Run locally

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                  # add GEMINI_API_KEY
pytest -q                                             # 103 tests, no network needed
uvicorn app.main:app --port 8000

cd ../frontend
npm install
echo NEXT_PUBLIC_API_URL=http://localhost:8000 > .env.local
npm run dev                                           # http://localhost:3000
```

CLI: `python -m app.jobs cycle | refresh-prices | refresh-announcements | enrich | research <SYMBOL> | digest [hours]`.
See `DEPLOY.md` to deploy.
