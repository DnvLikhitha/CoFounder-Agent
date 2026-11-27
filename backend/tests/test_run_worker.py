"""Real PostgreSQL tests. Set TEST_DATABASE_URL to an expendable local database."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from copy import deepcopy
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from threading import Event
import time
import unittest
from unittest.mock import patch
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
from backend.run_worker.store import LostClaim, Store, StoreError
from backend.run_worker.worker import execute_claim
from backend.run_worker.workflow import DEPENDENCIES, ProviderFailure, fake_provider


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
        settings.v1_jwt_secret = cls.secret
        app.dependency_overrides[store] = lambda: Store(cls.dsn)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        app.dependency_overrides.clear()
        settings.v1_jwt_secret = cls.original_secret
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

    def test_dependency_fixture_requires_committed_pricing(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/business_dependencies.json").read_text())
        self.assertEqual(DEPENDENCIES, fixture)
        run_id = self.submit()["run_id"]
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
        environment = {**os.environ, "DATABASE_URL": self.dsn}
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

    def test_runner_schedules_dependencies_before_display_order(self):
        initial = self.submit()
        reordered = deepcopy(initial)
        for index, step in enumerate(reordered["manifest"]["steps"]):
            step["order"] = 3 - index
        with self.database.connect() as connection:
            connection.execute("UPDATE v1_runs SET snapshot=%s WHERE run_id=%s",
                               (Jsonb(reordered), initial["run_id"]))
        observed = []
        def provider(step_id, body, upstream):
            self.assertTrue(set(DEPENDENCIES[step_id]) <= set(observed))
            for dependency, content in upstream.items():
                committed = Store(self.dsn).artifact("alice", initial["run_id"], dependency)
                self.assertEqual(content, committed["content"])
            observed.append(step_id)
            return fake_provider(step_id, body, upstream)
        execute_claim(self.database, self.database.claim(), provider)
        self.assertLess(observed.index("pricing_strategy"), observed.index("financial_projections"))

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

    def test_partial_and_failed_results_and_exports(self):
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
                self.assertIn("Missing sections", response.text)

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


if __name__ == "__main__":
    unittest.main()
