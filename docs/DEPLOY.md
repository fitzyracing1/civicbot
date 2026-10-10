# Deploying the civicbot signup site + hosted runner

> Status: deploy-ready code, **not deployed anywhere**. Nothing below has been run against a paid host,
> and no X app has been created. Prices were checked on 2026-10-10. Check them again before you buy anything.

## What runs

| Process | Command | Job |
|---|---|---|
| web | `python -m civicbot.web` | Signup wizard, owner dashboard, `/healthz`, X OAuth callback |
| worker | `python -m civicbot.web.worker` | Runs the multi-tenant `Fleet` for every active robot: polls mentions, replies, applies guardrails |

Both use one database (`DATABASE_URL`). The default is SQLite on a volume. For Postgres, set
`postgresql+psycopg://...`; the image includes `civicbot[postgres]`. Tables are created on startup.
On a single machine you can set `CIVICBOT_EMBEDDED_WORKER=1` to run the worker loop inside the web
process. This is the cheapest option, and it's needed with SQLite on hosts where two services can't
share a volume.

Health checks:
* `GET /healthz` returns 200 when the DB is reachable, and also reports the worker heartbeat age.
* `GET /healthz?strict=1` returns 503 if the worker heartbeat is stale.
* `python -m civicbot.web.worker --check` exits 1 if the heartbeat is stale.

## 1. X developer app (Joshua, in the X Developer Console)

Source: docs.x.com, "Developer Apps" and "OAuth 2.0 Authorization Code Flow with PKCE", read 2026-10-10.

1. Create a Project and App at <https://console.x.com>. API access is pay-per-use: buy credits and **set a
   spending limit** there. That limit is the hard backstop behind civicbot's own daily cap.
2. Open the App's **User authentication settings**:
   * **App permissions**: *Read and write*. Robots reply, and that needs `tweet.write`.
   * **Type of App**: *Web App, Automated App or Bot*. This is a confidential client, so you get a
     **Client Secret**. Native and Single-page apps are public clients and won't work here.
   * **Callback URI / Redirect URL**: `https://YOUR_DOMAIN/auth/x/callback`. It must match exactly,
     including scheme and trailing slash. An app can have up to 10 callback URLs.
   * **Website URL**: `https://YOUR_DOMAIN/`. Add **Terms** (`/terms`) and **Privacy** (`/privacy`)
     URLs once the drafts have had legal review.
3. Copy the **OAuth 2.0 Client ID and Client Secret** into `X_CLIENT_ID` and `X_CLIENT_SECRET`. Don't use
   the OAuth 1.0a API key/secret or a Bearer token; this app uses neither.
4. Scopes are requested at runtime, so there's nothing to tick in the console:
   * owner sign-in: `tweet.read users.read`. The token is revoked right after `/2/users/me`.
   * robot connect: `tweet.read tweet.write users.read offline.access`. The refresh token keeps
     robots working past the 2-hour access-token lifetime.
5. Read the README "X policy findings" first. Many user-owned bots run through one app, so X's view
   on that matters, and "Public Utility Apps" may qualify for free scaled access. Consider asking X
   before launch.

For local testing against real X, use a **separate dev app** with callback
`http://localhost:8000/auth/x/callback`. Never put production credentials on a laptop.

## 2. Secrets and settings

```bash
cp .env.example .env
python -c "import secrets;print(secrets.token_urlsafe(48))"                               # SESSION_SECRET
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"  # CIVICBOT_TOKEN_KEY
```

* Store these in the host's secret manager, not in git. `.env` is gitignored.
* **Back up `CIVICBOT_TOKEN_KEY`.** It encrypts every robot's OAuth tokens. If it's lost or rotated
  without re-encrypting, every owner has to reconnect.
* Launch in **shadow mode** (`CIVICBOT_X_WRITE_ENABLED=0`). Robots read mentions and the dashboard
  shows the replies they *would* have posted. Flip it to `1` once replies look right.
* `CIVICBOT_ALLOW_311_SENDING=0` stays off until each city agrees and you hold its API key
  (`CIVICBOT_CITY_API_KEYS`). Owners can switch sending on in the dashboard, but nothing is filed
  without this flag and a key.

## 3. Cost guardrails (X API)

Prices are pay-per-use and billed to the app owner (README "Costs"): $0.005 per mention read,
$0.010 per author lookup, $0.010 per summoned reply, and $0.20 for any post with a URL. civicbot never
puts URLs in replies.

| Setting | Default | Why |
|---|---|---|
| `CIVICBOT_DAILY_SPEND_CAP_USD` | 5.00 | Estimated spend per UTC day for the whole app. Polling stops at the cap. Worst case is about $150/month |
| `CIVICBOT_ROBOT_DAILY_MENTIONS` / `_REPLIES` | 200 / 50 | One busy robot can't eat the budget |
| `CIVICBOT_APP_POLLS_PER_15MIN` | 300 | X's per-app mentions ceiling is 450/15 min |
| `CIVICBOT_APP_POSTS_PER_DAY` | 9000 | X's per-app post ceiling is 10,000/24 h |
| `CIVICBOT_POLL_INTERVAL_S` | 120 | Minimum gap between polls of one robot |

The cap is checked before each poll, so one poll can overshoot it by at most a page of mentions. The X
console spending limit is the hard stop.

## 4. Hosts

All three below run the same Docker image. Prices come from each vendor's pricing page on
2026-10-10, are rounded, and leave out tax and bandwidth overage. The X API spend above usually
outweighs hosting.

### Fly.io (cheapest always-on)
Source: <https://fly.io/docs/about/pricing/>. A shared-cpu-1x 256MB Machine is $2.19/month,
512MB is $3.69/month, and volumes are $0.15/GB-month. Fly's own example lists Managed Postgres
Basic at $38/month.

A Fly volume attaches to one Machine. With SQLite, run **one** Machine with
`CIVICBOT_EMBEDDED_WORKER=1`:

```bash
fly launch --no-deploy            # uses the Dockerfile
fly volumes create civicbot_data --size 1
fly secrets set X_CLIENT_ID=... X_CLIENT_SECRET=... SESSION_SECRET=... CIVICBOT_TOKEN_KEY=... \
  PUBLIC_BASE_URL=https://YOUR_APP.fly.dev CIVICBOT_EMBEDDED_WORKER=1 CIVICBOT_TRUST_PROXY=1
# fly.toml: [mounts] source="civicbot_data" destination="/data"; [http_service] internal_port=8000,
#           auto_stop_machines="off", min_machines_running=1 (the worker must stay up);
#           [[http_service.checks]] path="/healthz"
fly deploy
```

That's about **$3.69 + $0.15 ≈ $4/month** for one 512MB Machine and a 1GB volume, before X API costs.

### Render
Source: <https://render.com/pricing>. The Hobby workspace is $0/month plus compute. A Starter
instance (512MB) is $7/month, persistent disks are $0.25/GB-month, and Postgres Basic-256mb is
$6/month. Free instances spin down when idle, so they can't run the worker.

* **Option A**: one Web Service, Starter, with a 1GB disk at `/data` and
  `CIVICBOT_EMBEDDED_WORKER=1`. About **$7.25/month**.
* **Option B**: Web Service plus Background Worker, both Starter, with Render Postgres Basic and
  `DATABASE_URL` set to the internal URL. About **$20/month**.

Set the health check path to `/healthz`.

### Railway
Source: <https://railway.com/pricing>. The Hobby plan has a $5/month minimum that includes $5 of usage.
Usage is billed at $0.00000386/GB-sec of memory (about $10/GB-month) and $0.00000772/vCPU-sec (about
$20/vCPU-month). Volumes are $0.00000006/GB-sec (about $0.16/GB-month).

Deploy the repo as two services from the same Dockerfile: web, plus a worker with start command
`python -m civicbot.web.worker`. Add Railway Postgres, or use one service with a volume and
`CIVICBOT_EMBEDDED_WORKER=1`. A small idle deployment may fit inside the included $5; check the
usage dashboard after a day.

## 5. Production checklist

- [ ] HTTPS-only domain. `PUBLIC_BASE_URL` must be `https://` (the app refuses otherwise). Cookies are
      then `__Host-`, `Secure`, `HttpOnly`, `SameSite=Lax`, and HSTS is on.
- [ ] Set `CIVICBOT_TRUST_PROXY=1` only behind the platform's proxy, so per-IP rate limits see real
      client IPs. The limiter is in-process: with more than one web instance, add an edge rate limit
      or a shared store.
- [ ] Database backups. Volume snapshots or managed Postgres PITR.
- [ ] Logs are JSON on stdout, with tokens, auth codes, `state` and `Authorization` headers redacted.
      Ship them to the host's log drain. Keep them for a limited time, and document that in the
      privacy notice.
- [ ] Legal review of `/privacy` and `/terms` (both are marked DRAFT), plus the operator's identity
      and contact details.
- [ ] X app approved for the use case, with spending limit set and credits loaded.
- [ ] Start in shadow mode, check the dashboard, then set `CIVICBOT_X_WRITE_ENABLED=1`.
