# PostgreSQL run worker slice

This implements a four-step fake workflow behind the merged v1 payload models. PostgreSQL stores the authoritative snapshot, immutable artifacts, ordered events, submission identity, and expiring claim. The API process only queues work. Run a separate worker process to execute it.

## Scope and contract follow-up

The v1 API supports submission, snapshots, event replay, both artifact reads, owner-scoped history, and Markdown, PDF, and PPTX downloads. History uses the contract's descending `(created_at, run_id)` order and opaque cursor. Review decisions remain integration work. This fake manifest has no review gate and records `not_evaluated` evaluations.

The following additions require a separate shared-contract PR before Surya integrates authentication and submission retries.

- Optional `Idempotency-Key` request header, scoped to the authenticated owner. Retain one key per submission and reuse it on retry. The same key and normalized body return the original 202 queued snapshot, even after execution completes. Fetch the current snapshot afterward. Conflicting input returns 409. Omitting the header creates a new run per request, as the merged contract specifies. Keys remain reserved for the lifetime of the run.
- Bearer authentication with HS256 JWT, required `sub`, `exp`, `iss`, and `aud` claims, plus 401 and authentication-configuration 503 errors. Owner identity is exclusively the verified subject. Other owners receive 404 for snapshot, artifacts, events, and exports. History lists only the caller's runs. The service must configure a dedicated secret of at least 32 characters. The secret remains on the backend. Production token issuance and rotation remain follow-up work.
- The browser must use fetch-based SSE with an Authorization header for this slice. Native EventSource cannot set that header. Reconnect with the last applied event ID, either in Last-Event-ID or `after`. The header takes precedence, including zero. Close after terminal run.updated or HTTP 204. Streams close when their token expires; renew the token and reconnect. Replay is retained for the lifetime of the run.

New records live in `v1_runs`, `v1_artifacts`, and `v1_events`, so legacy endpoints continue using their existing tables. Existing Supabase helpers perform independent HTTP calls and swallow database errors, which cannot provide the atomic writes this worker needs. The new store uses direct PostgreSQL transactions and can target the same PostgreSQL/Supabase database through DATABASE_URL. Export generation reuses RunContext and the existing generators. Fake results are labelled as demonstrations and partial exports identify missing workflow sections.

## Persistence and recovery

The additive schema migration is explicit and safe to repeat. Apply it before starting the new API or worker. The database role must be able to create the three tables during migration and perform runtime SELECT/INSERT/UPDATE operations afterward. Schema changes to existing legacy tables are unnecessary.

A claim uses SELECT FOR UPDATE SKIP LOCKED, a random claim token, and a 30-second expiry measured by the database clock. Each mutation locks the run row, validates the token and expiry, then validates expiry again at the final snapshot update. A stale attempt rolls back its artifact, status, and events together. Reclaims replace the token. The worker renews between steps and recomputes interrupted steps. Completed steps are recovered from PostgreSQL and skipped. A provider taking longer than its lease loses permission to publish; background renewal and live-provider timeout policy are deferred.

Each step completion inserts one immutable artifact, updates step state, appends artifact/step/evaluation events, and updates the snapshot in one transaction. Retrying the same artifact and content during an active claim returns the original artifact without new events. Different content conflicts. Per-run row locking serializes event allocation, and rolled-back transactions leave no event ID gaps. Terminal status has its own atomic snapshot/event transaction. A crash before that transaction is recovered by the next claim. Expected fake-provider failures produce partial or failed results with sanitized errors.

The runner topologically schedules the manifest frozen at submission. A step begins only after all dependencies have succeeded and their artifacts can be read from committed database state. The provider receives those persisted values. No in-memory context supplies upstream results.

## Dependency finding

The ZIP was not available in this checkout. Inspection confirms the described issue in these files.

- `backend/agents/layer2/agent8_pricing.py` reads `ctx.business_model`.
- `backend/agents/layer2/agent9_financials.py` reads `ctx.business_model` and `ctx.pricing_strategy`.
- `backend/agents/layer2/agent10_risk.py` reads `ctx.business_model`.
- `backend/orchestrator.py` launches business model, pricing, financials, and risk together through asyncio.gather in phase 2.

The fixture at `backend/tests/fixtures/business_dependencies.json` expresses those dependencies. Tests cover rejected early financial starts, an uncommitted pricing transaction, and a manifest whose display order opposes dependency order. Full live-agent migration remains a follow-up PR.

## Local setup

Use Python 3.11 and PostgreSQL. The existing root docker-compose.yml provides a local postgres service if Docker is available. Alternatively, use an existing PostgreSQL instance. Configure ignored backend/.env or the process environment using placeholders below. DATABASE_URL must be a direct `postgresql://` connection string accepted by psycopg, without a SQLAlchemy `+asyncpg` suffix.

```dotenv
DATABASE_URL=postgresql://<user>:<password>@localhost:5432/<database>
V1_JWT_SECRET=<random-secret-at-least-32-characters>
V1_JWT_ISSUER=cofounder-agent
V1_JWT_AUDIENCE=cofounder-api
```

From the repository root in PowerShell, install dependencies, migrate, and start the API.

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m backend.run_worker.migrate
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

In a second terminal with the same configuration, start the worker.

```powershell
.\.venv\Scripts\python.exe -m backend.run_worker.worker
# Consume at most one queued or expired run, then exit
.\.venv\Scripts\python.exe -m backend.run_worker.worker --once
```

For local development, obtain a short-lived token from a trusted issuer configured with the same secret, issuer, and audience. This PowerShell snippet mints a local test token into a shell variable without writing it to a file. Never give the signing secret to the frontend.

```powershell
$runToken = @'
import time
from jose import jwt
from backend.config import settings
assert len(settings.v1_jwt_secret) >= 32
print(jwt.encode({'sub': 'local-likhitha', 'exp': int(time.time()) + 900,
                  'iss': settings.v1_jwt_issuer, 'aud': settings.v1_jwt_audience},
                 settings.v1_jwt_secret, algorithm='HS256'))
'@ | .\.venv\Scripts\python.exe -
$runHeaders = @{ Authorization = "Bearer $runToken"; 'Idempotency-Key' = [guid]::NewGuid().ToString() }
$runBody = @{ problem = 'Help students discover relevant internships.' } | ConvertTo-Json
$run = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/runs -Headers $runHeaders -ContentType application/json -Body $runBody
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/runs/$($run.run_id)" -Headers $runHeaders
```

Keep `$runHeaders` to retry the same submission. Stream using a fetch-based SSE client or curl with the bearer header, and use the returned artifact hrefs against the backend origin. API and worker must point to the same database. An unavailable database returns a sanitized 503 rather than an accepted run.

## Checks

The tests use standard-library unittest and a real PostgreSQL database. TEST_DATABASE_URL must point to a disposable local test database with CREATE SCHEMA privileges. Each invocation creates a unique schema, applies the migration, truncates only its own tables between tests, and drops that schema afterward. Tests never connect to DATABASE_URL. The worker subprocess receives the isolated test connection string explicitly.

```powershell
$env:TEST_DATABASE_URL = 'postgresql://<test-user>:<test-password>@localhost:5432/<test-database>'
.\.venv\Scripts\python.exe -m unittest backend.tests.test_run_worker -v
.\.venv\Scripts\python.exe -m backend.contracts.tool --check
.\.venv\Scripts\python.exe -m pip check
```

Coverage includes concurrent duplicate submission, payload conflicts, owner-scoped keys, concurrent worker claims, restart/reclaim fencing, rollback between artifact/event publication, lease expiry during commit, immutable artifact retry, committed dependency reads, separate worker process execution, replay at every cursor, live streaming, owner isolation, JWT rejection, partial/failed results, all three export formats, and legacy route registration. Legacy live-provider execution and production Supabase connectivity require environment-specific integration checks.

Before staging, configure a trusted token issuer, the database connection, secret handling, and the frontend's bearer/SSE integration. The legacy demo routes retain their existing access behavior and need a separate staging exposure decision. No deployment is performed by these commands.
