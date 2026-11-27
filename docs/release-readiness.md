# CoFounder-Agent release readiness

Candidate base: `baeeda7` on `origin/main` (PRs #5 and #6). The release-readiness branch adds a v1 stream expiry fix and regression test. The React live build is suitable for a fake-provider staging exercise. Keep the legacy application in service until the production gates below pass.

## Local verification

- `python -m unittest discover -s backend/tests -v` passed all 25 tests with `TEST_DATABASE_URL` pointed at disposable PostgreSQL 17. The suite covers JWT rejection, owner isolation, SSE replay and expiry, durable reclaim, stale publication fencing, provider timeout, partial results, history, and export generation.
- A loopback HTTP smoke test used a separate Uvicorn process and worker with two synthetic users. The owner disconnected at event 1 and received events 2–18 on replay. The run succeeded, appeared only in the owner's history, and returned all three exports. The other user received 404 on the stream and exports.
- `python -m backend.contracts.tool --check` passed schema and deterministic fixture replay. The fixtures cover review pause and resume. The v1 API still needs a review-decision handler and durable resume. The worker records `not_evaluated`. A deterministic model-quality eval suite and CI gate still need implementation. `python -m pip check` also passed.
- In `frontend-vite`, `npm run lint`, `npm test` (14 tests), `npm run build`, and `npm run build:live` passed on Node 22.18. The tests cover mock review and partial results, wire replay, deduplication, reconnect, and authenticated requests. Use the live build with the staging ingress.
- In `frontend`, `npm run build` passed with Google Fonts network access. Keep the previously deployed Next.js artifact available for rollback.
- The repository has no checked-in CI workflow. GitHub listed only the dynamic Copilot review workflow and returned no workflow runs for `baeeda7`. GitHub returned no public deployment records. Staging verification still requires the ingress URL and synthetic test accounts.

## Gates before production cutover

1. Configure production sign-in and token refresh. Use two synthetic staging users to verify that history, runs, artifacts, SSE, and exports remain owner-scoped. Verify unauthenticated and expired-token behavior through the ingress. Review exposure of the legacy routes separately. The current React live UI expects a manually supplied bearer token.
2. Verify same-origin `/api/v1` routing with SSE buffering disabled and SPA navigation fallback. Disconnect mid-run, let several events commit, reconnect with the last applied cursor, then refresh. Compare chronological event IDs, artifact uniqueness, and final state with the authoritative snapshot. Repeat through the real ingress after an API restart.
3. Reclaim an interrupted run after stopping a worker mid-step. Verify no stale writes, contiguous event IDs, and no recomputation of completed steps. Repeat under concurrent claims and verify provider shutdown and worker recovery under staging timing.
4. Integrate and verify a live workflow, provider deadlines, capability-compatible fallback, and durable per-run budget accounting across restart. Review and resume must bind the founder’s decision to the exact artifact revision and survive worker restart.
5. Compare successful and partial Markdown, PDF, and PPTX reports against representative legacy results. Check section coverage, visual rendering, notice text, and legacy history continuity. Current v1 uses separate history tables and its exports cover the four-step demonstration. Decide how users will access prior history before the switch.
6. Add CI enforcement for PostgreSQL integration, frontend checks, and deterministic model-quality evaluation. Cross-review the runtime authentication and idempotency behavior against the published v1 schema.

## Live evaluation baseline

Await an approved staging URL, synthetic credentials, a provider profile, and an approved cost ceiling. A proposed workload is ten fixed, labeled synthetic runs at concurrency two, with matched inputs across builds. Record the exact build, prompt and model profile, successful and partial outcomes, fallback attempts, submit-to-terminal latency, time to first artifact, token totals, and estimated cost. Report median and slowest observed latency for this sample. Reserve budget before each attempt, count retries against the cap, and stop at exhaustion. Record provider-free measurements separately from live-provider metrics.

## Rollback

The migration creates separate v1 tables and indexes. Keep those tables and data in place during an app rollback. Retain the previously deployed frontend artifact, backend/worker artifact, and their configuration. Verify the precise deployed revisions in staging. The repository comparison uses `7449da1`, the merge before PRs #5 and #6 reached main. The extracted backend at that revision submitted and completed a `fake-business-v1` run on the current schema after applying the migration twice. The current backend read all four artifacts.

Before restoring a prior v1 worker, stop submissions and drain runs for workflow versions the rollback worker cannot safely execute. Keep a compatible worker available for any remaining newer runs. The worker pins its fake workflow by manifest version, but live prompts and model profiles are not independently versioned or persisted. Restoring live prompt/model behavior requires the prior build and configuration and verification that its models remain available. Rehearse rollback with a staging copy of the current schema and verify history, replay, and exports before traffic resumes.

## Draft PR

**Title** — Verify the React cutover candidate and enforce SSE token expiry

This PR documents local release verification, staging acceptance criteria, and rollback steps. It also closes an SSE stream when authorization expires while PostgreSQL is returning an event batch. Reconnecting with a fresh token can replay those persisted events.

The production switch and legacy Next.js removal remain separate review items. Full cutover requires live authentication, staging SSE and recovery verification, provider budget and quality evaluation, durable review/resume, and export/history parity.
