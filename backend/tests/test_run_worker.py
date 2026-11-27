"""Real PostgreSQL tests. Set TEST_DATABASE_URL to an expendable local database."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from copy import deepcopy
from dataclasses import replace
from functools import partial
import json
from multiprocessing import active_children
import os
from pathlib import Path
import secrets
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Barrier, Event
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from jose import jwt
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from backend.config import settings
from backend.contracts.tool import replay
from backend.contracts.v1 import Artifact, EVENT_ADAPTER, RunSnapshot
from backend.run_worker.api import app, store
from backend.run_worker.provider_call import call_with_deadline
from backend.run_worker import workflow
from backend.run_worker.store import LostClaim, Store, StoreError
from backend.run_worker.worker import execute_claim
from backend.run_worker.workflow import (
    FAKE_VERSIONS, LIVE_STEPS, LIVE_VERSION, InvalidOutput, PartialOutput, ProviderFailure,
    fake_provider, validate_output,
)
from backend.tests.test_live_agents import FIXTURE, fixture_provider


# Synchronization tests share threading Events and closures with the test process.
# Other tests exercise the worker's production process boundary.
def inline_call(provider, step_id, body, upstream, timeout, calls):
    return provider(step_id, body, upstream)


def hang_during_pricing(step_id, body, upstream):
    if step_id == "pricing_strategy":
        Event().wait()
    return fake_provider(step_id, body, upstream)


def wait_in_sibling_steps(marker_dir, step_id, body, upstream):
    if step_id in {"pricing_strategy", "risk_register"}:
        (Path(marker_dir) / f"{os.getpid()}.started").touch()
        while not (Path(marker_dir) / "release").exists():
            time.sleep(0.05)
    return fake_provider(step_id, body, upstream)


class PricingValidationTests(unittest.TestCase):
    def test_json_prices_accept_finite_numbers(self):
        for value, accepted in [(10, True), (10.25, True), (True, False), ("10", False),
                                (float("inf"), False), (float("nan"), False)]:
            with self.subTest(value=value):
                content = {"tiers": [{"tier_name": "Starter", "price_monthly_usd": value}]}
                if accepted:
                    validate_output("fake-business-v2", "pricing_strategy", content)
                else:
                    with self.assertRaises(InvalidOutput):
                        validate_output("fake-business-v2", "pricing_strategy", content)


class WorkerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_dsn = os.environ["TEST_DATABASE_URL"]
        cls.schema = "worker_test_" + uuid4().hex
        with psycopg.connect(cls.base_dsn) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
        cls.dsn = make_conninfo(cls.base_dsn, options=f"-csearch_path={cls.schema}")
        cls.database = Store(cls.dsn)
        cls.database.migrate()
        cls.database.migrate()
        cls.secret = secrets.token_hex(32)
        cls.original_secret = settings.v1_jwt_secret
        cls.original_provider_mode = settings.v1_provider_mode
        cls.original_environment = settings.environment
        cls.original_concurrency = settings.v1_step_concurrency
        settings.v1_jwt_secret = cls.secret
        settings.v1_provider_mode = "fake"
        settings.environment = "development"
        settings.v1_step_concurrency = 2
        app.dependency_overrides[store] = lambda: Store(cls.dsn)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        app.dependency_overrides.clear()
        settings.v1_jwt_secret = cls.original_secret
        settings.v1_provider_mode = cls.original_provider_mode
        settings.environment = cls.original_environment
        settings.v1_step_concurrency = cls.original_concurrency
        with psycopg.connect(cls.base_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    def setUp(self):
        with self.database.connect() as connection:
            connection.execute("TRUNCATE v1_events, v1_artifacts, v1_runs")
        self.body = {"problem": "Help students find useful internships.", "domain": None, "geography": None}

    def headers(self, subject="alice", **claims):
        payload = dict(sub=subject, exp=int(time.time()) + 300,
                       iss=settings.v1_jwt_issuer, aud=settings.v1_jwt_audience)
        payload.update(claims)
        return {"Authorization": "Bearer " + jwt.encode(payload, self.secret, algorithm="HS256")}

    def submit(self, subject="alice", key="submission-1"):
        return self.database.submit(subject, key, self.body)

    def expire(self, run_id):
        with self.database.connect() as connection:
            connection.execute("UPDATE v1_runs SET lease_until=clock_timestamp()-interval '1 second' WHERE run_id=%s", (run_id,))

    def test_duplicate_submission_concurrent_and_conflicting(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            snapshots = list(pool.map(lambda _: self.submit(), range(6)))
        self.assertTrue(all(snapshot == snapshots[0] for snapshot in snapshots))
        self.assertEqual(snapshots[0]["status"], "queued")
        execute_claim(self.database, self.database.claim())
        self.assertEqual(self.submit(), snapshots[0])
        with self.assertRaises(StoreError) as failure:
            self.database.submit("alice", "submission-1", {**self.body, "domain": "changed"})
        self.assertEqual(failure.exception.status, 409)
        self.assertNotEqual(self.submit("bob")["run_id"], snapshots[0]["run_id"])

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_claim_exclusion_reclaim_and_restart(self):
        initial = self.submit()
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda _: self.database.claim(), range(4)))
        active = [claim for claim in claims if claim]
        self.assertEqual(len(active), 1)
        run_id, old_token = active[0]
        inputs = self.database.begin_step(run_id, old_token, "business_model")
        content = fake_provider("business_model", *inputs)
        self.database.complete_step(run_id, old_token, "business_model", content)
        self.database.begin_step(run_id, old_token, "pricing_strategy")
        self.expire(run_id)
        restarted = Store(self.dsn)
        new_claim = restarted.claim()
        self.assertNotEqual(new_claim[1], old_token)
        for action in [lambda: self.database.complete_step(run_id, old_token, "pricing_strategy", {}),
                       lambda: self.database.renew(run_id, old_token),
                       lambda: self.database.fail(run_id, old_token, "pricing_strategy")]:
            with self.assertRaises(LostClaim):
                action()
        called = []
        def provider(step_id, body, upstream):
            called.append(step_id)
            return fake_provider(step_id, body, upstream)
        execute_claim(restarted, new_claim, provider)
        self.assertNotIn("business_model", called)
        final = restarted.snapshot("alice", run_id)
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(final["steps"][1]["attempt"], 2)
        self.assertEqual(replay(initial, restarted.events("alice", run_id, 0)), final)

    def test_artifact_idempotency_and_transaction_rollback(self):
        run_id = self.submit()["run_id"]
        claim = self.database.claim()
        inputs = self.database.begin_step(*claim, "business_model")
        before = self.database.snapshot("alice", run_id)
        content = fake_provider("business_model", *inputs)
        original_emit = self.database._emit
        def interrupt(connection, snapshot, kind, data, timestamp):
            if kind == "step.updated":
                raise RuntimeError("Simulated crash after artifact insert")
            original_emit(connection, snapshot, kind, data, timestamp)
        with patch.object(self.database, "_emit", side_effect=interrupt):
            with self.assertRaises(RuntimeError):
                self.database.complete_step(*claim, "business_model", content)
        self.assertEqual(self.database.snapshot("alice", run_id), before)
        with self.assertRaises(StoreError):
            self.database.artifact("alice", run_id, "business_model")
        artifact = self.database.complete_step(*claim, "business_model", content)
        checkpoint = self.database.snapshot("alice", run_id)
        self.assertEqual(self.database.complete_step(*claim, "business_model", content), artifact)
        self.assertEqual(self.database.snapshot("alice", run_id), checkpoint)
        with self.assertRaises(StoreError):
            self.database.complete_step(*claim, "business_model", {"different": True})
        ids = [event["event_id"] for event in self.database.events("alice", run_id, 0)]
        self.assertEqual(ids, list(range(1, checkpoint["last_event_id"] + 1)))

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_slow_provider_keeps_claim_past_its_original_expiry(self):
        run_id = self.submit()["run_id"]
        lease_seconds = 2
        claim = self.database.claim(lease_seconds)
        started, release = Event(), Event()

        def slow_provider(step_id, body, upstream):
            if step_id == "business_model":
                started.set()
                if not release.wait(15):
                    raise RuntimeError("Test provider timed out")
            return fake_provider(step_id, body, upstream)

        with ThreadPoolExecutor(max_workers=1) as pool:
            worker = pool.submit(execute_claim, self.database, claim, slow_provider, lease_seconds)
            try:
                self.assertTrue(started.wait(10))
                time.sleep(lease_seconds + 0.5)
                self.assertIsNone(Store(self.dsn).claim())
            finally:
                release.set()
            worker.result(timeout=15)
        snapshot = self.database.snapshot("alice", run_id)
        self.assertEqual(snapshot["status"], "succeeded")
        self.assertTrue(all(step["attempt"] == 1 for step in snapshot["steps"]))

    def test_hung_provider_fails_step_and_worker_can_process_next_run(self):
        run_id = self.submit()["run_id"]
        with patch.object(settings, "v1_provider_timeout_seconds", 6):
            execute_claim(self.database, self.database.claim(2), hang_during_pricing, lease_seconds=2)
        final = self.database.snapshot("alice", run_id)
        steps = {step["step_id"]: step for step in final["steps"]}
        self.assertEqual(final["status"], "partial")
        self.assertEqual(steps["pricing_strategy"]["status"], "failed")
        self.assertEqual(steps["pricing_strategy"]["error"]["code"], "provider_timeout")
        self.assertEqual(steps["financial_projections"]["status"], "skipped")
        self.assertEqual(steps["risk_register"]["status"], "succeeded")
        self.assertNotIn("pricing_strategy", [a["artifact_id"] for a in final["artifacts"]])
        next_run = self.submit(key="after-timeout")["run_id"]
        execute_claim(self.database, self.database.claim())
        self.assertEqual(self.database.snapshot("alice", next_run)["status"], "succeeded")

    def test_lease_expiring_during_commit_rolls_back(self):
        run_id = self.submit()["run_id"]
        claim = self.database.claim()
        inputs = self.database.begin_step(*claim, "business_model")
        before = self.database.snapshot("alice", run_id)
        original_emit = self.database._emit
        def expire_during_write(connection, snapshot, kind, data, timestamp):
            original_emit(connection, snapshot, kind, data, timestamp)
            connection.execute("UPDATE v1_runs SET lease_until=clock_timestamp()-interval '1 second' WHERE run_id=%s", (run_id,))
        with patch.object(self.database, "_emit", side_effect=expire_during_write):
            with self.assertRaises(LostClaim):
                self.database.complete_step(*claim, "business_model", fake_provider("business_model", *inputs))
        self.assertEqual(self.database.snapshot("alice", run_id), before)
        with self.assertRaises(StoreError):
            self.database.artifact("alice", run_id, "business_model")

    def test_reclaim_terminates_both_active_children_before_provider_deadline(self):
        run_id = self.submit()["run_id"]
        claim = self.database.claim(3)
        with TemporaryDirectory() as marker_dir, ThreadPoolExecutor(1) as pool:
            path = Path(marker_dir)
            with patch.object(settings, "v1_provider_timeout_seconds", 60):
                worker = pool.submit(execute_claim, self.database, claim, partial(wait_in_sibling_steps, marker_dir), 3)
                try:
                    deadline = time.monotonic() + 20
                    while len(list(path.glob("*.started"))) < 2 and time.monotonic() < deadline:
                        time.sleep(0.05)
                    child_pids = {int(marker.stem) for marker in path.glob("*.started")}
                    self.assertEqual(len(child_pids), 2)
                    self.expire(run_id)
                    replacement = self.database.claim()
                    self.assertEqual(replacement[0], run_id)
                    before = self.database.snapshot("alice", run_id)
                    with self.assertRaises(LostClaim):
                        worker.result(timeout=5)
                    self.assertTrue(child_pids.isdisjoint(p.pid for p in active_children()))
                    self.assertEqual(self.database.snapshot("alice", run_id), before)
                    self.assertEqual(self.database.events("alice", run_id, before["last_event_id"]), [])
                finally:
                    (path / "release").touch()
        execute_claim(self.database, replacement)
        self.assertEqual(self.database.snapshot("alice", run_id)["status"], "succeeded")

    def test_dependency_fixture_requires_committed_pricing(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/business_dependencies.json").read_text())
        initial = self.submit()
        self.assertEqual({s["step_id"]: s["depends_on"] for s in initial["manifest"]["steps"]}, fixture)
        run_id = initial["run_id"]
        claim = self.database.claim()
        for step in ["pricing_strategy", "financial_projections", "risk_register"]:
            with self.assertRaises(StoreError):
                self.database.begin_step(*claim, step)
        inputs = self.database.begin_step(*claim, "business_model")
        business = fake_provider("business_model", *inputs)
        self.database.complete_step(*claim, "business_model", business)
        pricing_inputs = Store(self.dsn).begin_step(*claim, "pricing_strategy")
        self.assertEqual(pricing_inputs[1], {"business_model": business})
        before = self.database.snapshot("alice", run_id)
        with self.assertRaises(StoreError):
            self.database.begin_step(*claim, "financial_projections")
        self.assertEqual(self.database.snapshot("alice", run_id), before)
        pricing = fake_provider("pricing_strategy", *pricing_inputs)
        self.database.complete_step(*claim, "pricing_strategy", pricing)
        finance_inputs = Store(self.dsn).begin_step(*claim, "financial_projections")
        self.assertEqual(finance_inputs[1], {"business_model": business, "pricing_strategy": pricing})
        execute_claim(self.database, claim)
        events = self.database.events("alice", run_id, 0)
        pricing_commit = next(e["event_id"] for e in events if e["type"] == "artifact.created" and e["data"]["step_id"] == "pricing_strategy")
        finance_start = next(e["event_id"] for e in events if e["type"] == "step.updated" and e["data"]["step_id"] == "financial_projections")
        self.assertLess(pricing_commit, finance_start)

    def test_http_snapshot_sse_replay_and_separate_worker_process(self):
        response = self.client.post("/runs", json=self.body, headers={**self.headers(), "Idempotency-Key": "http-key"})
        self.assertEqual(response.status_code, 202)
        initial = response.json()
        RunSnapshot.model_validate(initial)
        run_id = initial["run_id"]
        environment = {**os.environ, "DATABASE_URL": self.dsn, "V1_PROVIDER_MODE": "fake",
                       "V1_STEP_CONCURRENCY": "2", "ENVIRONMENT": "development"}
        worker = subprocess.run([sys.executable, "-m", "backend.run_worker.worker", "--once"],
                                env=environment, capture_output=True, timeout=30)
        self.assertEqual(worker.returncode, 0, "Separate worker failed")
        final = self.client.get(f"/runs/{run_id}", headers=self.headers()).json()
        RunSnapshot.model_validate(final)
        self.assertEqual(final["status"], "succeeded")
        duplicate = self.client.post("/runs", json=self.body,
                                     headers={**self.headers(), "Idempotency-Key": "http-key"})
        self.assertEqual(duplicate.status_code, 202)
        self.assertEqual(duplicate.json(), initial)
        conflict = self.client.post("/runs", json={**self.body, "domain": "changed"},
                                    headers={**self.headers(), "Idempotency-Key": "http-key"})
        self.assertEqual(conflict.status_code, 409)
        response = self.client.get(f"/runs/{run_id}/events", headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        for event in events:
            EVENT_ADAPTER.validate_python(event)
        self.assertEqual(replay(initial, events), final)
        for boundary in range(len(events) + 1):
            response = self.client.get(f"/runs/{run_id}/events?after=0",
                                       headers={**self.headers(), "Last-Event-ID": str(boundary)})
            if boundary == len(events):
                self.assertEqual(response.status_code, 204)
            else:
                remaining = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
                self.assertEqual(remaining, events[boundary:])
        self.assertEqual(self.client.get(f"/runs/{run_id}/events?after=999", headers=self.headers()).status_code, 409)
        self.assertEqual(self.client.get(f"/runs/{run_id}/events?after=-1", headers=self.headers()).status_code, 422)
        for reference in final["artifacts"]:
            response = self.client.get(f'/runs/{run_id}/artifacts/{reference["artifact_id"]}', headers=self.headers())
            Artifact.model_validate(response.json())

    def test_financials_waits_for_pricing_transaction_commit(self):
        run_id = self.submit()["run_id"]
        claim = self.database.claim()
        inputs = self.database.begin_step(*claim, "business_model")
        self.database.complete_step(*claim, "business_model", fake_provider("business_model", *inputs))
        inputs = self.database.begin_step(*claim, "pricing_strategy")
        pricing = fake_provider("pricing_strategy", *inputs)
        publishing, release = Event(), Event()
        publisher = Store(self.dsn)
        original_emit = publisher._emit
        def pause_before_commit(connection, snapshot, kind, data, timestamp):
            original_emit(connection, snapshot, kind, data, timestamp)
            if kind == "evaluation.completed":
                publishing.set()
                if not release.wait(5):
                    raise RuntimeError("Test publication was not released")
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(publisher, "_emit", side_effect=pause_before_commit):
            publication = pool.submit(publisher.complete_step, *claim, "pricing_strategy", pricing)
            try:
                self.assertTrue(publishing.wait(5))
                with self.assertRaises(StoreError):
                    self.database.artifact("alice", run_id, "pricing_strategy")
                finance = pool.submit(self.database.begin_step, *claim, "financial_projections")
                with self.assertRaises(TimeoutError):
                    finance.result(timeout=0.2)
            finally:
                release.set()
            publication.result(timeout=5)
            self.assertEqual(finance.result(timeout=5)[1]["pricing_strategy"], pricing)

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_runner_schedules_dependencies_before_display_order(self):
        initial = self.submit()
        reordered = deepcopy(initial)
        for index, step in enumerate(reordered["manifest"]["steps"]):
            step["order"] = 3 - index
        with self.database.connect() as connection:
            connection.execute("UPDATE v1_runs SET snapshot=%s WHERE run_id=%s",
                               (Jsonb(reordered), initial["run_id"]))
        observed = []
        required = {s["step_id"]: set(s["depends_on"]) for s in initial["manifest"]["steps"]}
        def provider(step_id, body, upstream):
            self.assertTrue(required[step_id] <= set(observed))
            for dependency, content in upstream.items():
                committed = Store(self.dsn).artifact("alice", initial["run_id"], dependency)
                self.assertEqual(content, committed["content"])
            observed.append(step_id)
            return fake_provider(step_id, body, upstream)
        execute_claim(self.database, self.database.claim(), provider)
        self.assertLess(observed.index("pricing_strategy"), observed.index("financial_projections"))

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_invalid_pricing_blocks_only_financials_while_risk_runs_concurrently(self):
        initial = self.submit()
        siblings = Barrier(2)
        called = []

        def provider(step_id, body, upstream):
            called.append(step_id)
            if step_id in {"pricing_strategy", "risk_register"}:
                siblings.wait(timeout=5)
                self.assertEqual(set(upstream), {"business_model"})
            if step_id == "pricing_strategy":
                return {"tiers": [{"tier_name": "Invalid", "price_monthly_usd": -1}]}
            return fake_provider(step_id, body, upstream)

        execute_claim(self.database, self.database.claim(), provider)
        run_id = initial["run_id"]
        final = self.database.snapshot("alice", run_id)
        states = {s["step_id"]: s for s in final["steps"]}
        self.assertEqual(final["status"], "partial")
        self.assertEqual(states["pricing_strategy"]["error"]["code"], "invalid_output")
        self.assertEqual(states["pricing_strategy"]["status"], "failed")
        self.assertEqual(states["financial_projections"]["status"], "skipped")
        self.assertEqual(states["financial_projections"]["error"]["code"], "dependency_blocked")
        self.assertEqual(states["financial_projections"]["attempt"], 0)
        self.assertNotIn("financial_projections", called)
        self.assertEqual({a["artifact_id"] for a in final["artifacts"]}, {"business_model", "risk_register"})
        self.assertEqual(replay(initial, self.database.events("alice", run_id, 0)), final)

    def test_invalid_nested_outputs_leave_artifacts_and_events_untouched(self):
        run_id = self.submit()["run_id"]
        claim = self.database.claim()
        invalid = {
            "business_model": {"revenue_streams": ["malformed"]},
            "pricing_strategy": {"tiers": [{"tier_name": "Free", "price_monthly_usd": True}]},
            "financial_projections": {"monthly_projections": [{"month": 1, "mrr_usd": "unknown"}]},
            "risk_register": {"risks": [{"risk_id": "r1", "mitigation_strategy": []}]},
        }
        for step_id, changes in invalid.items():
            with self.subTest(step_id=step_id):
                inputs = self.database.begin_step(*claim, step_id)
                output = fake_provider(step_id, *inputs)
                before = self.database.snapshot("alice", run_id)
                with self.assertRaises(InvalidOutput):
                    self.database.complete_step(*claim, step_id, {**output, **changes})
                self.assertEqual(self.database.snapshot("alice", run_id), before)
                self.assertEqual(self.database.events("alice", run_id, before["last_event_id"]), [])
                with self.assertRaises(StoreError):
                    self.database.artifact("alice", run_id, step_id)
                self.database.complete_step(*claim, step_id, output)

    def test_preexisting_v1_manifest_can_complete(self):
        initial = self.submit()
        initial["manifest"]["version"] = "fake-business-v1"
        with self.database.connect() as connection:
            connection.execute("UPDATE v1_runs SET initial_snapshot=%s, snapshot=%s WHERE run_id=%s",
                               (Jsonb(initial), Jsonb(initial), initial["run_id"]))
        claim = self.database.claim()
        self.database.begin_step(*claim, "business_model")
        legacy_content = {"legacy_model": "subscription"}
        self.database.complete_step(*claim, "business_model", legacy_content)
        execute_claim(self.database, claim)
        final = self.database.snapshot("alice", initial["run_id"])
        self.assertEqual(final["manifest"], initial["manifest"])
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(replay(initial, self.database.events("alice", initial["run_id"], 0)), final)

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_partial_pricing_survives_reclaim_and_blocks_required_consumer(self):
        initial = self.submit()
        claim = self.database.claim()
        run_id, _ = claim
        for step_id in ["business_model", "pricing_strategy"]:
            inputs = self.database.begin_step(*claim, step_id)
            output = fake_provider(step_id, *inputs)
            self.database.complete_step(*claim, step_id, output, partial=step_id == "pricing_strategy")
        self.expire(run_id)

        def remaining_provider(step_id, body, upstream):
            self.assertEqual(step_id, "risk_register")
            return PartialOutput(fake_provider(step_id, body, upstream))

        execute_claim(Store(self.dsn), self.database.claim(), remaining_provider)
        final = self.database.snapshot("alice", run_id)
        self.assertEqual(final["status"], "partial")
        self.assertEqual([s["status"] for s in final["steps"]], ["succeeded", "partial", "skipped", "partial"])
        for step_id in ["pricing_strategy", "risk_register"]:
            artifact = self.database.artifact("alice", run_id, step_id)
            self.assertEqual(artifact["reference"]["quality"], "partial")
        report = self.client.get(f"/runs/{run_id}/exports/markdown", headers=self.headers())
        self.assertIn("Missing sections: Financial Projections.", report.text)
        self.assertIn("Incomplete sections: Pricing Strategy, Risk Register.", report.text)
        self.assertEqual(replay(initial, self.database.events("alice", run_id, 0)), final)

    def test_reclaim_uses_submitted_optional_inputs_and_output_schema_after_upgrade(self):
        run_id = self.submit()["run_id"]
        claim = self.database.claim()
        # Model a run with foundation steps already committed before the business phase.
        with self.database.connect() as connection:
            row = connection.execute("SELECT snapshot FROM v1_runs WHERE run_id=%s FOR UPDATE",
                                     (run_id,)).fetchone()
            snapshot = row["snapshot"]
            for name in ("startup_idea", "executive_summary"):
                definition = dict(snapshot["manifest"]["steps"][0], step_id=name, artifact_kinds=[name])
                snapshot["manifest"]["steps"].append(definition)
                step = dict(snapshot["steps"][0], step_id=name, status="succeeded",
                            completed_at=snapshot["created_at"], started_at=snapshot["created_at"], attempt=1)
                snapshot["steps"].append(step)
                connection.execute("INSERT INTO v1_artifacts VALUES (%s,%s,%s)",
                                   (run_id, name, Jsonb({"content": {"source": name}})))
            connection.execute("UPDATE v1_runs SET snapshot=%s WHERE run_id=%s", (Jsonb(snapshot), run_id))
        _, upstream = self.database.begin_step(*claim, "business_model")
        self.assertEqual(upstream, {"startup_idea": {"source": "startup_idea"}})
        self.expire(run_id)
        # Simulate a deployment changing both the allowed inputs and the output model.
        version = "fake-business-v3"
        newer = dict(workflow.WORKFLOWS["fake-business-v2"])
        newer["business_model"] = replace(newer["business_model"], optional=("executive_summary",),
                                           output=workflow.Pricing)
        with patch.object(workflow, "WORKFLOWS", {**workflow.WORKFLOWS, version: newer}), \
             patch.object(workflow, "CURRENT_VERSION", version):
            fresh = self.submit(key="after-upgrade")
            self.assertEqual(fresh["manifest"]["version"], version)
            reclaimed = self.database.claim()
            self.assertEqual(reclaimed[0], run_id)
            body, after = self.database.begin_step(*reclaimed, "business_model")
            self.assertEqual(after, upstream)
            content = fake_provider("business_model", body, after)
            self.database.complete_step(*reclaimed, "business_model", content)
            fresh_claim = self.database.claim()
            self.database.begin_step(*fresh_claim, "business_model")
            with self.assertRaises(InvalidOutput):
                self.database.complete_step(*fresh_claim, "business_model", content)

    def test_worker_leaves_newer_manifest_for_a_compatible_worker(self):
        with patch.object(workflow, "CURRENT_VERSION", "future"), patch.object(
            workflow, "WORKFLOWS", {**workflow.WORKFLOWS, "future": workflow.WORKFLOWS["fake-business-v2"]}
        ):
            future = self.submit()
        supported = self.submit(key="supported")
        self.assertEqual(self.database.claim()[0], supported["run_id"])
        self.assertIsNone(self.database.claim())
        self.assertEqual(self.database.snapshot("alice", future["run_id"]), future)

    def test_stream_follows_events_committed_after_subscription(self):
        initial = self.submit()
        subscribed = Event()
        streaming_store = Store(self.dsn)
        original_events = streaming_store.events
        def read_events(*args):
            events = original_events(*args)
            subscribed.set()
            return events
        app.dependency_overrides[store] = lambda: streaming_store
        try:
            with ThreadPoolExecutor(max_workers=1) as pool, patch.object(streaming_store, "events", side_effect=read_events):
                stream = pool.submit(self.client.get, f'/runs/{initial["run_id"]}/events', headers=self.headers())
                self.assertTrue(subscribed.wait(5))
                execute_claim(self.database, self.database.claim())
                response = stream.result(timeout=10)
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            self.assertEqual(replay(initial, events), self.database.snapshot("alice", initial["run_id"]))
        finally:
            app.dependency_overrides[store] = lambda: Store(self.dsn)

    def test_stream_expiring_during_database_read_can_replay_with_fresh_token(self):
        run_id = self.submit()["run_id"]
        self.database.claim()
        expiry = int(time.time()) + 60
        clock = Mock(return_value=expiry - 1)
        database = Store(self.dsn)
        original_events = database.events

        def read_events(*args):
            batch = original_events(*args)
            clock.return_value = expiry
            return batch

        app.dependency_overrides[store] = lambda: database
        path = f"/runs/{run_id}/events"
        try:
            with patch("backend.run_worker.api.time", SimpleNamespace(time=clock, monotonic=time.monotonic)), \
                 patch.object(database, "events", side_effect=read_events):
                ended = self.client.get(path, headers=self.headers(exp=expiry))
            self.assertEqual(ended.status_code, 200)
            self.assertEqual(ended.content, b"")
            with patch("backend.run_worker.worker.call_with_deadline", inline_call):
                self.expire(run_id)
                execute_claim(database, database.claim())
            resumed = self.client.get(path, headers={**self.headers(), "Last-Event-ID": "0"})
            self.assertIn("id: 1\nevent: run.updated", resumed.text)
        finally:
            app.dependency_overrides[store] = lambda: Store(self.dsn)

    def test_owner_isolation_and_authentication(self):
        run_id = self.submit()["run_id"]
        self.assertEqual(self.client.post("/runs", json=self.body).status_code, 401)
        execute_claim(self.database, self.database.claim())
        paths = [f"/runs/{run_id}", f"/runs/{run_id}/events", f"/runs/{run_id}/artifacts",
                 f"/runs/{run_id}/artifacts/business_model", f"/runs/{run_id}/exports/markdown"]
        for path in paths:
            self.assertEqual(self.client.get(path, headers=self.headers("bob")).status_code, 404)
            self.assertEqual(self.client.get(path).status_code, 401)
        for claims in [dict(exp=1), dict(aud="wrong"), dict(iss="wrong")]:
            self.assertEqual(self.client.get(paths[0], headers=self.headers(**claims)).status_code, 401)
        forged = {"Authorization": "Bearer " + jwt.encode(dict(sub="alice", exp=time.time()+60), "wrong", algorithm="HS256")}
        self.assertEqual(self.client.get(paths[0], headers=forged).status_code, 401)
        with patch.object(settings, "v1_jwt_secret", ""):
            self.assertEqual(self.client.get(paths[0], headers=self.headers()).status_code, 503)
        response = self.client.post("/runs", json={"problem": "short"}, headers=self.headers())
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation_error")

    def test_database_failure_is_not_accepted_or_exposed(self):
        with patch.object(Store, "connect", side_effect=psycopg.OperationalError("private connection details")):
            response = self.client.post("/runs", json=self.body, headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("private", response.text)
        with self.database.connect() as connection:
            self.assertEqual(connection.execute("SELECT count(*) AS count FROM v1_runs").fetchone()["count"], 0)

    def test_history_cursor_order_and_owner_scope(self):
        alice = [self.submit(key=f"alice-{i}")["run_id"] for i in range(3)]
        self.submit("bob")
        with self.database.connect() as connection:
            connection.execute("UPDATE v1_runs SET created_at='2000-01-01T00:00:00Z'")
        headers = self.headers()
        self.assertEqual(self.client.get("/runs").status_code, 401)
        self.assertEqual(self.client.get("/runs?cursor=invalid", headers=headers).status_code, 422)
        self.assertEqual(self.client.get("/runs?limit=0", headers=headers).status_code, 422)
        response = self.client.get("/runs?limit=2", headers=headers)
        self.assertEqual(response.status_code, 200)
        first = response.json()
        self.assertEqual([run["run_id"] for run in first["runs"]], sorted(alice, reverse=True)[:2])
        newest = self.submit(key="newer")["run_id"]
        response = self.client.get("/runs", params={"limit": 2, "cursor": first["next_cursor"]}, headers=headers)
        self.assertEqual(response.status_code, 200)
        last = response.json()
        self.assertEqual([run["run_id"] for run in last["runs"]], [min(alice)])
        self.assertIsNone(last["next_cursor"])
        self.assertNotIn(newest, [run["run_id"] for run in last["runs"]])
        self.assertNotIn("steps", last["runs"][0])

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_partial_and_failed_results_and_exports(self):
        from io import BytesIO
        from pptx import Presentation

        for failing_step, expected in [("pricing_strategy", "partial"), ("business_model", "failed")]:
            initial = self.submit(key=failing_step)
            def provider(step, body, upstream):
                if step == failing_step:
                    raise ProviderFailure()
                return fake_provider(step, body, upstream)
            execute_claim(self.database, self.database.claim(), provider)
            final = self.database.snapshot("alice", initial["run_id"])
            self.assertEqual(final["status"], expected)
            self.assertEqual(replay(initial, self.database.events("alice", initial["run_id"], 0)), final)
            response = self.client.get(f'/runs/{initial["run_id"]}/exports/markdown', headers=self.headers())
            self.assertEqual(response.status_code, 200 if expected == "partial" else 409)
            if expected == "partial":
                self.assertIn("Partial results", response.text)
                self.assertIn("Missing sections", response.text)
                self.assertIn("Business model: subscription", response.text)
                deck = self.client.get(f'/runs/{initial["run_id"]}/exports/pptx', headers=self.headers())
                presentation = Presentation(BytesIO(deck.content))
                slide_text = "\n".join(shape.text for slide in presentation.slides
                                       for shape in slide.shapes if shape.has_text_frame)
                self.assertIn("Partial results", slide_text)
                self.assertIn("Missing sections: Pricing Strategy", slide_text)
                self.assertIn("Business model: subscription", slide_text)

    def test_exports_and_legacy_routes_registered(self):
        run_id = self.submit()["run_id"]
        self.assertEqual(self.client.get(f"/runs/{run_id}/exports/pdf", headers=self.headers()).status_code, 409)
        execute_claim(self.database, self.database.claim())
        for format, prefix in [("markdown", b"#"), ("pdf", b"%PDF"), ("pptx", b"PK")]:
            response = self.client.get(f"/runs/{run_id}/exports/{format}", headers=self.headers())
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content.startswith(prefix))
            self.assertIn("attachment", response.headers["content-disposition"])
        from backend.main import app as main_app
        paths = {route.path for route in main_app.routes}
        self.assertTrue({"/api/run", "/api/runs", "/api/run/{run_id}/stream", "/api/v1"} <= paths)
        client = TestClient(main_app)
        response = client.get(f"/api/v1/runs/{run_id}", headers=self.headers())
        self.assertEqual(response.status_code, 200)
        client.close()

    def test_live_submission_fails_without_provider_credentials(self):
        with patch.object(settings, "v1_provider_mode", "live"), patch.object(settings, "groq_api_key", ""):
            response = self.client.post("/runs", json=self.body, headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertIn("GROQ_API_KEY", response.json()["error"]["message"])
        self.assertIsNone(self.database.claim())

    def test_all_live_agents_publish_committed_artifacts_and_export_real_content(self):
        from io import BytesIO
        from pptx import Presentation
        from reportlab import rl_config

        with patch.object(settings, "v1_provider_mode", "live"), patch.object(settings, "groq_api_key", "synthetic"):
            response = self.client.post("/runs", json=self.body, headers=self.headers())
        self.assertEqual(response.status_code, 202)
        initial = response.json()
        run_id = initial["run_id"]
        self.assertEqual(initial["manifest"]["version"], LIVE_VERSION)
        self.assertEqual([step["step_id"] for step in initial["manifest"]["steps"]], list(LIVE_STEPS))
        self.assertIsNone(self.database.claim(versions=FAKE_VERSIONS))
        independent_research = Barrier(2)
        seen = {}

        def observe_call(provider, step_id, body, upstream, timeout, calls):
            spec = LIVE_STEPS[step_id]
            self.assertTrue(set(spec.required + spec.optional) <= upstream.keys(), step_id)
            for dependency, content in upstream.items():
                self.assertEqual(self.database.artifact("alice", run_id, dependency)["content"], content)
            seen[step_id] = frozenset(upstream)
            if step_id in {"market_research", "competitor_analysis"}:
                independent_research.wait(5)
            return call_with_deadline(provider, step_id, body, upstream, timeout, calls)

        with patch("backend.run_worker.worker.live_provider", fixture_provider), \
             patch("backend.run_worker.worker.call_with_deadline", observe_call), \
             patch.object(settings, "v1_step_concurrency", 2):
            execute_claim(self.database, self.database.claim(versions=(LIVE_VERSION,)))
        final = self.client.get(f"/runs/{run_id}", headers=self.headers()).json()
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(set(seen), set(LIVE_STEPS))
        self.assertEqual(len(final["artifacts"]), 16)
        self.assertEqual({artifact["kind"] for artifact in final["artifacts"]}, set(LIVE_STEPS))
        market_path = f"/runs/{run_id}/artifacts/market_research"
        market = self.client.get(market_path, headers=self.headers()).json()["content"]
        self.assertEqual(market["tool_evidence"]["serpapi_sources"], ["https://example.org/audit-source"])
        self.assertIn("synthetic fixture", market["tool_evidence"]["fred_data"])
        self.assertIsNone(market["cagr_percent"])
        self.assertEqual(self.client.get(market_path, headers=self.headers("bob")).status_code, 404)

        wire = self.client.get(f"/runs/{run_id}/events", headers=self.headers())
        self.assertEqual(wire.status_code, 200)
        events = [json.loads(line[6:]) for line in wire.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(replay(initial, events), final)
        remainder = self.client.get(f"/runs/{run_id}/events?after=30", headers=self.headers())
        self.assertEqual([json.loads(line[6:]) for line in remainder.text.splitlines()
                          if line.startswith("data: ")], events[30:])

        exports = f"/runs/{run_id}/exports"
        markdown = self.client.get(f"{exports}/markdown", headers=self.headers())
        self.assertIn("Campus Bridge & Co", markdown.text)
        self.assertIn("CREATE TABLE verified_roles", markdown.text)
        self.assertIn("A Verified Internship Gap", markdown.text)
        self.assertIn("https://example.org/audit-source", markdown.text)
        self.assertNotIn("Fake-provider demonstration", markdown.text)
        with patch.object(rl_config, "pageCompression", 0):
            pdf = self.client.get(f"{exports}/pdf", headers=self.headers())
        self.assertEqual(pdf.status_code, 200)
        self.assertIn(b"Campus Bridge connects busy students", pdf.content)
        self.assertIn(b"Campus Pilot", pdf.content)
        pptx = self.client.get(f"{exports}/pptx", headers=self.headers())
        self.assertEqual(pptx.status_code, 200)
        deck = Presentation(BytesIO(pptx.content))
        self.assertEqual(len(deck.slides), 13)  # Report cover plus the 12 generated slides.
        self.assertEqual(deck.slides[1].shapes[0].text, "A Verified Internship Gap")
        self.assertIn("Describe the schedule verification workflow", deck.slides[1].notes_slide.notes_text_frame.text)

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_live_reclaim_preserves_artifacts_and_isolates_failed_pricing_dependencies(self):
        initial = self.database.submit("alice", "live-reclaim", self.body, version=LIVE_VERSION)
        run_id = initial["run_id"]
        original = self.database.claim()
        for step_id in ("problem_refined", "startup_idea"):
            inputs = self.database.begin_step(*original, step_id)
            self.database.complete_step(*original, step_id, fixture_provider(step_id, *inputs))
        before = self.database.snapshot("alice", run_id)
        self.expire(run_id)
        replacement = self.database.claim()
        self.assertEqual(replacement[0], run_id)
        with self.assertRaises(LostClaim):
            self.database.begin_step(*original, "market_research")

        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        def provider(step_id, body, upstream):
            self.assertNotIn(step_id, {"problem_refined", "startup_idea", "financial_projections",
                                       "pitch_deck", "executive_summary"})
            if step_id == "pricing_strategy":
                return {"tiers": []}
            return fixture[step_id]["personas"] if step_id == "customer_personas" else fixture[step_id]

        execute_claim(Store(self.dsn), replacement, provider)
        final = self.database.snapshot("alice", run_id)
        states = {step["step_id"]: step for step in final["steps"]}
        self.assertEqual(final["status"], "partial")
        self.assertEqual(final["artifacts"][:2], before["artifacts"])
        self.assertEqual(states["startup_idea"]["attempt"], 1)
        self.assertEqual(states["pricing_strategy"]["error"]["code"], "invalid_output")
        for step_id in ("financial_projections", "pitch_deck", "executive_summary"):
            self.assertEqual(states[step_id]["error"]["code"], "dependency_blocked")
        self.assertEqual(states["risk_register"]["status"], "succeeded")
        self.assertEqual(states["database_schema"]["status"], "succeeded")
        self.assertEqual(replay(initial, self.database.events("alice", run_id, 0)), final)
        report = self.client.get(f"/runs/{run_id}/exports/markdown", headers=self.headers())
        self.assertIn("Partial results", report.text)
        self.assertIn("Missing sections: Pricing Strategy, Financial Projections, Pitch Deck, Executive Summary", report.text)
        self.assertIn("Campus Bridge & Co", report.text)

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_live_failed_optional_risk_does_not_block_executive_summary(self):
        initial = self.database.submit("alice", "optional-risk", self.body, version=LIVE_VERSION)
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

        def provider(step_id, body, upstream):
            if step_id == "risk_register":
                raise ProviderFailure()
            if step_id == "executive_summary":
                self.assertNotIn("risk_register", upstream)
                self.assertIn("financial_projections", upstream)
            if step_id == "customer_personas":
                return fixture[step_id]["personas"]
            if step_id == "pitch_deck":
                return {"slides": fixture[step_id]}
            return fixture[step_id]

        execute_claim(self.database, self.database.claim(), provider)
        final = self.database.snapshot("alice", initial["run_id"])
        self.assertEqual(final["status"], "partial")
        states = {step["step_id"]: step["status"] for step in final["steps"]}
        self.assertEqual(states["risk_register"], "failed")
        self.assertEqual(states["executive_summary"], "succeeded")


if __name__ == "__main__":
    unittest.main()
