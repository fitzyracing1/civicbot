# civicbot

**Robots and agents that call city-operated APIs to get things done.** Every person brings their
**own** robot X account (e.g. `@joshs_robot`) and connects it to civicbot with X OAuth 2.0. When the
owner posts "@joshs_robot streetlight out at 401 N Morton St", the robot works out which city that
address is in, picks the right 311 request type, prepares the Open311 request, and replies **from
the owner's robot account**.

> **Early prototype (v0.2, Oct 2026), open source under the MIT license.** Dry-run by default: it never
> files a real 311 request or posts to X unless you explicitly enable sending. Not yet published to PyPI;
> install from source. Issues and PRs welcome.

## What's in the box

| Module | What it does | Network |
|---|---|---|
| `civicbot.open311` | Open311 GeoReport v2 client: `list_services`, `get_service_definition`, `list_requests`, `get_request`, `get_token`, `build_request`, `create_request` (**dry_run=True default**) | read live, write gated |
| `civicbot.registry` + `data/endpoints.json` | Bundled registry of the verified endpoints (Chicago, Boston, Bloomington IN, Austin, Brookline MA) plus the SeeClickFix lat/lng-scoped fallback | n/a |
| `civicbot.geocode` | Free geocoding: US Census geocoder, then Nominatim (≤1 req/s, identifying User-Agent). Falls back to an approximate street centroid for intersections | read |
| `civicbot.resolver` | lat/lng or address → endpoint (city bounding box, then a live SeeClickFix coverage check) | read |
| `civicbot.transit` | Minimal GTFS-Realtime reader (arrivals, vehicles, alerts) for any feed URL | read |
| `civicbot.robot` | Rule-based intent parser (optional LLM hook), service matcher, `RobotProfile` (one per user-owned robot), varied replies under 280 chars, the `Robot` engine with policy guards, and `Fleet` (multi-tenant runner) | stubbed X |
| `civicbot.x` | X OAuth 2.0 PKCE connect (`XOAuth2`, `finish_connect`), token stores (`EncryptedFileTokenStore`), and the real `XApiV2Adapter` (**disabled unless `enabled=True` + a stored token**) | tests use mocked HTTP only |
| `civicbot.offline` | Transport that replays real responses captured 2026-10-10, for demos with no network | none |

Zero runtime dependencies (stdlib `urllib`). Transit parsing needs `civicbot[transit]`; encrypted token storage needs `civicbot[secure]` (cryptography).

## Coverage: why this is hard, and where the leverage is

These figures come from [`docs/research.md`](docs/research.md), which has sources and dates.

- The US has **19,491 municipal governments** (Census of Governments, 2022). Almost none have a callable "do something" API.
- About **5 city-run Open311 endpoints** are live and document write access: Chicago, Boston, Bloomington IN, Austin, and Brookline MA. The official Open311 server list is stale. SF officially dropped Open311, NYC's endpoint is retired, and DC is down.
- **SeeClickFix (CivicPlus)** exposes one GeoReport v2 API for each of its roughly **300–340 client governments**. That client count is a third-party estimate. This is the biggest single write integration, and civicbot uses it as the fallback for any lat/lng.
- **Open data (read-only):** about 150 US local governments use Socrata, and ArcGIS Hub reports 10,000+ public sites worldwide.
- **Transit:** about 41–55% of US federally funded transit agencies publish GTFS.
- Small towns mostly have nothing callable, so vendor integrations matter most (SeeClickFix/CivicPlus, Accela, Tyler, ParkMobile).

## Quickstart

```bash
git clone https://github.com/fitzyracing1/civicbot && cd civicbot
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest -q                                   # unit tests (mocked HTTP)
CIVICBOT_LIVE=1 pytest -q -m live           # read-only live smoke tests

# two users, two robot accounts, two cities (fake X; real read-only city APIs, or --offline)
python -m civicbot simulate --demo
python -m civicbot simulate --demo --offline

# your own robots and messages: --robot handle:owner:home city, messages "author> @robot text"
python -m civicbot simulate --robot "joshs_robot:joshua:Bloomington, IN" \
    "joshua> @joshs_robot streetlight out at 401 N Morton St" --then "joshua> @joshs_robot YES"

# print the X authorization URL for a robot account (no network calls)
python -m civicbot connect --robot @joshs_robot --owner joshua \
    --client-id $X_CLIENT_ID --redirect-uri http://127.0.0.1:8765/callback

python -m civicbot endpoints
python -m civicbot services bloomington-in
python -m civicbot resolve "1 City Hall Sq, Boston, MA"
python -m civicbot transit https://cdn.mbta.com/realtime/TripUpdates.pb --route Red
```

## Bring your own robot account (setup for each person)

civicbot never creates, owns or holds anyone's X account. Each person does this once:

1. **Create a separate X account for the robot**, e.g. `@joshs_robot`. It must not be your personal
   account (`finish_connect` refuses to connect a robot whose handle equals the owner's). Each X account
   needs its own email/phone. X lets one person run up to 10 accounts for non-duplicative purposes.
2. **Make it obviously a bot.**
   - Turn on the **Automated** label and link your personal account as the managing account.
     Path reported by secondary guides: Settings and privacy → Your account → Account information →
     Automation → Managing account → log in as your personal account (x.com/settings/account/automation).
     X's help page describes the label as a feature it is still launching, so the menu may be missing for
     some accounts. If so, put the bot statement in the bio and try again later.
   - Bio: "Bot run by @joshua. Files city 311 reports when @joshua asks. Reply STOP to opt out."
3. **Connect it to civicbot.** Run `civicbot connect` (or open the app's connect page), read the consent
   list (what the robot will do automatically), then **log in to X as the robot account** and approve.
   Scopes: `tweet.read tweet.write users.read offline.access`. civicbot checks via `GET /2/users/me` that
   the token really belongs to the robot account, stores it encrypted, and records your consent
   (version + timestamp).
4. **Set your home city** (and optionally a default location, an allowlist of friends, and
   `updates on` if you want status follow-ups in the thread).
5. **Use it**: post `@joshs_robot pothole at 401 N Morton St`. Only you (and people you allowlisted) can
   command your robot; it ignores everyone else.
6. **Disconnect any time**: reply `STOP`, revoke the app at x.com/settings/connected_apps, or call
   `civicbot.x.disconnect(...)`, which revokes the token at X and deletes it locally.

### How the code maps to this

```python
from civicbot.robot import Fleet, ProfileStore
from civicbot.x import OAuthConfig, XOAuth2, EncryptedFileTokenStore, XApiV2Adapter, finish_connect

oauth = XOAuth2(OAuthConfig(client_id=..., client_secret=..., redirect_uri="https://civicbot.example/cb"))
tokens = EncryptedFileTokenStore("tokens.enc")         # key from CIVICBOT_TOKEN_KEY; or plug in KMS
profiles = ProfileStore("profiles.json")               # no secrets in here

url, pending = oauth.start(robot_hint="joshs_robot", owner_hint="joshua")   # send owner to url
# ... X redirects to /cb?state=..&code=..  (code is valid for 30 s)
finish_connect(oauth, tokens, profiles, state=state, code=code, consent_accepted=True,
               home_city="Bloomington, IN")

fleet = Fleet(profiles, lambda p: XApiV2Adapter(p.robot_id, oauth, tokens,
                                                robot_user_id=p.robot_user_id, enabled=True))
fleet.run_once()   # polls each robot's mentions with ITS token, replies from ITS account
```

- Access tokens last 2 hours; the adapter refreshes them automatically (refresh tokens need
  `offline.access`), and saves the rotated token back into the store.
- One robot's failure (revoked token, 429) is logged and does not stop the rest of the fleet.

## Safety model

- **Dry-run by default.** `create_request()` builds and validates the exact form payload. To actually
  send you need all of `dry_run=False`, `api_key=...` and `confirm="SEND"`.
- **The robot can't file by itself.** "YES" only files when the robot's profile has `send_enabled=True`
  and civicbot holds a city API key. Both are off by default; the simulator never turns them on.
- **The real X adapter is off.** `XApiV2Adapter` raises unless built with `enabled=True` *and* a token
  exists for that robot. Tests only run it against a fake transport. Nothing in this repo posts to X.
- **Owner-only.** Each robot acts only on mentions/DMs from its owner (plus an explicit allowlist), only
  on posts that actually @mention it, and only after recorded consent.
- **Secrets.** Tokens are Fernet-encrypted at rest (file mode 600); `OAuthToken.__repr__` hides them;
  the CLI never prints the PKCE verifier. Use a KMS-backed `TokenStore` in production.
- **Rate limits.** City APIs: 0.5 s per host (1.1 s for Nominatim) and an identifying User-Agent.
  X: `Fleet(min_poll_interval=60)` per robot by default (see the per-app ceiling below).

## X policy findings for the bring-your-own-robot model (checked 2026-10-10)

Sources: [Developer Policy](https://docs.x.com/developer-terms/policy),
[Developer Guidelines](https://docs.x.com/developer-guidelines),
[Automation Rules](https://help.x.com/en/rules-and-policies/x-automation) ("Updated April 2026"; read via the
[Wayback copy of 2026-10-01](https://web.archive.org/web/2026/https://help.x.com/en/rules-and-policies/x-automation)
because help.x.com blocks automated fetches),
[Authenticity policy](https://help.x.com/en/rules-and-policies/authenticity) (Wayback 2026-10-07),
[Automated account labels](https://help.x.com/en/using-x/automated-account-labels) (Wayback 2026-05-04),
[Rate limits](https://docs.x.com/x-api/fundamentals/rate-limits), [Pricing](https://docs.x.com/x-api/getting-started/pricing),
[Manage Posts](https://docs.x.com/x-api/posts/manage-tweets/introduction), [Changelog](https://docs.x.com/changelog).
This is not legal advice. **Recommendation: email X developer support and describe this exact pattern before launch.**

**1. The 10-account limit.** Authenticity policy: "X allows users to create and/or operate up to ten (10)
accounts for different, non-duplicative purposes." The limit applies to a *user*. Here each person creates
and owns one robot account, so it counts toward *their* limit, not Joshua's. The policy also allows people to
"control multiple accounts on behalf of a third-party (e.g. 'Social Media Managers'), provided that no
violations of X Rules ... occurs". *Uncertain:* X has not said how it views one app operating thousands of
user-owned bots that do the same job.

**2. Consent: OAuth alone is not enough.** Automation Rules II.A: "A user authorizing your app or service to
access their X account through OAuth does not by itself constitute sufficient consent to take automated
actions through that user's account." You must "clearly describe to the user the types of automated actions
that will occur", get express consent, and honor opt-outs. → `RobotProfile.grant_consent()` records the action
list + version + time; `Robot` ignores everything until consent exists; `civicbot connect` prints the list.

**3. Automated label and responsibility.** Developer Policy: "If you're operating an API-based bot account you
must clearly indicate what the account is and who is responsible for it." Developer Guidelines require
enabling the 'Automated' label, a bio disclosure, and "Link to a human-managed account". Help center: "Our
Automation rules require these accounts to display labels and remain connected to a human-run account." The
**owner** sets this on their robot account and links their *personal* account (step 2 above). civicbot
cannot set it through the API.

**4. Identical / substantially similar content — the biggest risk.**
- Developer Policy: "Never post identical or substantially similar content across multiple accounts".
- Automation Rules: "You may not post duplicative or substantially similar posts on one account or over
  multiple accounts you operate" and "You may not create and/or automate multiple accounts for duplicative or
  substantially similar use cases. However, automating multiple accounts for related but non-duplicative use
  cases is permitted."
- Developer Guidelines list "Account Farms: Multiple accounts for same duplicative purpose" as prohibited,
  but allow "Multiple city-specific alert accounts (e.g., @WeatherNYC, @WeatherLA) — non-duplicative,
  location-specific content".

*How civicbot reduces the risk:* robots post only in reply to their owner, and the content comes from the
owner's specific request (service, city, street). Phrasing comes from a template pool chosen by a hash of
robot + mention. A fleet-wide `FleetDuplicateGuard` rotates the template (or adds a robot-specific suffix)
whenever another robot already posted the same normalized text. Tests check that 12 robots handling the
*identical* request produce 12 different texts. *Uncertain / blocker to clarify:* whether X treats "many
people's robots, all doing 311 reports via one app" as an account farm. The per-person ownership and
per-location content are the arguments that it is not.

**5. Replies only when summoned.** Automation Rules allow automated replies only after opt-in, e.g. "A mention
of your account by the user in a manner suggesting the user clearly wishes or intends to receive a
response", with "one automated reply or mention per user interaction". Manage Posts (since the
2026-02-23 change): "Self-serve customers: Replies are only permitted if the original post's author has
explicitly summoned the replying account by @mentioning them or quoting one of their posts." → The robot
replies only to posts that @mention it, once per mention. Replies don't start with "@owner": X threads
replies on its own, and programmatic @mentions carry extra restrictions.

**6. Follow-ups.** "After a user-initiated interaction ends, don't send additional follow-up Direct Messages
or mention users in a post unless you get permission from the user." → Status follow-ups are off until
the owner says `updates on` (or opts in at connect); `status #id` always works on demand.

**7. Does the app need X's approval?**
- *White label — probably not:* "'White label' versions of a tool or service are not permissible. If you plan
  to 'white label' versions of your application, you must notify and receive separate approval from us."
  civicbot is **one app** (max 3: dev/staging/prod) acting for many users, not a re-branded copy per
  customer. Don't ship per-city or per-customer copies of the app.
- *AI replies — yes, if you add an LLM:* "the deployment or operation of any AI reply bot requires prior
  written and explicit approval from X." civicbot's parser and replies are rule-based by default; turning on
  `llm_hook`, or generating reply text with a model, needs X's approval first.
- *Commercial / government:* Developer Guidelines: "Commercial use: Requires appropriate paid tier; free tier
  is non-commercial only"; "Government use: Requires Enterprise tier". If a city runs or pays for this, plan
  on Enterprise.

**8. Rate limits: per-user and per-app both apply.** "Per-user limits apply with OAuth 1.0a or OAuth 2.0 user
tokens; per-app limits apply with Bearer Token (app-only)." The table lists both columns for each endpoint:

| Endpoint | Per app | Per user |
|---|---|---|
| `GET /2/users/:id/mentions` | 450 / 15 min | 300 / 15 min |
| `POST /2/tweets` | 10,000 / 24 h | 100 / 15 min |

Each robot has its own per-user budget. But if the per-app column also counts user-token calls (the docs
don't say clearly; *assume it does*), the whole fleet shares **450 mention polls per 15 min** (one poll every
2 s across all robots) and **10,000 replies per day**. At 1,000 robots that is one poll per robot every
~33 min. Past a few hundred active robots you need the Account Activity webhooks / filtered stream or
Enterprise.

**9. Costs (pay-per-use; the app owner pays).** Credits are bought in the X Developer Console by the
developer account that owns the app — i.e. **Joshua pays for every robot's API calls**, not the robot
owners. Spending limits and auto-recharge are set there.

| Action | Price |
|---|---|
| Posts: Read (each mention returned) | $0.005 per resource |
| User: Read (e.g. author expansion, `/users/me`) | $0.010 per resource |
| Post: Create (summoned reply) | $0.010 per request |
| Post: Create (normal / with URL) | $0.015 / $0.200 per request |
| DM Interaction: Create | $0.015 per request |

Resources are deduplicated within a 24-hour UTC day. "Owned Reads" ($0.001) are "requests made by your own
developer app for your own data", so they most likely **don't** apply to other people's robot accounts.
Rough cost per report: 1 mention read + the author expansion + 1 summoned reply ≈ $0.025, or ~$0.04 with a
YES confirmation round. An empty mentions poll returns no resources, but treat polling cost as uncertain.
Keep URLs out of replies ($0.20 each). The changelog notes "Public Utility Apps continue to receive free
scaled access", so a civic 311 tool may be worth applying for that.

**Blockers before any real launch:** (a) X's view on many user-owned bots via one app (item 4);
(b) AI approval if any LLM is used; (c) paid/Enterprise tier for commercial or government use; (d) the
per-app ceiling (item 8); (e) each city's API key and terms for real filing.

## Tests

`pytest -q` runs 84 unit tests with mocked HTTP and skips 5 live tests. They cover:
- PKCE S256, the authorize URL, code exchange (state check, TTL, Basic auth), refresh and revoke
- the encrypted token store (no plaintext on disk, mode 600, wrong key fails)
- the adapter's disabled guard, mentions/reply payloads, token auto-refresh and 429 handling
- `finish_connect` identity checks
- fleet routing, owner-only, consent, summoned-only, reply variation and follow-up permission
- CLI `connect` (no network) and the two-robot demo

`CIVICBOT_LIVE=1 pytest -m live` adds the read-only live city checks (Bloomington, Boston, SeeClickFix
New Haven, a live-schema dry run, MBTA GTFS-RT).

## Limitations / next steps

- City bounding boxes are approximate. Point-in-polygon against city boundaries (Census TIGER) would be exact.
- Intersections fall back to a street centroid. An Overpass query for the actual intersection node would be more precise.
- Each Open311 server returns a different response shape after a POST (service_request_id or token). `get_token` exists, but polling tokens isn't wired into the robot yet.
- Next integrations to add: SeeClickFix's own APIv2 (accounts, comments), Socrata/ArcGIS read helpers, Accela, and parking.
