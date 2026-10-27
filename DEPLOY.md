# Deploying FINN

Two pieces, two hosts:

| Piece | Host | Why |
|---|---|---|
| `backend/` (FastAPI) | **Render**, free web service | Runs continuously: polls NSE every 15 min, keeps a SQLite DB, runs minute-long research jobs. Vercel's serverless functions can't. |
| `frontend/` (Next.js) | **Vercel** | Native Next.js hosting |

The backend ships a demo snapshot (`backend/demo/finn_demo.db`). On a fresh server with no
database it starts from that snapshot, so the app opens with real filings and research even on a
host whose disk is wiped on every deploy.

## Before you start

1. **Rotate the Gemini key.** The current one was pasted into an AI chat. Create a new key in
   Google AI Studio, delete the old one, and keep the new one only in Render's dashboard.
2. Make sure `backend/.env`, `frontend/.env.local`, `backend/finn.db*` and `backend/data/` are **not**
   committed. `.gitignore` already excludes them.

## Prompt to give your coding agent (e.g. Antigravity)

> In this folder is a project called FINN (`backend/` is FastAPI, `frontend/` is Next.js 16).
> 1. Push the whole folder to my GitHub repo **<REPO NAME>** on branch `main`. Respect `.gitignore`;
>    don't commit any `.env` / `.env.local` file, `backend/finn.db*`, `backend/data/`, `.venv/` or
>    `node_modules/`. Before pushing, run `git status` and confirm no file contains a Gemini API key
>    (a string starting with `AQ.` or `AIza`).
> 2. Backend on **Render**: create a Blueprint from the repo (it reads `render.yaml`: service
>    `finn-api`, root `backend`, Python 3.12, free plan). When it asks for `GEMINI_API_KEY`, stop and
>    let me paste it myself. Wait until `https://<service>.onrender.com/api/health` returns
>    `{"api":"ok", ...}` and give me that URL.
> 3. Frontend on **Vercel**: import the same repo, set **Root Directory = `frontend`**, framework
>    Next.js, and add the environment variable `NEXT_PUBLIC_API_URL = https://<service>.onrender.com`
>    (no trailing slash). Deploy, then give me the production URL.
> 4. Open the Vercel URL on a phone-sized viewport and confirm the Today screen shows cards (L&T and
>    Maruti results, HDFC Bank MD & CEO change). If it shows "Couldn't load the briefing", check the
>    browser console for a CORS or URL error and fix the env var. Don't change application code
>    without asking me.

## Manual steps (if you'd rather click)

**Render**: dashboard → New → Blueprint → select the repo → set `GEMINI_API_KEY` → Apply. The first
build takes about 5 minutes. Check `/api/health`.

**Vercel**: dashboard → Add New → Project → import the repo → Root Directory `frontend` → add
`NEXT_PUBLIC_API_URL` → Deploy.

## After deploying

- **Keep it awake.** Render's free tier sleeps after 15 idle minutes (the first request then takes
  about 50 s, and polling pauses). A free pinger such as cron-job.org or UptimeRobot hitting
  `https://<service>.onrender.com/api/health` every 10 minutes keeps it awake and polling.
- **Persistence.** On the free plan the database resets to the demo snapshot on each redeploy or
  restart. For data that persists, use Render's Starter plan with a disk mounted at `/data` and set
  `DATABASE_URL=sqlite:////data/finn.db` and `DOCS_DIR=/data/docs`.
- **Warm the research cache** (optional) after the first deploy:
  `POST /api/research/<SYMBOL>/prepare` for any extra demo companies.
- If Yahoo rate-limits the server's IP, price refresh reports `failed` in `/api/health` and the app
  keeps showing the last prices from the snapshot.
