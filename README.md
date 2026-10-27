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
| **Research** | Any NSE ticker: transcripts and annual report indexed on demand; guidance from the last four quarters scored against reported numbers (met / missed / on track); grounded Q&A |

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
- **Guards against hallucination.** Results figures are checked against the PDF text layer; guidance
  quotes that can't be found in the transcript are dropped; Q&A cites excerpt ids and invalid ones
  are removed; segment-level guidance is never scored against group numbers.
- **Cost.** Every LLM call is cached by content hash and logged (`/api/llm/usage`). Building
  everything here, experiments included, cost about $0.06 at list prices (free tier in practice):
  roughly $0.001 per results filing, $0.002 per transcript, $0.0015 per question.
- **Honest data.** Prices are end-of-day, never "live"; a mid-session bar is not stored. A
  management bio not taken from the filing is labelled *Unverified*.

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
pytest -q                                             # 84 tests, no network needed
uvicorn app.main:app --port 8000

cd ../frontend
npm install
echo NEXT_PUBLIC_API_URL=http://localhost:8000 > .env.local
npm run dev                                           # http://localhost:3000
```

CLI: `python -m app.jobs cycle | refresh-prices | refresh-announcements | enrich | research <SYMBOL> | digest [hours]`.
See `DEPLOY.md` to deploy.
