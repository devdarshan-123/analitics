# Analytics Dashboard — GA4 + Microsoft Clarity

One web UI for Google Analytics 4 (traffic, acquisition, content, events, realtime) and Microsoft Clarity (scroll depth, engagement time, rage/dead clicks and other frustration signals). It also has a combined **Content** view that flags *problem pages*: pages with high traffic and high frustration.

```
analytics/
├─ backend/    FastAPI · SQLAlchemy · APScheduler · httpx · google-analytics-data
├─ frontend/   React · Vite · TypeScript · Tailwind · Recharts · TanStack Query
├─ docker-compose.yml   backend + frontend (nginx) + Postgres
└─ .env.example
```

## How it works

| Source | How data is fetched |
|---|---|
| **GA4** | Live, on request, through the Analytics Data API (`BetaAnalyticsDataClient`). Cached in memory for 10 min (realtime for 60 s). |
| **Clarity** | **Never on page load.** Clarity's Data Export API allows only **10 requests per project per day** and returns only the last 1–3 days. A scheduled job (02:00 in `TZ`) makes 5 calls (totals, URL, Device, Source, Country/Region) with `numOfDays=1`. It stores the raw JSON (`clarity_raw_snapshots`) and normalised rows (`clarity_metrics`), so history builds up beyond Clarity's 3-day window. The first run also backfills a 3-day totals snapshot (6 calls in total). Re-runs for the same date are skipped (idempotent). A per-UTC-day counter (`clarity_api_usage`) refuses calls once 9 have been used. An HTTP 429 marks the day as exhausted. |

Every `/api/*` route except `/api/health` needs a login, using a single password (`DASHBOARD_PASSWORD`) and an HTTP-only signed cookie. Tokens and keys stay on the server, and the browser only ever talks to `/api/*`.

---

## Prerequisites

- Python **3.11+** (tested with 3.13)
- Node.js **20+** (tested with 24)
- Optional: Docker Desktop (for `docker compose`)
- A GA4 property, and a Clarity project on the same site

## 1. Set up Google Analytics 4 access (service account)

1. **Create or choose a Google Cloud project:** go to <https://console.cloud.google.com/>.
2. **Enable the API:** go to *APIs & Services → Library*, search for **"Google Analytics Data API"** and click **Enable**.
3. **Create a service account:** go to *IAM & Admin → Service Accounts → Create service account*. Give it a name such as `ga4-dashboard`. It doesn't need any GCP roles, so click *Done*.
4. **Create a key:** open the service account, go to *Keys → Add key → Create new key → JSON*, and download the file.
   - Save it as `secrets/ga-service-account.json` in this repo (the folder is git-ignored). **Never commit it.**
5. **Grant access in GA4:** in GA, go to *Admin → (Property column) Property access management → + → Add users*. Paste the service account's email (`…@…iam.gserviceaccount.com`), choose the **Viewer** role, untick "Notify", and click **Add**.
6. **Find the numeric property ID:** go to *Admin → Property settings*. **Property ID** is a number like `412345678`. This is **not** the `G-XXXXXXX` measurement ID.

### Multiple properties

The dashboard lists **every GA4 property the service account can read** (Analytics Admin API `listAccountSummaries`, cached 1 hour; *Refresh list* in the property switcher bypasses the cache) and lets you switch between them in the header.

- Enable **"Google Analytics Admin API"** in the same Google Cloud project as the Data API.
- Add the service account as **Viewer at the account level** (*Admin → Account access management*) to expose every property in that account, or per property.
- `GA4_PROPERTY_ID` is now an optional default; without it the first property is used. `GA_PROPERTY_ALLOWLIST` (comma-separated IDs) hides the rest.
- Every `/api/ga/*`, `/api/clarity/*` and `/api/combined/*` call takes `?propertyId=`. IDs not in the discovered list are rejected with 403.

## 2. Generate the Clarity API token

1. Open your project at <https://clarity.microsoft.com/>, then go to **Settings → Data Export**.
2. Click **Generate new API token**, give it a name, and copy the token. It's shown once, and you need to be a project admin.
3. The token is project-scoped. Each project has its own 10 requests/day, and the app tracks that quota per project.
4. Link each Clarity project to its GA4 property: in **Settings → Clarity projects** (tokens are stored Fernet-encrypted; set `CLARITY_TOKEN_ENCRYPTION_KEY`), or in `.env` via `CLARITY_TOKENS={"<property id>": "<token>"}`. The old `CLARITY_API_TOKEN` still works and belongs to the default property. The nightly sync runs each enabled project independently.

## 3. Fill in `.env`

```bash
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env
```

| Variable | Value |
|---|---|
| `MOCK_MODE` | `true` to preview with fake data (no credentials needed); `false` for real data |
| `GA4_PROPERTY_ID` | numeric property ID from step 1.6 |
| `GOOGLE_APPLICATION_CREDENTIALS` | path to the JSON key, e.g. `./secrets/ga-service-account.json` (absolute, or relative to the repo root) |
| `CLARITY_API_TOKEN` | token from step 2 |
| `DATABASE_URL` | `sqlite:///./analytics.db` locally; `postgresql://user:pass@host:5432/db` in production |
| `DASHBOARD_PASSWORD` | the password for the login page |
| `SESSION_SECRET` | optional; a long random string (otherwise derived from the password) |
| `COOKIE_SECURE` | `true` when served over HTTPS |
| `TZ` | `Asia/Kolkata`; used for the 02:00 schedule and for "yesterday" |
| `CORS_ORIGINS` | frontend origin(s), comma-separated (default `http://localhost:5173`) |
| `ENABLE_SCHEDULER` | `true` on exactly **one** backend instance |

> In mock mode with the default SQLite URL, the app automatically uses `analytics_mock.db`, so fake Clarity history never mixes with real data.

## 4. Run locally

**Backend** (terminal 1):

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend** (terminal 2):

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173> and sign in with `DASHBOARD_PASSWORD`. Vite proxies `/api` to `localhost:8000`.

API docs: <http://localhost:8000/docs>.

**Useful commands**

```bash
cd backend
pytest                              # run the test suite
python -m app.jobs.clarity_sync     # run a Clarity sync now (respects quota + idempotency)
```

You can also sync from **Settings → Sync Clarity now**, or with `POST /api/admin/clarity/sync`.

## 5. Run with Docker

```bash
# .env filled in; key file at ./secrets/ga-service-account.json
docker compose up --build
```

Open <http://localhost:8080>. Compose runs Postgres, the backend (one worker, which runs the scheduler) and nginx. Nginx serves the built frontend and proxies `/api` to the backend.

## 6. Deploy

The recommended setup puts the **backend and scheduler on Render or Railway**, the **frontend on Vercel**, and **Postgres on Supabase**.

### Postgres on Supabase
1. Create a project, then open *Project Settings → Database → Connection string → URI*. Use the **session pooler** URI (port 5432) for a long-running server.
2. Use it as `DATABASE_URL` (`postgres://…` or `postgresql://…` both work; the app adds the psycopg driver). Tables are created on first start.

### Backend on Render (Railway works the same way)
1. *New → Web Service* from this repo, **Root directory** `backend`, runtime **Docker**. Render injects `PORT`, and the Dockerfile uses it.
2. Environment: everything from `.env`, with `MOCK_MODE=false`, `COOKIE_SECURE=true` and `CORS_ORIGINS=https://your-app.vercel.app`.
3. **Service-account key:** add it as a *Secret File* named `ga-service-account.json` (Render mounts it at `/etc/secrets/ga-service-account.json`), and set `GOOGLE_APPLICATION_CREDENTIALS` to that path. On Railway, mount it through a volume or a file variable the same way.
4. **Scheduler:** the job runs inside the web process, so use an instance type that **doesn't sleep** and keep a **single instance**. On a free/sleeping tier, set `ENABLE_SCHEDULER=false` instead, and add a **Cron Job** service (same repo and env) with schedule `30 20 * * *` (UTC = 02:00 IST) and command `python -m app.jobs.clarity_sync`.
5. Health check path: `/api/health`.

### Frontend on Vercel
1. Import the repo with **Root directory** `frontend`. The framework preset is Vite: build `npm run build`, output `dist`.
2. Edit `frontend/vercel.json` and replace `YOUR-BACKEND.onrender.com` with your backend host. Vercel then proxies `/api/*` to the backend, so the browser treats everything as a single origin. The session cookie works with `SameSite=Lax`, and no backend URL or secret ends up in the JS bundle.

---

## API reference

All GA endpoints accept `?start=YYYY-MM-DD&end=YYYY-MM-DD` (default: last 30 days) and `&compare=true`.

| Endpoint | Description |
|---|---|
| `GET /api/ga/overview` | Totals plus % change vs the previous period of equal length |
| `GET /api/ga/timeseries` | Daily users/sessions/views (`compare` adds the previous period) |
| `GET /api/ga/channels` | By `sessionDefaultChannelGroup` (`compare` adds the previous sessions) |
| `GET /api/ga/sources` · `pages` · `geo` · `tech` · `events` | Source/medium, top 50 pages, country and city, device/browser/OS, top events |
| `GET /api/ga/realtime` | Active users in the last 30 min by country, device and page |
| `GET /api/clarity/overview` · `frustration` · `pages` | Read from the DB for the date range |
| `GET /api/clarity/breakdown?dimension=Device\|Source\|Country` | Latest snapshot |
| `GET /api/clarity/status` | Last sync, calls used today, next scheduled run |
| `GET /api/combined/pages` | GA pages joined with Clarity per-URL metrics; flags problem pages |
| `POST /api/admin/clarity/sync` | Manual sync |
| `POST /api/admin/test/ga` · `POST /api/admin/test/clarity[?live=true]` | Connection tests (a live Clarity test uses 1 call) |
| `POST /api/auth/login` · `logout`, `GET /api/auth/me`, `GET /api/health` | Auth and health |

Errors are returned as `{"error": {"code", "message", "hint"}}`, e.g. `ga_permission_denied` → *"GA permission denied — add the service account as a Viewer on the property."*

### Problem-page rule
Frustration score = `2×rage% + dead% + 0.5×quickback% + errorclick%` (each is the % of Clarity sessions with that signal). A page is flagged when its views are in the top quartile **and** its score is at or above `max(8, 75th percentile)`. GA and Clarity pages are matched on a normalised path: domain, query string, fragment and trailing slash are removed.

## Troubleshooting

| Symptom | Fix |
|---|---|
| *GA permission denied* | Add the service-account email as **Viewer** on the property (step 1.5) and enable the Analytics Data API (1.2). |
| *GA4 property not found* | `GA4_PROPERTY_ID` must be the numeric ID, not `G-…`. |
| Clarity sync "failed: rejected the API token" | Regenerate the token in Clarity → Settings → Data Export. |
| Clarity "quota used up" | Wait for the next UTC day. The counter resets at 00:00 UTC (05:30 IST). |
| Behaviour tab is empty | Clarity history starts at the first sync. Data for day *D* arrives at 02:00 on *D+1*. |

## Notes and limitations

- Clarity's metric field names aren't fully documented. The parser stores every numeric field it sees, keeps unknown metrics and fields (and logs them), and never crashes on unexpected shapes. The raw payload is always kept in `clarity_raw_snapshots`, so it can be re-parsed later. `backend/tests/fixtures/clarity_live_insights.json` documents the expected shape. After your first real sync, compare it with a stored payload.
- `numOfDays=1` covers "the last 24 hours" at sync time. It's stored as yesterday's date.
- Schema is created with `create_all`; `app/migrate.py` upgrades pre-multi-property databases in place on startup (existing Clarity data is assigned to the default property). Run it manually with `python -m app.migrate`. Tested on SQLite; the Postgres path uses plain `ALTER TABLE`.
