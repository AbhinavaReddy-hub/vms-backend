# Visitor Management System — Backend

Complete, working backend. Two services, 124 tested endpoints.

Everything in here was run and verified before hand-off — auth, permissions,
invites, visitor registration, face recognition, kiosk movements, approvals,
blocklist, roles, audit log.

---

## What's inside

```
vms-backend/
├── docker-compose.yml          run everything together
├── .env.example                copy to .env and edit
├── postman_collection.json     124 requests, ready to import
├── smoke_test.py               proves the whole system works in one run
│
├── api_gateway/                the main service
│   ├── seed.py                 creates roles, visitor types, demo staff, a kiosk
│   └── app/
│       ├── main.py             FastAPI app, routers, CORS, background jobs
│       ├── core/               config, security, permissions, deps, pagination
│       ├── db/                 SQLAlchemy session and base
│       ├── models/             every database table
│       ├── schemas/            Pydantic request/response shapes
│       ├── api/v1/             route handlers (thin - no business logic here)
│       ├── services/           ALL business rules live here (no FastAPI imports)
│       ├── clients/            face, email, SMS, Teams - one file each
│       └── jobs/               auto-close visits, expire invites, purge face data
│
└── face_service/               separate service, no public port
    └── app/
        ├── main.py             /embed, /compare, /health
        └── face_engine.py      InsightFace (SCRFD + ArcFace), no web code
```

---

## Run it (Windows)

### Option A — quickest, no Docker

You need two terminals.

**Terminal 1 — the main API:**
```cmd
cd vms-backend\api_gateway

python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt

copy ..\.env.example ..\.env

uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs — every endpoint is there, clickable.

**Terminal 2 — the face service** (optional; the API works without it,
face endpoints just return "face service unavailable"):
```cmd
cd vms-backend\face_service

python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt

uvicorn app.main:app --reload --port 8001
```

First run downloads the face model (~280MB), so give it a minute.

Check both are talking to each other:
```cmd
curl http://localhost:8000/health
```
You want `"face_service": "up"`.

### Option B — Docker (closer to production, uses Postgres)

```cmd
cd vms-backend
copy .env.example .env
docker compose up --build
```

---

## Seeded logins

| Email | Password | Role | What they can do |
|---|---|---|---|
| abhinav@company.com | `Admin@12345` | Global Admin | Everything (all 43 permissions) |
| priya@company.com | `Security@123` | Security Desk | Visitors, approvals, blocklist |
| suresh@company.com | `Host@12345` | Host | Only his own visitors |
| meera@company.com | `Approve@123` | Approvals Admin | Approvals + visitor entries |
| rahul@company.com | *(no login yet)* | — | Use him to test the admin-invite flow |

**Kiosk pairing code: `123456`** (one-time use — re-seed the DB to get it back)

---

## Testing with Postman

1. Import `postman_collection.json`
2. Run **1. Auth → Login (Global Admin)** — it saves the token automatically
3. Run **5. Kiosk → Pair device** — saves the device token automatically
4. Everything else now works

The **11. SECURITY TESTS** folder is worth showing in your interview — every
request in it is supposed to fail, and proves the permission system is real.

---

## Prove it works in one command

```cmd
cd vms-backend
python smoke_test.py
```

This runs the entire system end to end and prints pass/fail for each step.

---

## The three caller types

This is the core of the security design. Three kinds of caller, three
different credentials, three separate dependencies:

| Caller | Credential | Can reach |
|---|---|---|
| Staff (admin site) | `Authorization: Bearer <JWT>` | `/api/v1/*` admin routes, filtered by permission |
| Visitor (their phone) | invite token in the URL | `/api/v1/public/*` only |
| Kiosk tablet | `X-Device-Token: <token>` | `/api/v1/kiosk/*` only |

A kiosk token cannot reach an admin route. An admin token cannot act as a
kiosk. Not because of a flag check — because those routes use a completely
different dependency function.

---

## Security, layer by layer

- **Passwords** — bcrypt hash, never the password
- **Access token** — JWT, 15 minutes
- **Refresh token** — stored hashed in the DB, so it can actually be revoked
- **Brute force** — failed-attempt counter + temporary lockout + IP rate limit
- **Generic login errors** — never reveals whether an email exists
- **Permissions** — every endpoint declares its key; deny by default
- **Row-level rules** — a Host sees only his own invites and approvals
- **Invite tokens** — `secrets.token_urlsafe(32)`, only the SHA-256 hash stored
- **OTP** — hashed, 5-minute expiry, max 5 attempts, single use
- **Device tokens** — hashed, instantly revocable from the Devices page
- **Face service** — no public port at all; unreachable, not just protected
- **Consent gate** — face capture is blocked until consent is recorded
- **Retention job** — face data auto-deletes after the retention period
- **Blocklist** — visitor sees a neutral message; only security sees the reason
- **Audit log** — append-only, no PATCH or DELETE endpoints exist
- **CORS** — locked to the known frontend origin, never `*`
- **Secrets** — environment variables only, `.env` is gitignored

---

## Decoupling, and where it stops

**Split into separate services:**
- Face service — heavy unusual dependencies, might need a GPU later, most
  likely piece to be replaced, and highest security value in isolating

**Split inside the codebase:**
- `api/` handlers are 3–5 lines: check permission, call service, return
- `services/` holds every business rule and imports no FastAPI at all
- `clients/` wraps each external dependency in one file

**Deliberately NOT split** (worth saying out loud in the interview):
- No repository layer — SQLAlchemy is already an abstraction
- No auth microservice — it is tightly bound to user data
- No message queue — `BackgroundTasks` is right at office scale
- No separate DB per service — the face service is stateless
- No event bus — invites, visits and approvals change together

---

## Key design decisions

**One visit, many movements.** A visit runs from arrival to final departure.
Cafeteria, lunch and restroom trips are `step_out` / `step_in` movements
*inside* that visit. They never need re-approval and never re-notify the
host — pinging someone for a bathroom break is how people learn to ignore
notifications.

**Group invites make one token per person.** A single shared link would let
anyone with it register as anyone else. One admin action, separate tokens.

**Bad rows fail individually.** A bulk invite with one bad email creates the
good ones and returns per-row errors, so the UI can highlight the exact cell.

**Corrections never overwrite.** Fixing a wrong timestamp adds a new row
flagged `is_correction`. The original stays visible. That is what makes the
log worth trusting.

**Auto-closed visits are labelled honestly.** If nobody scanned out, the
end-of-day job marks it `auto_closed` rather than inventing an exit time.

**SQLite by default.** Runs with zero setup so you can demo anywhere. Set
`DATABASE_URL` to a Postgres URL and nothing else in the code changes.

---

## Tuning before your demo

The one number worth changing is the face match threshold:

```cmd
curl -X PATCH http://localhost:8000/api/v1/settings ^
  -H "Authorization: Bearer YOUR_TOKEN" ^
  -H "Content-Type: application/json" ^
  -d "{\"face.match_threshold\": 0.72}"
```

Too many wrong matches → raise it. Real returning visitors not recognised →
lower it. Test with your own face at different angles and lighting.

---

## What is deliberately not built

Worth having as a slide: *here's what I left out, and why.*

- Directory sync (Google/Entra) — config table exists, sync does not
- Legal document signing — tables exist, signing UI does not
- Third-party watchlist screening — approval framework is generic so a vendor
  could plug in; only the internal blocklist is implemented
- Multi-location — single office by design
- Billing — out of scope
- WebSocket live push — dashboard endpoints exist; polling is fine at this scale
- Alembic migrations — `create_all` while the schema is still moving
