# Final project verification

This report records the initial LangGraph cleanup. See the [current README](../README.md) for startup commands and the current compatibility policy.

Starting source was `18b58c93ee3fb05ee4fcb6c091ced850393c6db3` on canonical `main`, after PRs #16 through #18. The cleanup branch was based on a clean isolated worktree. The original checkout contained an untracked file and was left intact.

## Architecture and agent audit

One Vite React app calls one mounted FastAPI v1 API. One worker advances a LangGraph StateGraph. PostgreSQL owns run data, immutable artifact revisions, the event log, claim and budget ledgers, and the graph checkpoints. The run UUID is the checkpoint thread ID. Fence checks guard both application transactions and checkpoint writes. The API and worker retain the same REST and SSE contracts.

The [current compiled dependency graph](../README.md#current-compiled-dependency-graph) comes from the reviewed graph. The [migration report](archive/langgraph-orchestration.md) archives the earlier graph. All agents below register as individual LangGraph nodes through `LIVE_STEPS`. The node hydrates a private, frozen input adapter from committed artifact bodies, runs the registered prompt and research integration through the shared Groq adapter in live mode, validates the output, and transactionally writes the artifact, evaluation, and public events. The graph reducer receives status and references. It holds no provider clients or mutable shared agent context. Fake mode supplies backend fixtures at the same node boundaries.

| Node and agent source | Required committed inputs | Optional inputs | Output model | Research |
| --- | --- | --- | --- | --- |
| `problem_refined`<br>[Problem Refiner](../backend/agents/layer0/agent0_refiner.py) | None | None | `RefinedProblem` | None |
| `startup_idea`<br>[Idea Generator](../backend/agents/layer1/agent1_idea.py) | `problem_refined` | None | `StartupIdea` | SerpAPI |
| `market_research`<br>[Market Research](../backend/agents/layer1/agent2_market.py) | `problem_refined`, `startup_idea` | None | `MarketResearch` | SerpAPI and FRED |
| `competitor_analysis`<br>[Competitor Analysis](../backend/agents/layer1/agent3_competitors.py) | `problem_refined`, `startup_idea` | None | `CompetitorAnalysis` | SerpAPI |
| `customer_personas`<br>[Customer Personas](../backend/agents/layer1/agent4_personas.py) | `problem_refined`, `startup_idea`, `market_research` | None | `CustomerPersonas` | None |
| `product_design`<br>[Product Designer](../backend/agents/layer2/agent5_product.py) | `problem_refined`, `startup_idea`, `customer_personas` | None | `ProductDesign` | None |
| `mvp_roadmap`<br>[MVP Roadmap](../backend/agents/layer2/agent6_roadmap.py) | `startup_idea`, `product_design` | None | `Roadmap` | None |
| `business_model`<br>[Business Model](../backend/agents/layer2/agent7_bizmodel.py) | `startup_idea`, `market_research`, `competitor_analysis` | None | `BusinessModel` | None |
| `pricing_strategy`<br>[Pricing Strategy](../backend/agents/layer2/agent8_pricing.py) | `startup_idea`, `business_model` | `competitor_analysis`, `customer_personas` | `Pricing` | None |
| `financial_projections`<br>[Financial Projections](../backend/agents/layer2/agent9_financials.py) | `startup_idea`, `market_research`, `business_model`, `pricing_strategy` | None | `Financials` | FRED |
| `risk_register`<br>[Risk Analyst](../backend/agents/layer2/agent10_risk.py) | `startup_idea`, `business_model` | None | `RiskRegister` | None |
| `tech_architecture`<br>[Technical Architecture](../backend/agents/layer3/agent11_architecture.py) | `startup_idea`, `product_design` | `market_research` | `Architecture` | None |
| `database_schema`<br>[Database Schema](../backend/agents/layer3/agent12_database.py) | `startup_idea`, `product_design`, `business_model`, `customer_personas` | None | `DatabaseSchema` | None |
| `security_compliance`<br>[Security and Compliance](../backend/agents/layer3/agent13_security.py) | `startup_idea`, `product_design` | None | `SecurityCompliance` | None |
| `pitch_deck`<br>[Pitch Deck](../backend/agents/layer4/agent14_pitchdeck.py) | `problem_refined`, `startup_idea`, `market_research`, `business_model`, `pricing_strategy`, `financial_projections` | `competitor_analysis` | `PitchDeck` | None |
| `executive_summary`<br>[Executive Summary](../backend/agents/layer4/agent15_execsummary.py) | `problem_refined`, `startup_idea`, `market_research`, `business_model`, `pricing_strategy`, `financial_projections` | `risk_register` | `ExecutiveSummary` | None |

Required failures become blocked dependents; failed optional producers settle their graph edges and supply no content. Market and competitor research can overlap. A valid forecast unlocks both investor nodes. Risk is optional to the executive summary and can fail independently. Pricing review uses native `interrupt()` and scoped `Command(resume=...)`. The optional executive-summary decision gates final application status after graph execution. It requires no agent continuation.

## Cleanup and targeted fixes

- Removed the 24 tracked Next.js files, including its package manifests, lockfile, routes, and scripts. React covers the maintained workspace. Removed the nine disabled route, orchestrator, and legacy database adapter files. Their tracked source remains recoverable from the starting commit. Legacy database tables and the v1 migrations remain intact.
- Replaced the separate worker scheduler with a compatibility StateGraph for pinned pre-checkpoint manifests. Historical live runs retain their optional joins. Older demo runs retain their required edges and their already-available optional-input behavior. Finished application steps are reused and the remaining jobs checkpoint under their existing run UUID.
- Kept all 16 agent files, prompts, parsers, and research integrations. Removed execution and fallback writes to shared mutable context. Research returns explicit evidence and the export code has a separate per-report data object. Recomputed the source-derived fingerprints for the refactored renderers. Existing prompt versions retain their rendering instructions. New reviewed runs pin v3.
- The archived partial Groq run recorded generic finance and risk validation failures without the rejected responses. The exact historical malformed fields cannot be reconstructed. V3 increases the two completion allowances, gives precise JSON and calculation instructions, and permits at most one regeneration after a structural or domain validation failure. The existing attempt limit, deadline and per-run reservations apply to both completions. Validation still rejects invalid output and no missing values are supplied.
- The PDF now labels unavailable estimated infrastructure cost using the same formatter as Markdown. Both reports carry the approved figures when present.
- Aligned the PostgreSQL-only local compose setup, environment sample, CI browser checks, and Windows startup instructions with the maintained app. Development can use loopback HTTP Supabase with the same asymmetric JWT and owner checks. Test API HS256 remains restricted to local environments without a Supabase issuer.
- Removed direct dependencies on `supabase`, `jinja2`, `bcrypt`, `passlib`, `aioredis`, `redis`, `mistune`, `markdown2`, `sse-starlette`, and `python-multipart`. Supabase browser authentication, native FastAPI streaming, and the report libraries remain. The standalone React lockfile is still authoritative.

## Verification

### Commands and test results

The npm commands in this table ran from `frontend-vite/`. The Windows run used Python 3.11, PostgreSQL 18.1 on disposable loopback port 55458, Edge, and Node 22.21.1 for the secure preview. The local Supabase CLI stack used an ES256 key and two newly provisioned test users. The existing databases and accounts were outside this lab.

| Command | Result |
| --- | --- |
| `python -m venv .venv`, `.venv/Scripts/python.exe -m pip install -r backend/requirements.txt`, `.venv/Scripts/python.exe -m pip check` | Clean install and dependency check passed |
| `.venv/Scripts/python.exe -m unittest discover -s backend/tests -v` with `TEST_DATABASE_URL` set to the disposable database | 79/79 passed in 432.764 s with no skips. The focused full-agent export regression passed again after the PDF cost-label change (77.645 s). |
| `.venv/Scripts/python.exe -m backend.contracts.tool --check --check-runtime` | Passed generated and mounted REST, SSE schema, examples, replay and reconnect fixtures |
| `npm.cmd ci --no-audit --no-fund` | Clean install passed with the maintained lockfile |
| `npm.cmd run lint`, `npm.cmd test`, `npm.cmd run build:live` | Lint, 33 frontend tests and production build passed |
| `$env:PLAYWRIGHT_CHROMIUM_CHANNEL='msedge'; npm.cmd run test:browser` | 7/7 browser fixture tests passed |
| `docker compose config --quiet`, `git diff --check` | Passed |

A Playwright smoke check started the frontend in explicit Vite mock mode and verified its label and form. The full-stack run used the production React build against the deterministic backend.

The older prompt compatibility check rendered all 16 agents through each of the three older bundles with fixture research and provider responses. The original and cleaned trees produced the same combined prompt-and-output hash `7e2e6c9edf5a23355f507b077472caa09826026ce67559b1d8d50eaebd4810a4` for those inputs.

The timing regression initially exposed slow Windows provider startup. At a six-second test deadline, the healthy business-model child timed out before the test reached pricing. At sixteen seconds that child completed in about 12 seconds, the healthy risk sibling completed, and only the deliberately hung pricing child timed out. The tests now allow for the measured startup and transport overhead while still checking timeout, independent completion, reservation retention, and subsequent worker recovery. Runtime provider limits are unchanged.

### Full local browser run

The acceptance driver ran via Node 22.21.1 with Playwright Edge and Vite's live build and HTTPS preview. It used the application migrations, real FastAPI, two separate `python -m backend.run_worker.worker --once` processes, real local Supabase Auth, and backend `V1_PROVIDER_MODE=fake`. The startup idea from the request went through the real form. The agent bodies and metrics were deterministic fixture values.

- The two users performed actual Supabase password sign-in. The owner persisted a session across reload, renewed it on the provider after expiring the cached client metadata, and signed out. The browser protected the history route and reopened the owner's run. Foreign snapshot, artifact, SSE, review, and export requests returned 404, and the foreign history was empty.
- The run moved from queued to the pricing checkpoint and resumed on approval in the second worker. The browser compared immutable pricing revisions; only the financial agent executed twice. The pitch deck and summary used the new financial revision. All 16 steps succeeded and 18 immutable artifact references remained. The run UUID had 12 PostgreSQL checkpoint rows. Full SSE replay returned 81 consecutive events and replay after the review cursor matched the full event log suffix.
- A second case refreshed the browser while the persisted run status was running. It cut the browser connection while the worker completed more steps, then reconnected and recovered the pricing checkpoint. That run also recorded 81 consecutive events across three browser SSE requests. The interrupted artifact request needed the checkpoint UI’s Retry button. Revision, approval, resume and the three downloads then worked.
- The successful run took **28.719 seconds** from submission to the terminal snapshot. The first worker phase took **12.030 seconds** and the resume phase took **14.077 seconds** as observed by the acceptance driver. These windows include worker process startup. The pricing step window spans founder review. The database contained **zero provider attempts** for this run. The PostgreSQL suite separately exercises actual adapter calls against a simulated Groq transport, including fallback, reservation, timeout and quota behavior.
- Edge saved the PDF, PowerPoint, and Markdown over local HTTPS with the expected filenames. The bytes matched the authenticated HTTP responses. The PDF opened and its first page rendered (seven pages total), PowerPoint opened with one cover and 12 generated slides, and Markdown opened as UTF-8 (201 lines). All three carried the revised $6,600 fixture ARR. PDF and Markdown included technical architecture, generated SQL, and security sections and marked the absent infrastructure cost as unavailable.
- Opened deterministic rejection exports separately. The PDF had five pages, the PowerPoint had one cover slide, and the Markdown had 117 lines. All three identified the missing Financial Projections and Pitch Deck. The draft forecast remained in immutable history.

The automated browser tests use controlled responses to exercise disconnect and token renewal, stale or unauthorized decisions, recovery after missing messages, error states, and Save-link behavior. The PostgreSQL suite covers restart and claim fencing, duplicate and stale decisions, approval and rejection, selectively recomputed revisions, branch-scoped failures, and concurrent budget enforcement. The local browser rendered the finance chart and table, risk register, technical and database outputs, pitch preview, and executive summary, and had no horizontal overflow at 390 CSS pixels.

### All 16 outcomes

The last step window is taken from PostgreSQL timestamps. The historical Groq column describes the archived partial run.

| Node | Local result | Last step window | Attempts | Latest heuristic | Archived Groq result |
| --- | --- | ---: | ---: | --- | --- |
| `problem_refined` | succeeded | 84 ms | 1 | passed (1) | Published |
| `startup_idea` | succeeded | 79 ms | 1 | passed (1) | Published |
| `market_research` | succeeded | 93 ms | 1 | needs_review (0.8) | Published |
| `competitor_analysis` | succeeded | 88 ms | 1 | needs_review (0.8) | Published |
| `customer_personas` | succeeded | 106 ms | 1 | passed (1) | Published |
| `product_design` | succeeded | 95 ms | 1 | passed (1) | Published |
| `mvp_roadmap` | succeeded | 94 ms | 1 | passed (1) | Published |
| `business_model` | succeeded | 99 ms | 1 | passed (1) | Published |
| `pricing_strategy` | succeeded | 5,333 ms | 1 | passed (1) | Published |
| `financial_projections` | succeeded | 261 ms | 2 | needs_review (0.6) | Failed validation |
| `risk_register` | succeeded | 97 ms | 1 | needs_review (0.75) | Failed validation |
| `tech_architecture` | succeeded | 94 ms | 1 | needs_review (0.75) | Published |
| `database_schema` | succeeded | 114 ms | 1 | passed (1) | Published |
| `security_compliance` | succeeded | 90 ms | 1 | passed (1) | Published |
| `pitch_deck` | succeeded | 202 ms | 1 | needs_review (0.8) | Blocked |
| `executive_summary` | succeeded | 186 ms | 1 | passed (1) | Blocked |

## Limits and local startup

The actual Groq rerun was skipped because the required zero-spend account status could not be verified for an authorized key. No actual generation, research quota-consuming calls, or paid evaluation calls were made during this cleanup. The archived real run completed 12 agents and its metrics remain in [the historical report](archive/release-readiness-verification.md). The historical model's rejected response bodies were unavailable. The deterministic latencies and fixture values describe only the local test workload.

Follow the complete [Windows setup](../README.md#run-locally-on-windows). The entry points are:

```powershell
.\.venv\Scripts\python.exe -m backend.run_worker.migrate
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
.\.venv\Scripts\python.exe -m backend.run_worker.worker
npm.cmd --prefix frontend-vite run dev:live
```

Repository layout is `backend/` for API, agents, worker and exports, `frontend-vite/` for React, `shared/contracts/` for versioned fixtures and schemas, and `docs/` for current verification and archived reports.

## Verdict

**COMPLETE WITH EXPLICIT VERIFICATION LIMITATIONS**

## Draft PR

**Finish the local LangGraph cleanup and verify the 16-agent workspace**

Retire the disabled Next.js and backend execution paths. Route historical pinned jobs through LangGraph while preserving existing data and recovery. Keep all 16 agent prompts and research integrations, and add budgeted finance and risk output recovery. Document Windows startup, test the local workspace, and record the provider verification limits.
