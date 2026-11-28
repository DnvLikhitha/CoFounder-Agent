"""Transactions serialize each run and atomically publish its state and events."""
from base64 import b64decode, urlsafe_b64encode
from contextlib import contextmanager
from datetime import datetime
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.contracts.v1 import Artifact, EVENT_ADAPTER, ReviewReceipt, RunSnapshot, RunSummary
from backend.llm.profiles import PROFILE_VERSION, PROMPT_VERSION
from backend.run_worker import workflow
from backend.run_worker.evaluator import domain_errors, failed_evaluation, heuristic
from backend.run_worker.live_agents import REVIEWED_PROMPT_VERSION

TERMINAL = {"succeeded", "partial", "failed"}
STEP_TERMINAL = TERMINAL | {"skipped"}
PRICING = "pricing_strategy"
FINANCIALS = "financial_projections"


class StoreError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code = status, code


class LostClaim(Exception):
    pass


def now(connection):
    return connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"].isoformat()


def latest_artifacts(snapshot):
    return {ref["step_id"]: ref for ref in snapshot["artifacts"]}


def decode_history_cursor(cursor):
    try:
        value = b64decode(cursor, altchars=b"-_", validate=True).decode("ascii")
        timestamp, run_id = value.split("|")
        timestamp = datetime.fromisoformat(timestamp)
        if timestamp.utcoffset() is None:
            raise ValueError("Cursor timestamp needs an offset")
        return timestamp, UUID(run_id)
    except ValueError:
        raise StoreError(422, "validation_error", "Invalid history cursor") from None


class Store:
    def __init__(self, dsn):
        self.dsn = dsn

    def connect(self, **options):
        if not self.dsn:
            raise StoreError(503, "service_unavailable", "Database is not configured")
        return psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5, **options)

    def migrate(self):
        with self.connect() as connection:
            # Serialize concurrent invocations of this additive migration.
            connection.execute("SELECT pg_advisory_xact_lock(71894021)")
            connection.execute(Path(__file__).with_name("schema.sql").read_text())
            self._check_retired_runs(connection)
        from backend.run_worker.checkpoints import migrate_checkpoints
        migrate_checkpoints(self)

    @staticmethod
    def _check_retired_runs(connection):
        unfinished = connection.execute(
            """SELECT 1 FROM v1_runs WHERE snapshot->'manifest'->>'version' = ANY(%s)
               AND (snapshot->>'status') NOT IN ('succeeded', 'partial', 'failed') LIMIT 1""",
            (list(workflow.RETIRED_DEMO_VERSIONS),),
        ).fetchone()
        if unfinished:
            raise StoreError(409, "retired_runs_pending",
                             "Finish pending four-agent demo runs with the previous worker before upgrading.")

    def check_retired_runs(self):
        with self.connect() as connection:
            self._check_retired_runs(connection)

    def submit(self, owner, key, body, *, version=workflow.REVIEWED_VERSION, token_limit=500_000, cost_limit=250_000_000,
               require_review=False, graph_mode=None, pricing_review=False, llm_evaluation=False):
        with self.connect() as connection:
            timestamp, run_id = now(connection), str(uuid4())
            manifest = workflow.current_manifest(version)
            snapshot = dict(contract_version="1.0", run_id=run_id, input=body,
                            status="queued", created_at=timestamp, updated_at=timestamp,
                            completed_at=None, error=None, last_event_id=0,
                            manifest=manifest.model_dump(mode="json"),
                            steps=[dict(step_id=step.step_id, status="queued", attempt=0,
                                        started_at=None, completed_at=None, error=None)
                                   for step in manifest.steps],
                            artifacts=[], evaluations=[], pending_review=None)
            RunSnapshot.model_validate(snapshot)
            if (manifest.version in workflow.GRAPH_VERSIONS) != (graph_mode in {"live", "fake"}):
                raise ValueError("A LangGraph run requires an explicit provider mode")
            live = manifest.version == workflow.LIVE_VERSION or graph_mode == "live"
            prompt_version = REVIEWED_PROMPT_VERSION if manifest.version == workflow.REVIEWED_VERSION else PROMPT_VERSION
            inserted = connection.execute(
                """INSERT INTO v1_runs (run_id, owner_id, submission_key, input,
                   initial_snapshot, snapshot, created_at, model_profile, prompt_version, token_limit,
                   cost_limit_nanousd, require_review, graph_mode, pricing_review, llm_evaluation)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (owner_id, submission_key) DO NOTHING RETURNING run_id""",
                (run_id, owner, key, Jsonb(body), Jsonb(snapshot), Jsonb(snapshot), timestamp,
                 PROFILE_VERSION if live else None, prompt_version if live or graph_mode else None,
                 token_limit if live else None, cost_limit if live else None, require_review, graph_mode,
                 pricing_review, llm_evaluation and live)).fetchone()
            if inserted:
                return snapshot
            row = connection.execute(
                "SELECT input, initial_snapshot FROM v1_runs WHERE owner_id=%s AND submission_key=%s",
                (owner, key)).fetchone()
            if row["input"] != body:
                raise StoreError(409, "state_conflict", "Submission key was used with different input")
            return row["initial_snapshot"]

    def heartbeat(self, mode):
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO v1_worker_heartbeats (mode, seen_at) VALUES (%s,clock_timestamp())
                   ON CONFLICT (mode) DO UPDATE SET seen_at=clock_timestamp()""", (f"{mode}:{workflow.REVIEWED_VERSION}",))

    def ready(self, mode):
        from backend.run_worker.checkpoints import checkpoint_schema_ready

        with self.connect() as connection:
            connection.execute("SET LOCAL statement_timeout = '3s'")
            # Resolve the runtime relations and migrated columns using the configured database role.
            connection.execute("""
                SELECT r.token_limit, r.cost_limit_nanousd, r.prompt_version, r.model_profile, r.require_review,
                       r.graph_mode, r.graph_interrupt_id, r.graph_resume_id, r.graph_resume_payload, r.pricing_review,
                       r.llm_evaluation, a.body, e.body, l.charged_tokens, l.retry_at, l.purpose, l.execution_revision, d.receipt
                FROM v1_runs r LEFT JOIN v1_artifacts a USING (run_id) LEFT JOIN v1_events e USING (run_id)
                LEFT JOIN v1_llm_attempts l USING (run_id) LEFT JOIN v1_review_decisions d USING (run_id)
                LIMIT 0""")
            if not checkpoint_schema_ready(connection):
                return False
            return connection.execute(
                """SELECT 1 FROM v1_worker_heartbeats WHERE mode=%s
                   AND seen_at > clock_timestamp() - interval '45 seconds'""", (f"{mode}:{workflow.REVIEWED_VERSION}",)
            ).fetchone() is not None

    def snapshot(self, owner, run_id):
        with self.connect() as connection:
            row = connection.execute("SELECT snapshot FROM v1_runs WHERE run_id=%s AND owner_id=%s",
                                     (run_id, owner)).fetchone()
            if row is None:
                raise StoreError(404, "not_found", "Run not found")
            return row["snapshot"]

    def history(self, owner, limit, cursor):
        timestamp, run_id = decode_history_cursor(cursor) if cursor is not None else (None, None)
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT created_at, run_id, snapshot FROM v1_runs WHERE owner_id=%s
                   AND (%s::timestamptz IS NULL OR (created_at, run_id) < (%s, %s))
                   ORDER BY created_at DESC, run_id DESC LIMIT %s""",
                (owner, timestamp, timestamp, run_id, limit + 1)).fetchall()
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = page[-1]
            boundary = f'{last["created_at"].isoformat()}|{last["run_id"]}'
            next_cursor = urlsafe_b64encode(boundary.encode("ascii")).decode("ascii")
        return {
            "runs": [{name: row["snapshot"][name] for name in RunSummary.model_fields} for row in page],
            "next_cursor": next_cursor,
        }

    def artifact(self, owner, run_id, artifact_id):
        with self.connect() as connection:
            row = connection.execute(
                """SELECT a.body FROM v1_artifacts a JOIN v1_runs r USING (run_id)
                   WHERE r.owner_id=%s AND r.run_id=%s AND a.artifact_id=%s""",
                (owner, run_id, artifact_id)).fetchone()
            if row is None:
                raise StoreError(404, "not_found", "Artifact not found")
            return row["body"]

    def events(self, owner, run_id, after, limit=100):
        with self.connect() as connection:
            connection.execute("SET LOCAL statement_timeout = '3s'")
            rows = connection.execute(
                """SELECT e.body FROM v1_events e JOIN v1_runs r USING (run_id)
                   WHERE r.owner_id=%s AND r.run_id=%s AND e.event_id>%s
                   ORDER BY e.event_id LIMIT %s""", (owner, run_id, after, limit)).fetchall()
            return [row["body"] for row in rows]

    def _emit(self, connection, snapshot, kind, data, timestamp):
        snapshot["last_event_id"] += 1
        snapshot["updated_at"] = timestamp
        event = dict(contract_version="1.0", run_id=snapshot["run_id"],
                     event_id=snapshot["last_event_id"], occurred_at=timestamp, type=kind, data=data)
        EVENT_ADAPTER.validate_python(event)
        connection.execute("INSERT INTO v1_events VALUES (%s,%s,%s)",
                           (snapshot["run_id"], event["event_id"], Jsonb(event)))

    def _run_status(self, connection, snapshot, status, timestamp, error=None):
        data = dict(status=status, updated_at=timestamp,
                    completed_at=timestamp if status in TERMINAL else None, error=error)
        snapshot.update(data)
        self._emit(connection, snapshot, "run.updated", data, timestamp)

    def claim(self, lease_seconds=30, *, versions=None, prompt_versions=None, model_profiles=None,
              graph_mode=None, active_limit=None):
        if lease_seconds <= 0:
            raise ValueError("Lease must be positive")
        prompts = None if prompt_versions is None else list(prompt_versions)
        profiles = None if model_profiles is None else list(model_profiles)
        with self.connect() as connection:
            if active_limit is not None:
                connection.execute("SELECT pg_advisory_xact_lock(71894023)")
                active = connection.execute("""SELECT count(*) AS active FROM v1_runs
                    WHERE snapshot->>'status'='running' AND lease_until > clock_timestamp()""").fetchone()
                if active["active"] >= active_limit:
                    return None
            row = connection.execute(
                """SELECT * FROM v1_runs WHERE snapshot->>'status' IN ('queued','running')
                   AND snapshot->'manifest'->>'version' = ANY(%s)
                   AND (%s::text[] IS NULL OR prompt_version = ANY(%s::text[]))
                   AND (%s::text[] IS NULL OR model_profile = ANY(%s::text[]))
                   AND (%s::text IS NULL OR graph_mode=%s
                        OR (%s::text = 'live' AND graph_mode IS NULL AND snapshot->'manifest'->>'version' = %s))
                   AND (graph_interrupt_id IS NULL OR graph_interrupt_id=graph_resume_id)
                   AND (lease_until IS NULL OR lease_until <= clock_timestamp())
                   ORDER BY created_at, run_id FOR UPDATE SKIP LOCKED LIMIT 1""",
                (list(workflow.WORKFLOWS if versions is None else versions), prompts, prompts,
                 profiles, profiles, graph_mode, graph_mode, graph_mode, workflow.LIVE_VERSION)).fetchone()
            if row is None:
                return None
            token, snapshot = str(uuid4()), row["snapshot"]
            if snapshot["status"] == "queued":
                self._run_status(connection, snapshot, "running", now(connection))
            self._close_reservations(connection, row["run_id"])
            connection.execute(
                """UPDATE v1_runs SET claim_token=%s,
                   lease_until=clock_timestamp() + %s * interval '1 second', snapshot=%s
                   WHERE run_id=%s""", (token, lease_seconds, Jsonb(snapshot), row["run_id"]))
            return str(row["run_id"]), token

    @staticmethod
    def _close_reservations(connection, run_id, step_id=None):
        connection.execute(
            """UPDATE v1_llm_attempts SET status='unknown', finished_at=clock_timestamp()
               WHERE run_id=%s AND status='reserved' AND (%s::text IS NULL OR step_id=%s)""",
            (run_id, step_id, step_id))

    @contextmanager
    def _claimed(self, run_id, token, *, release=False):
        with self.connect() as connection:
            row = connection.execute("SELECT snapshot FROM v1_runs WHERE run_id=%s FOR UPDATE",
                                     (run_id,)).fetchone()
            valid = connection.execute(
                """SELECT 1 FROM v1_runs WHERE run_id=%s AND claim_token=%s
                   AND lease_until > clock_timestamp() AND snapshot->>'status'='running'""",
                (run_id, token)).fetchone()
            if row is None or valid is None:
                raise LostClaim()
            snapshot = row["snapshot"]
            yield connection, snapshot
            RunSnapshot.model_validate(snapshot)
            saved = connection.execute(
                """UPDATE v1_runs SET snapshot=%s, claim_token=CASE WHEN %s THEN NULL ELSE claim_token END,
                   lease_until=CASE WHEN %s THEN NULL ELSE lease_until END WHERE run_id=%s AND claim_token=%s
                   AND lease_until > clock_timestamp() RETURNING run_id""",
                (Jsonb(snapshot), release, release, run_id, token)).fetchone()
            if saved is None:
                raise LostClaim()  # Rolls back artifact and events too.

    def renew(self, run_id, token, lease_seconds=30):
        if lease_seconds <= 0:
            raise ValueError("Lease must be positive")
        with self._claimed(run_id, token) as (connection, snapshot):
            renewed = connection.execute(
                """UPDATE v1_runs SET lease_until=clock_timestamp() + %s * interval '1 second'
                   WHERE run_id=%s AND lease_until > clock_timestamp() RETURNING run_id""",
                (lease_seconds, run_id)).fetchone()
            if renewed is None:
                raise LostClaim()

    def live_configuration(self, run_id, token):
        with self._claimed(run_id, token) as (connection, _):
            return connection.execute(
                "SELECT model_profile, prompt_version FROM v1_runs WHERE run_id=%s", (run_id,)
            ).fetchone()

    def graph_configuration(self, run_id, token):
        with self._claimed(run_id, token) as (connection, snapshot):
            row = connection.execute("""SELECT graph_mode, model_profile, prompt_version, graph_resume_id,
                                              graph_resume_payload, pricing_review, llm_evaluation
                                       FROM v1_runs WHERE run_id=%s""", (run_id,)).fetchone()
            return {**row, "input": snapshot["input"], "manifest": snapshot["manifest"]}

    def park_graph(self, run_id, token, interrupt_id, *, public=False):
        with self._claimed(run_id, token, release=True) as (connection, snapshot):
            connection.execute("""UPDATE v1_runs SET graph_interrupt_id=%s, graph_resume_id=NULL, graph_resume_payload=NULL
                                  WHERE run_id=%s""", (interrupt_id, run_id))
            if public:
                timestamp = now(connection)
                artifact = latest_artifacts(snapshot)[PRICING]
                step = next(s for s in snapshot["steps"] if s["step_id"] == PRICING)
                step.update(status="awaiting_review", completed_at=None)
                self._emit(connection, snapshot, "step.updated", step, timestamp)
                self._request_pricing_review(connection, snapshot, artifact["artifact_id"], timestamp)
                self._run_status(connection, snapshot, "awaiting_review", timestamp)

    def _request_pricing_review(self, connection, snapshot, artifact_id, timestamp):
        pending = dict(review_id=str(uuid4()), step_id=PRICING, artifact_ids=[artifact_id], revision_kind="pricing",
                       prompt="Approve the pricing assumptions, reject them, or propose revised tier prices.",
                       created_at=timestamp)
        snapshot["pending_review"] = pending
        self._emit(connection, snapshot, "review.requested", pending, timestamp)

    def authorize_graph_resume(self, owner, run_id, interrupt_id):
        """Private approval entry point. Prompt 14 will call this from its review transaction."""
        with self.connect() as connection:
            row = connection.execute("""SELECT graph_interrupt_id, graph_resume_id, pricing_review, snapshot->>'status' AS status
                                       FROM v1_runs WHERE run_id=%s AND owner_id=%s FOR UPDATE""",
                                     (run_id, owner)).fetchone()
            if row is None:
                raise StoreError(404, "not_found", "Run not found")
            if row["pricing_review"]:
                raise StoreError(409, "state_conflict", "This run requires a persisted review decision")
            if row["graph_resume_id"] == interrupt_id and interrupt_id:
                return
            if not interrupt_id or row["graph_interrupt_id"] != interrupt_id or row["status"] != "running":
                raise StoreError(409, "state_conflict", "Run has no matching graph interrupt")
            connection.execute("UPDATE v1_runs SET graph_resume_id=%s WHERE run_id=%s", (interrupt_id, run_id))

    def graph_step_outcome(self, run_id, token, step_id):
        with self._claimed(run_id, token) as (connection, snapshot):
            version = snapshot["manifest"]["version"]
            spec = workflow.WORKFLOWS[version][step_id]
            definition = next(step for step in snapshot["manifest"]["steps"] if step["step_id"] == step_id)
            states = {step["step_id"]: step for step in snapshot["steps"]}
            step = states[step_id]
            if step["status"] not in STEP_TERMINAL:
                raise StoreError(409, "state_conflict", "Graph step outcome is not committed")
            ref = latest_artifacts(snapshot).get(step_id)
            artifact = connection.execute("""SELECT body->'reference' AS reference,
                       (body->'content') ? 'tool_evidence' AS research,
                       (body->'content') ? 'assumptions' AS assumptions
                       FROM v1_artifacts WHERE run_id=%s AND artifact_id=%s""",
                                          (run_id, ref["artifact_id"])).fetchone() if ref and step["status"] in {"succeeded", "partial"} else None
            if (step["status"] in {"succeeded", "partial"}) != bool(artifact):
                raise StoreError(409, "state_conflict", "Graph step artifact is inconsistent")
            outcome = {
                "status": step["status"], "error": step["error"], "artifact": artifact["reference"] if artifact else None,
                "required": {key: states[key]["status"] for key in definition["depends_on"]},
                "optional": {key: states[key]["status"] for key in spec.optional if key in states},
                "research_artifact_id": ref["artifact_id"] if artifact and artifact["research"] else None,
                "assumptions_artifact_id": ref["artifact_id"] if artifact and artifact["assumptions"] else None,
            }
            if snapshot["manifest"]["version"] == workflow.REVIEWED_VERSION:
                outcome["attempt"] = step["attempt"]
            return outcome

    def is_demo(self, owner, run_id):
        with self.connect() as connection:
            row = connection.execute("SELECT graph_mode FROM v1_runs WHERE run_id=%s AND owner_id=%s",
                                     (run_id, owner)).fetchone()
            return row is not None and row["graph_mode"] == "fake"

    def begin_step(self, run_id, token, step_id):
        with self._claimed(run_id, token) as (connection, snapshot):
            definition = next(s for s in snapshot["manifest"]["steps"] if s["step_id"] == step_id)
            step = next(s for s in snapshot["steps"] if s["step_id"] == step_id)
            if step["status"] not in {"queued", "running"}:
                return None
            states = {s["step_id"]: s["status"] for s in snapshot["steps"]}
            required = definition["depends_on"]
            blocked = [name for name in required if states[name] in {"partial", "failed", "skipped"}]
            if blocked:
                timestamp = now(connection)
                error = dict(code="dependency_blocked", message="Required input unavailable: " + ", ".join(blocked),
                             retryable=False)
                step.update(status="skipped", completed_at=timestamp, error=error)
                self._emit(connection, snapshot, "step.updated", step, timestamp)
                return None
            upstream = {}
            refs = latest_artifacts(snapshot)
            optional = workflow.WORKFLOWS[snapshot["manifest"]["version"]][step_id].optional
            available_optional = [name for name in optional if states.get(name) == "succeeded" and name not in required]
            for dependency in (*required, *available_optional):
                ref = refs.get(dependency)
                artifact_id = ref["artifact_id"] if ref else (
                    dependency if snapshot["manifest"]["version"] != workflow.REVIEWED_VERSION else None)
                artifact = connection.execute("SELECT body FROM v1_artifacts WHERE run_id=%s AND artifact_id=%s",
                                              (run_id, artifact_id)).fetchone() if artifact_id else None
                if artifact is None and dependency in available_optional:
                    continue
                if states[dependency] != "succeeded" or artifact is None:
                    raise StoreError(409, "state_conflict", "Dependencies are not committed")
                upstream[dependency] = artifact["body"]["content"]
            timestamp = now(connection)
            step.update(status="running", attempt=step["attempt"] + 1, started_at=timestamp,
                        completed_at=None, error=None)
            self._emit(connection, snapshot, "step.updated", step, timestamp)
            return snapshot["input"], upstream

    def _record_evaluation(self, connection, snapshot, step_id, artifact_id, evaluation, timestamp):
        method = evaluation["method"]
        step = next(item for item in snapshot["steps"] if item["step_id"] == step_id)
        target = artifact_id or f'{step_id}-attempt-{step["attempt"]}'
        evaluation_id = f"{target}-{method}-evaluation"
        entry = dict(evaluation_id=evaluation_id, step_id=step_id, artifact_id=artifact_id,
                     evaluator="deterministic-checks" if method == "heuristic" else "groq-judge",
                     evaluator_version="1", created_at=timestamp, **evaluation)
        snapshot["evaluations"].append(entry)
        self._emit(connection, snapshot, "evaluation.completed", entry, timestamp)

    def _write_artifact(self, connection, snapshot, step_id, content, timestamp, *, partial=False):
        run_id = snapshot["run_id"]
        reviewed = snapshot["manifest"]["version"] == workflow.REVIEWED_VERSION
        history = [ref for ref in snapshot["artifacts"] if ref["step_id"] == step_id]
        revision = len(history) + 1
        artifact_id = step_id if revision == 1 else f"{step_id}-r{revision}"
        reference = dict(artifact_id=artifact_id, step_id=step_id, kind=step_id,
                         title=step_id.replace("_", " ").title(), media_type="application/json",
                         quality="partial" if partial else "complete", created_at=timestamp,
                         href=f"/api/v1/runs/{run_id}/artifacts/{artifact_id}")
        upstream = {}
        if reviewed:
            spec = workflow.LIVE_STEPS[step_id]
            refs = latest_artifacts(snapshot)
            successful = {step["step_id"] for step in snapshot["steps"] if step["status"] == "succeeded"}
            for dependency in spec.required + spec.optional:
                if dependency in successful and dependency in refs:
                    upstream[dependency] = connection.execute(
                        "SELECT body FROM v1_artifacts WHERE run_id=%s AND artifact_id=%s",
                        (run_id, refs[dependency]["artifact_id"])).fetchone()["body"]
            if domain_errors(step_id, content, {name: row["content"] for name, row in upstream.items()}):
                raise workflow.InvalidOutput(step_id)
            reference.update(revision=revision, supersedes_artifact_id=history[-1]["artifact_id"] if history else None,
                             input_artifact_ids=[row["reference"]["artifact_id"] for row in upstream.values()])
        artifact = dict(run_id=run_id, reference=reference, content=content)
        Artifact.model_validate(artifact)
        connection.execute("INSERT INTO v1_artifacts VALUES (%s,%s,%s)", (run_id, artifact_id, Jsonb(artifact)))
        snapshot["artifacts"].append(reference)
        self._emit(connection, snapshot, "artifact.created", reference, timestamp)
        return artifact, upstream

    def complete_step(self, run_id, token, step_id, content, *, partial=False, judged=None):
        with self._claimed(run_id, token) as (connection, snapshot):
            step = next(s for s in snapshot["steps"] if s["step_id"] == step_id)
            prior_ref = latest_artifacts(snapshot).get(step_id)
            version = snapshot["manifest"]["version"]
            if prior_ref and (version != workflow.REVIEWED_VERSION or step["status"] != "running"):
                previous = connection.execute("SELECT body FROM v1_artifacts WHERE run_id=%s AND artifact_id=%s",
                                              (run_id, prior_ref["artifact_id"])).fetchone()["body"]
                if previous["content"] != content or prior_ref["quality"] != ("partial" if partial else "complete"):
                    raise StoreError(409, "state_conflict", "Artifact is immutable")
                return previous
            if step["status"] != "running":
                raise StoreError(409, "state_conflict", "Step has not started")
            workflow.validate_output(version, step_id, content)
            timestamp = now(connection)
            artifact, upstream = self._write_artifact(connection, snapshot, step_id, content, timestamp, partial=partial)
            error = dict(code="incomplete_output", message="Provider returned incomplete output",
                         retryable=False) if partial else None
            step.update(status="partial" if partial else "succeeded", completed_at=timestamp, error=error)
            self._emit(connection, snapshot, "step.updated", step, timestamp)
            artifact_id = artifact["reference"]["artifact_id"]
            if version == workflow.REVIEWED_VERSION:
                self._record_evaluation(connection, snapshot, step_id, artifact_id,
                                        heuristic(step_id, content, snapshot["input"], upstream, artifact_id,
                                                  partial=partial), timestamp)
                if judged is not None:
                    self._close_reservations(connection, run_id, step_id)
                    self._record_evaluation(connection, snapshot, step_id, artifact_id, judged, timestamp)
            else:
                graph_mode = connection.execute("SELECT graph_mode FROM v1_runs WHERE run_id=%s",
                                                (run_id,)).fetchone()["graph_mode"]
                live = version == workflow.LIVE_VERSION or graph_mode == "live"
                evaluation = dict(evaluation_id=f"{step_id}-evaluation", step_id=step_id, artifact_id=step_id,
                                  evaluator="worker" if live else "fake-provider", evaluator_version="1",
                                  outcome="not_evaluated", score=None, reasons=["Historical workflow evaluation policy."],
                                  created_at=timestamp)
                snapshot["evaluations"].append(evaluation)
                self._emit(connection, snapshot, "evaluation.completed", evaluation, timestamp)
            return artifact

    def finish(self, run_id, token):
        with self._claimed(run_id, token) as (connection, snapshot):
            if any(s["status"] not in {"succeeded", "partial", "failed", "skipped"} for s in snapshot["steps"]):
                raise StoreError(409, "state_conflict", "Workflow is incomplete")
            required = {s["step_id"] for s in snapshot["manifest"]["steps"] if s["required"]}
            incomplete = [s for s in snapshot["steps"] if s["step_id"] in required and s["status"] != "succeeded"]
            status, error = "succeeded", None
            if incomplete:
                status = "partial" if snapshot["artifacts"] else "failed"
                error = next((s["error"] for s in incomplete if s["error"]), None)
            timestamp = now(connection)
            review_step_id = "executive_summary"
            review = connection.execute(
                """SELECT require_review AND NOT EXISTS
                   (SELECT 1 FROM v1_review_decisions WHERE run_id=%s AND review_kind='final') AS pending
                   FROM v1_runs WHERE run_id=%s""", (run_id, run_id)).fetchone()
            review_step = next((s for s in snapshot["steps"] if s["step_id"] == review_step_id), None)
            if status == "succeeded" and review["pending"] and review_step:
                pending = dict(review_id=str(uuid4()), step_id=review_step_id,
                               artifact_ids=[latest_artifacts(snapshot)[review_step_id]["artifact_id"]],
                               prompt="Approve this executive summary?", created_at=timestamp)
                snapshot["pending_review"] = pending
                self._emit(connection, snapshot, "review.requested", pending, timestamp)
                review_step.update(status="awaiting_review", completed_at=None)
                self._emit(connection, snapshot, "step.updated", review_step, timestamp)
                self._run_status(connection, snapshot, "awaiting_review", timestamp)
            else:
                self._run_status(connection, snapshot, status, timestamp, error)

    def decide_review(self, owner, run_id, review_id, decision):
        # Canonicalize omitted optional values while preserving legacy receipt equality.
        decision = {"comment": None, **{key: value for key, value in decision.items() if value is not None}}
        with self.connect() as connection:
            owned = connection.execute(
                "SELECT snapshot, graph_interrupt_id FROM v1_runs WHERE run_id=%s AND owner_id=%s FOR UPDATE",
                (run_id, owner)
            ).fetchone()
            if owned is None:
                raise StoreError(404, "not_found", "Run not found")
            previous = connection.execute(
                """SELECT receipt FROM v1_review_decisions
                   WHERE run_id=%s AND (decision_id=%s OR review_id=%s)""",
                (run_id, decision["decision_id"], review_id)).fetchall()
            if previous:
                for row in previous:
                    receipt = row["receipt"]
                    if receipt["review_id"] == review_id and receipt["decision"] == decision:
                        return receipt
                raise StoreError(409, "state_conflict", "Review or decision already resolved")
            snapshot = owned["snapshot"]
            pending = snapshot["pending_review"]
            if pending is None or pending["review_id"] != review_id:
                raise StoreError(404, "not_found", "Review not found")
            if snapshot["status"] != "awaiting_review":
                raise StoreError(409, "state_conflict", "Run is not awaiting review")
            is_pricing = pending.get("revision_kind") == "pricing"
            artifact_ids = decision.get("artifact_ids")
            if (is_pricing or artifact_ids is not None) and artifact_ids != pending["artifact_ids"]:
                raise StoreError(409, "state_conflict", "The reviewed artifact revision is stale")
            if decision["decision"] == "revise" and not is_pricing:
                raise StoreError(422, "validation_error", "This review does not accept a pricing revision")
            timestamp = now(connection)
            receipt = dict(run_id=str(run_id), review_id=review_id, decision=decision, decided_at=timestamp,
                           event_id=snapshot["last_event_id"] + 1)
            ReviewReceipt.model_validate(receipt)
            snapshot["pending_review"] = None
            self._emit(connection, snapshot, "review.decided", receipt, timestamp)
            if is_pricing:
                self._apply_pricing_decision(connection, snapshot, owned["graph_interrupt_id"], pending, decision, timestamp)
            else:
                self._apply_final_decision(connection, snapshot, pending, decision, timestamp)
            RunSnapshot.model_validate(snapshot)
            connection.execute(
                """INSERT INTO v1_review_decisions (run_id, review_id, decision_id, receipt, review_kind)
                   VALUES (%s,%s,%s,%s,%s)""",
                (run_id, review_id, decision["decision_id"], Jsonb(receipt), "pricing" if is_pricing else "final"))
            connection.execute("UPDATE v1_runs SET snapshot=%s, claim_token=NULL, lease_until=NULL WHERE run_id=%s",
                               (Jsonb(snapshot), run_id))
            return receipt

    def _apply_final_decision(self, connection, snapshot, pending, decision, timestamp):
        approved = decision["decision"] == "approve"
        rejection = dict(code="review_rejected", message="Founder rejected the review", retryable=False)
        for step in snapshot["steps"]:
            if step["step_id"] == pending["step_id"]:
                step.update(status="succeeded" if approved else "failed", completed_at=timestamp,
                            error=None if approved else rejection)
            elif not approved and step["status"] == "queued":
                step.update(status="skipped", completed_at=timestamp, error=rejection)
            else:
                continue
            self._emit(connection, snapshot, "step.updated", step, timestamp)
        status = "running" if approved else ("partial" if snapshot["artifacts"] else "failed")
        self._run_status(connection, snapshot, status, timestamp, None if approved else rejection)

    def _apply_pricing_decision(self, connection, snapshot, interrupt_id, pending, decision, timestamp):
        run_id = snapshot["run_id"]
        refs = latest_artifacts(snapshot)
        pricing = refs[PRICING]
        if not interrupt_id or pending["artifact_ids"] != [pricing["artifact_id"]]:
            raise StoreError(409, "state_conflict", "The review is no longer attached to the active pricing revision")
        action = decision["decision"]
        if action == "revise":
            row = connection.execute("SELECT body FROM v1_artifacts WHERE run_id=%s AND artifact_id=%s",
                                     (run_id, pricing["artifact_id"])).fetchone()
            content = deepcopy(row["body"]["content"])
            edit = decision["pricing_revision"]
            tier = next((item for item in content["tiers"] if item["tier_name"] == edit["tier_name"]), None)
            prices = {field: edit[field] for field in ("price_monthly_usd", "price_annual_usd")}
            if tier is None or all(tier[field] == value for field, value in prices.items()):
                raise StoreError(422, "validation_error", "Provide changed prices for an existing pricing tier")
            tier.update(prices)
            content["founder_price_revision"] = {**edit, "comment": decision["comment"]}
            try:
                workflow.validate_output(workflow.REVIEWED_VERSION, PRICING, content)
            except workflow.InvalidOutput:
                raise StoreError(422, "validation_error", "The pricing revision is invalid") from None
            if domain_errors(PRICING, content):
                raise StoreError(422, "validation_error", "The pricing revision violates pricing constraints")
            artifact, upstream = self._write_artifact(connection, snapshot, PRICING, content, timestamp)
            artifact_id = artifact["reference"]["artifact_id"]
            self._record_evaluation(connection, snapshot, PRICING, artifact_id,
                                    heuristic(PRICING, content, snapshot["input"], upstream, artifact_id), timestamp)
            self._request_pricing_review(connection, snapshot, artifact_id, timestamp)
            return

        steps = {step["step_id"]: step for step in snapshot["steps"]}
        approved = action == "approve"
        rejection = dict(code="review_rejected", message="Founder rejected the pricing assumptions", retryable=False)
        steps[PRICING].update(status="succeeded" if approved else "failed", completed_at=timestamp,
                              error=None if approved else rejection)
        self._emit(connection, snapshot, "step.updated", steps[PRICING], timestamp)
        recompute = approved and pricing["revision"] > 1
        if recompute or not approved:
            steps[FINANCIALS].update(status="queued" if recompute else "skipped", started_at=None,
                                     completed_at=None if recompute else timestamp, error=None if recompute else rejection)
            self._emit(connection, snapshot, "step.updated", steps[FINANCIALS], timestamp)
        resume = dict(decision=action, artifact_id=pricing["artifact_id"], recompute=recompute)
        connection.execute("UPDATE v1_runs SET graph_resume_id=%s, graph_resume_payload=%s WHERE run_id=%s",
                           (interrupt_id, Jsonb(resume), run_id))
        self._run_status(connection, snapshot, "running", timestamp)

    def fail(self, run_id, token, step_id, *, invalid_output=False, timed_out=False, budget_exceeded=False,
             validation_reason=None):
        with self._claimed(run_id, token) as (connection, snapshot):
            timestamp = now(connection)
            step = next(s for s in snapshot["steps"] if s["step_id"] == step_id)
            if step["status"] != "running":
                raise StoreError(409, "state_conflict", "Step is not running")
            error = dict(code="invalid_output" if invalid_output else "provider_failed",
                         message="Invalid provider output" if invalid_output else "Provider failed", retryable=False)
            if timed_out:
                error = dict(code="provider_timeout", message="Provider exceeded the step deadline", retryable=False)
            if budget_exceeded:
                error = dict(code="budget_exceeded", message="Run has insufficient provider budget", retryable=False)
            self._close_reservations(connection, run_id, step_id)
            step.update(status="failed", completed_at=timestamp, error=error)
            self._emit(connection, snapshot, "step.updated", step, timestamp)
            if snapshot["manifest"]["version"] == workflow.REVIEWED_VERSION:
                self._record_evaluation(connection, snapshot, step_id, None,
                                        failed_evaluation(validation_reason or error["message"]), timestamp)
