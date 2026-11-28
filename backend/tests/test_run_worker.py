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

from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient
from groq import APIStatusError
from langgraph.checkpoint.postgres import PostgresSaver
import httpx
import jwt
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from backend.config import settings
from backend.contracts.tool import replay
from backend.contracts.v1 import Artifact, EVENT_ADAPTER, RunSnapshot
from backend.llm.profiles import PROFILES, PROFILE_VERSION, PROMPT_VERSION
from backend.run_worker.api import app, store
from backend.run_worker.auth import supabase_keys
from backend.run_worker.checkpoints import ClaimCheckpointer
from backend.run_worker.graph import build_graph, demo_provider, merge_outcomes
from backend.run_worker.ledger import AttemptLedger, BudgetExceeded
from backend.run_worker.live_agents import PROMPT_BUNDLES
from backend.run_worker.provider_call import call_with_deadline
from backend.run_worker import workflow
from backend.run_worker.store import LostClaim, Store, StoreError
from backend.run_worker.worker import execute_claim
from backend.run_worker.workflow import (
    FAKE_VERSIONS, GRAPH_VERSION, REVIEWED_VERSION, LIVE_STEPS, LIVE_VERSION, InvalidOutput, PartialOutput,
    ProviderFailure, ProviderTimeout,
    fake_provider, validate_output,
)
from backend.tests.test_live_agents import FIXTURE, FixtureGroq, fixture_provider, hang_during_pricing, wait_in_sibling_steps


# Synchronization tests share threading Events and closures with the test process.
# Other tests exercise the worker's production process boundary.
def inline_call(provider, step_id, body, upstream, timeout, calls):
    return provider(step_id, body, upstream)


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
        cls.dsn = make_conninfo(cls.base_dsn, options=f"-csearch_path={cls.schema} -cTimeZone=UTC")
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
            connection.execute("TRUNCATE v1_events, v1_artifacts, v1_llm_attempts, v1_review_decisions, "
                               "v1_worker_heartbeats, v1_runs")
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

    def graph_run(self, key, mode="fake", **options):
        return self.database.submit("alice", key, self.body, version=GRAPH_VERSION, graph_mode=mode, **options)

    def test_pricing_review_revisions_are_owner_scoped_durable_and_recompute_only_dependents(self):
        with patch.object(settings, "v1_require_pricing_review", True):
            accepted = self.client.post("/runs", headers=self.headers(), json=self.body)
        self.assertEqual(accepted.status_code, 202)
        initial = accepted.json()
        run_id = initial["run_id"]
        execute_claim(self.database, self.database.claim())
        paused = self.database.snapshot("alice", run_id)
        self.assertEqual(paused["status"], "awaiting_review")
        self.assertIsNone(self.database.claim())
        self.assertEqual(len(paused["artifacts"]), 14)
        self.assertEqual(len(paused["evaluations"]), 14)
        first = paused["pending_review"]
        self.assertEqual(first["artifact_ids"], ["pricing_strategy"])
        old_price = self.database.artifact("alice", run_id, "pricing_strategy")
        old_forecast = self.database.artifact("alice", run_id, "financial_projections")
        tier = old_price["content"]["tiers"][0]
        monthly_price = tier["price_monthly_usd"]
        path = f'/runs/{run_id}/reviews/{first["review_id"]}/decisions'
        revision = {"decision_id": str(uuid4()), "decision": "revise", "artifact_ids": first["artifact_ids"],
                    "pricing_revision": {"tier_name": tier["tier_name"], "price_monthly_usd": monthly_price,
                                         "price_annual_usd": 900}}
        self.assertEqual(self.client.post(path, headers=self.headers("bob"), json=revision).status_code, 404)
        stale = {**revision, "artifact_ids": ["pricing_strategy-r2"]}
        self.assertEqual(self.client.post(path, headers=self.headers(), json=stale).status_code, 409)
        invalid = {**revision, "pricing_revision": {**revision["pricing_revision"], "tier_name": "unregistered"}}
        self.assertEqual(self.client.post(path, headers=self.headers(), json=invalid).status_code, 422)
        self.assertEqual(self.database.snapshot("alice", run_id), paused)
        with ThreadPoolExecutor(max_workers=2) as pool:
            duplicates = list(pool.map(lambda _: self.client.post(path, headers=self.headers(), json=revision), range(2)))
        self.assertEqual([reply.status_code for reply in duplicates], [200, 200])
        self.assertEqual(duplicates[0].json(), duplicates[1].json())
        restarted = Store(self.dsn)
        revised = restarted.snapshot("alice", run_id)
        current = revised["pending_review"]
        self.assertNotEqual(current["review_id"], first["review_id"])
        self.assertEqual(current["artifact_ids"], ["pricing_strategy-r2"])
        self.assertIsNone(restarted.claim())
        stale_decision = {"decision_id": str(uuid4()), "decision": "approve", "artifact_ids": first["artifact_ids"]}
        self.assertEqual(self.client.post(path, headers=self.headers(), json=stale_decision).status_code, 409)
        updated = self.client.get(f"/runs/{run_id}/artifacts/pricing_strategy-r2", headers=self.headers()).json()
        self.assertEqual(updated["reference"]["supersedes_artifact_id"], "pricing_strategy")
        self.assertEqual(updated["content"]["tiers"][0]["price_monthly_usd"], monthly_price)
        self.assertEqual(updated["content"]["tiers"][0]["price_annual_usd"], 900)
        self.assertEqual(restarted.artifact("alice", run_id, "pricing_strategy"), old_price)
        path = f'/runs/{run_id}/reviews/{current["review_id"]}/decisions'
        approval = {**stale_decision, "decision_id": str(uuid4()), "artifact_ids": current["artifact_ids"]}
        self.assertEqual(self.client.post(path, headers=self.headers(), json=approval).status_code, 200)
        environment = {**os.environ, "DATABASE_URL": self.dsn, "V1_PROVIDER_MODE": "fake", "ENVIRONMENT": "development"}
        process = subprocess.run([sys.executable, "-m", "backend.run_worker.worker", "--once"],
                                 env=environment, capture_output=True, timeout=45)
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", errors="replace"))
        final = self.client.get(f"/runs/{run_id}", headers=self.headers()).json()
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(final["pending_review"], None)
        self.assertEqual(len(final["artifacts"]), 18)
        states = {step["step_id"]: step["attempt"] for step in final["steps"]}
        self.assertEqual(states["financial_projections"], 2)
        self.assertTrue(all(count == 1 for step, count in states.items() if step != "financial_projections"))
        forecast = restarted.artifact("alice", run_id, "financial_projections-r2")
        self.assertEqual(forecast["content"]["assumptions"]["reviewed_monthly_price_usd"], monthly_price)
        final_month = forecast["content"]["monthly_projections"][-1]
        self.assertEqual(final_month["tier_customers"][tier["tier_name"]], {"monthly": 6, "annual": 6})
        self.assertEqual(final_month["mrr_usd"], 6 * monthly_price + 6 * 900 / 12)
        self.assertNotEqual(forecast["content"]["arr_month_12_usd"], old_forecast["content"]["arr_month_12_usd"])
        self.assertIn("pricing_strategy-r2", forecast["reference"]["input_artifact_ids"])
        self.assertEqual(restarted.artifact("alice", run_id, "financial_projections"), old_forecast)
        deck = restarted.artifact("alice", run_id, "pitch_deck")
        self.assertIn("financial_projections-r2", deck["reference"]["input_artifact_ids"])
        self.assertIn("financial_projections-r2", restarted.artifact("alice", run_id, "executive_summary")
                      ["reference"]["input_artifact_ids"])
        wire = self.client.get(f"/runs/{run_id}/events", headers=self.headers())
        events = [json.loads(line[6:]) for line in wire.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(replay(initial, events), final)
        self.assertEqual(sum(event["type"] == "review.requested" for event in events), 2)

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_revised_live_forecast_cannot_publish_draft_financials(self):
        run = self.database.submit("alice", "stale-forecast", self.body, version=REVIEWED_VERSION,
                                   graph_mode="live", pricing_review=True)
        run_id = run["run_id"]
        execute_claim(self.database, self.database.claim(), demo_provider)
        pricing = self.database.artifact("alice", run_id, "pricing_strategy")["content"]
        tier = pricing["tiers"][0]["tier_name"]
        for action in ("revise", "approve"):
            pending = self.database.snapshot("alice", run_id)["pending_review"]
            decision = dict(decision_id=str(uuid4()), decision=action, artifact_ids=pending["artifact_ids"])
            if action == "revise":
                decision["pricing_revision"] = dict(tier_name=tier, price_monthly_usd=37, price_annual_usd=370)
            self.database.decide_review("alice", run_id, pending["review_id"], decision)

        draft = self.database.artifact("alice", run_id, "financial_projections")["content"]
        claim = self.database.claim()
        self.database.begin_step(*claim, "financial_projections")
        with self.assertRaises(InvalidOutput):
            self.database.complete_step(*claim, "financial_projections", draft)

        def stale_provider(step, body, upstream):
            self.assertEqual(step, "financial_projections")
            candidate = demo_provider(step, body, upstream)
            # Copy the approved price table but keep the original forecast's MRR, making ARR internally consistent.
            for row, original in zip(candidate["monthly_projections"], draft["monthly_projections"], strict=True):
                row.update(mrr_usd=original["mrr_usd"], revenue_usd=original["mrr_usd"])
            candidate["arr_month_12_usd"] = draft["arr_month_12_usd"]
            return candidate

        execute_claim(self.database, claim, stale_provider)
        final = self.database.snapshot("alice", run_id)
        states = {step["step_id"]: step for step in final["steps"]}
        self.assertEqual(final["status"], "partial")
        self.assertEqual(states["financial_projections"]["error"]["code"], "invalid_output")
        self.assertEqual(states["pitch_deck"]["error"]["code"], "dependency_blocked")
        self.assertEqual(states["executive_summary"]["error"]["code"], "dependency_blocked")
        self.assertEqual([a["artifact_id"] for a in final["artifacts"] if a["step_id"] == "financial_projections"],
                         ["financial_projections"])

    def test_reject_pricing_blocks_dependents_but_keeps_draft_history(self):
        run = self.database.submit("alice", "reject-pricing", self.body, version=REVIEWED_VERSION,
                                   graph_mode="fake", pricing_review=True)
        run_id = run["run_id"]
        execute_claim(self.database, self.database.claim())
        review = self.database.snapshot("alice", run_id)["pending_review"]
        path = f'/runs/{run_id}/reviews/{review["review_id"]}/decisions'
        decision = dict(decision_id=str(uuid4()), decision="reject", artifact_ids=review["artifact_ids"])
        self.assertEqual(self.client.post(path, headers=self.headers(), json=decision).status_code, 200)
        execute_claim(self.database, self.database.claim())
        final = self.database.snapshot("alice", run_id)
        steps = {step["step_id"]: step for step in final["steps"]}
        self.assertEqual(final["status"], "partial")
        self.assertEqual(steps["pricing_strategy"]["error"]["code"], "review_rejected")
        self.assertEqual(steps["financial_projections"]["status"], "skipped")
        self.assertEqual(steps["pitch_deck"]["error"]["code"], "dependency_blocked")
        self.assertEqual(steps["risk_register"]["status"], "succeeded")
        self.assertEqual(self.database.artifact("alice", run_id, "financial_projections")["reference"]["revision"], 1)
        exported = self.client.get(f"/runs/{run_id}/exports/markdown", headers=self.headers())
        self.assertIn("Missing sections:", exported.text)
        self.assertNotIn("paid_campuses_month_12", exported.text)

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_failed_domain_validation_is_published_and_optional_judge_has_shared_budget(self):
        run = self.database.submit("alice", "evaluation-budget", self.body, version=REVIEWED_VERSION,
                                   graph_mode="live", token_limit=1, llm_evaluation=True)

        def provider(step, body, upstream):
            result = demo_provider(step, body, upstream)
            if step == "market_research":
                result.update(tam_usd_billions=1, sam_usd_billions=2)
            return result

        with patch("backend.llm.client.AsyncGroq", lambda **_: FixtureGroq(api_key="synthetic")):
            execute_claim(self.database, self.database.claim(), provider)
        final = self.database.snapshot("alice", run["run_id"])
        self.assertEqual(final["status"], "partial")
        market = next(e for e in final["evaluations"] if e["step_id"] == "market_research")
        self.assertEqual(market["outcome"], "failed")
        self.assertIsNone(market["artifact_id"])
        self.assertIn("TAM", market["reasons"][0])
        problem = [e for e in final["evaluations"] if e["step_id"] == "problem_refined"]
        self.assertEqual([e["method"] for e in problem], ["heuristic", "llm"])
        self.assertEqual(problem[1]["outcome"], "not_evaluated")
        self.assertIn("budget", problem[1]["reasons"][0])

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_provider_judge_records_metered_dimensions_and_rejects_malformed_scores(self):
        scores = dict(task_completion=2, relevance=2, consistency=2, grounding=1, completeness=2)

        class JudgeGroq(FixtureGroq):
            async def complete(self, model, messages, **kwargs):
                step = json.loads(messages[-1]["content"])["step"]
                payload = scores if step == "problem_refined" else {**scores, "relevance": 5}
                return SimpleNamespace(model=model, usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10),
                                       choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])

        def provider(step, body, upstream):
            return demo_provider(step, body, upstream) if step in {"problem_refined", "startup_idea"} else {}

        run = self.database.submit("alice", "meter-judge", self.body, version=REVIEWED_VERSION,
                                   graph_mode="live", llm_evaluation=True)
        with patch("backend.llm.client.AsyncGroq", JudgeGroq):
            execute_claim(self.database, self.database.claim(), provider)
        final = self.database.snapshot("alice", run["run_id"])
        judgments = {e["step_id"]: e for e in final["evaluations"] if e.get("method") == "llm"}
        self.assertEqual(judgments["problem_refined"]["outcome"], "needs_review")
        self.assertEqual(judgments["problem_refined"]["score"], .8)
        self.assertEqual(judgments["startup_idea"]["outcome"], "not_evaluated")
        self.assertEqual({artifact["artifact_id"] for artifact in final["artifacts"]}, {"problem_refined", "startup_idea"})
        with self.database.connect() as connection:
            charges = connection.execute("""SELECT purpose, charged_tokens, charged_cost_nanousd
                FROM v1_llm_attempts WHERE run_id=%s""", (run["run_id"],)).fetchall()
        self.assertEqual(len(charges), 2)
        self.assertTrue(all(row["purpose"] == "evaluation" and row["charged_tokens"] == 30
                            and row["charged_cost_nanousd"] > 0 for row in charges))

    def test_langgraph_structure_includes_16_agents_and_validated_joins(self):
        compiled = build_graph(lambda step, state: {})
        self.assertEqual(set(compiled.builder.nodes), {*LIVE_STEPS, "pricing_review"})
        joins = set(compiled.builder.waiting_edges)
        for name, spec in LIVE_STEPS.items():
            if name != "financial_projections" and spec.required:
                dependencies = set(spec.required + spec.optional)
                self.assertTrue(any(set(upstream) == dependencies and target == name for upstream, target in joins))
        self.assertIn("financial_projections", compiled.builder.branches["pricing_strategy"]["route_after_pricing"].ends)
        broken = dict(LIVE_STEPS)
        broken["problem_refined"] = replace(broken["problem_refined"], optional=("undefined_step",))
        with self.assertRaisesRegex(ValueError, "missing dependenc"):
            build_graph(lambda step, state: {}, steps=broken)
        broken["problem_refined"] = replace(broken["problem_refined"], optional=("startup_idea",))
        with self.assertRaises(ValueError):
            build_graph(lambda step, state: {}, steps=broken)
        left, right = {"market": {"status": "succeeded"}}, {"competitor": {"status": "failed"}}
        self.assertEqual(merge_outcomes(left, right), merge_outcomes(right, left))
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            merge_outcomes(left, {"market": {"status": "failed"}})

    def test_langgraph_interrupt_resume_from_postgres_in_separate_process(self):
        initial = self.graph_run("graph-interrupt")
        run_id = initial["run_id"]
        claim = self.database.claim()
        execute_claim(self.database, claim, review_pricing=True)
        with self.database.connect(autocommit=True, prepare_threshold=0) as connection:
            paused = connection.execute("""SELECT graph_interrupt_id, claim_token, lease_until
                                          FROM v1_runs WHERE run_id=%s""", (run_id,)).fetchone()
            checkpoint = PostgresSaver(connection).get_tuple({"configurable": {"thread_id": run_id}})
        self.assertIsNotNone(checkpoint)
        self.assertTrue(paused["graph_interrupt_id"])
        self.assertIsNone(paused["claim_token"])
        self.assertIsNone(paused["lease_until"])
        self.assertIsNone(self.database.claim())
        steps = {s["step_id"]: s["status"] for s in self.database.snapshot("alice", run_id)["steps"]}
        self.assertEqual(steps["pricing_strategy"], "succeeded")
        self.assertEqual(steps["financial_projections"], "queued")
        with self.assertRaises(StoreError) as foreign:
            self.database.authorize_graph_resume("bob", run_id, paused["graph_interrupt_id"])
        self.assertEqual(foreign.exception.status, 404)
        with self.assertRaises(StoreError) as wrong:
            self.database.authorize_graph_resume("alice", run_id, "wrong-interrupt")
        self.assertEqual(wrong.exception.status, 409)
        for _ in range(2):
            self.database.authorize_graph_resume("alice", run_id, paused["graph_interrupt_id"])
        environment = {**os.environ, "DATABASE_URL": self.dsn, "V1_PROVIDER_MODE": "fake", "ENVIRONMENT": "development"}
        completed = subprocess.run([sys.executable, "-m", "backend.run_worker.worker", "--once"],
                                   env=environment, capture_output=True, timeout=45)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", errors="replace"))
        final = self.database.snapshot("alice", run_id)
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(len(final["artifacts"]), 16)
        self.assertEqual(next(s["attempt"] for s in final["steps"] if s["step_id"] == "pricing_strategy"), 1)
        events = self.database.events("alice", run_id, 0)
        self.assertEqual(replay(initial, events), final)
        with self.database.connect(autocommit=True, prepare_threshold=0) as connection:
            latest = PostgresSaver(connection).get_tuple({"configurable": {"thread_id": run_id}})
        state = latest.checkpoint["channel_values"]
        self.assertEqual(state["review"], {"step_id": "pricing_strategy", "artifact_id": "pricing_strategy",
                                          "decision": "approve"})
        self.assertEqual(len(state["outcomes"]), 16)
        self.assertEqual(state["outcomes"]["market_research"]["research_artifact_id"], "market_research")
        self.assertNotIn("content", state["outcomes"]["market_research"]["artifact"])

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_graph_reconciles_artifact_commit_and_terminal_publication(self):
        initial = self.graph_run("checkpoint-crash")
        run_id = initial["run_id"]
        claim = self.database.claim()
        with patch.object(self.database, "graph_step_outcome", side_effect=RuntimeError("synthetic crash")):
            with self.assertRaisesRegex(RuntimeError, "Graph node interrupted"):
                execute_claim(self.database, claim)
        self.assertEqual(self.database.artifact("alice", run_id, "problem_refined")["reference"]["quality"], "complete")
        self.expire(run_id)
        restarted = Store(self.dsn)
        provider = Mock(side_effect=demo_provider)
        with patch.object(restarted, "finish", side_effect=RuntimeError("synthetic crash before final publication")):
            with self.assertRaisesRegex(RuntimeError, "before final publication"):
                execute_claim(restarted, restarted.claim(), provider)
        self.assertNotIn("problem_refined", [call.args[0] for call in provider.call_args_list])
        self.assertEqual(len(provider.call_args_list), 15)
        self.assertEqual(restarted.snapshot("alice", run_id)["status"], "running")
        self.expire(run_id)
        execute_claim(restarted, restarted.claim(), Mock(side_effect=AssertionError("Provider should not run again")))
        final = restarted.snapshot("alice", run_id)
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(replay(initial, restarted.events("alice", run_id, 0)), final)

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_graph_recovers_settled_attempt_before_artifact_commit(self):
        initial = self.graph_run("provider-before-artifact", mode="live")
        run_id = initial["run_id"]
        database = self.database
        claim = database.claim()

        def provider(step, body, upstream):
            if step == "problem_refined":
                return fixture_provider(step, body, upstream, store=database, claim=claim)
            return demo_provider(step, body, upstream)

        with patch.object(database, "complete_step", side_effect=RuntimeError("synthetic publication crash")):
            with self.assertRaisesRegex(RuntimeError, "Graph node interrupted"):
                execute_claim(database, claim, provider)
        with self.assertRaises(StoreError):
            database.artifact("alice", run_id, "problem_refined")
        self.expire(run_id)
        database = Store(self.dsn)
        claim = database.claim()
        execute_claim(database, claim, provider)
        with database.connect() as connection:
            charges = connection.execute("""SELECT status, charged_tokens FROM v1_llm_attempts
                WHERE run_id=%s AND step_id='problem_refined' ORDER BY attempt_no""", (run_id,)).fetchall()
        self.assertEqual(charges, [{"status": "succeeded", "charged_tokens": 400}] * 2)
        events = database.events("alice", run_id, 0)
        self.assertEqual(sum(e["type"] == "artifact.created" and e["data"]["step_id"] == "problem_refined"
                             for e in events), 1)
        self.assertEqual(replay(initial, events), database.snapshot("alice", run_id))

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_graph_reclaim_fences_parallel_nodes_and_checkpoint_writes(self):
        initial = self.graph_run("checkpoint-lease")
        run_id = initial["run_id"]
        claim = self.database.claim()
        reached = Barrier(3)
        release = Event()

        def abandoned(step, body, upstream):
            if step in {"market_research", "competitor_analysis"}:
                reached.wait(15)
                if not release.wait(15):
                    raise RuntimeError("Test release did not arrive")
            return demo_provider(step, body, upstream)

        with ThreadPoolExecutor(max_workers=1) as pool:
            active = pool.submit(execute_claim, self.database, claim, abandoned)
            try:
                reached.wait(15)
                self.expire(run_id)
                restarted = Store(self.dsn)
                replacement = restarted.claim()
                self.assertEqual(replacement[0], run_id)
                with restarted.connect(autocommit=True, prepare_threshold=0) as conn:
                    valid = ClaimCheckpointer(conn, *replacement)
                    config = {"configurable": {"thread_id": run_id}}
                    latest = valid.get_tuple(config)
                    with self.assertRaises(ValueError):
                        valid.get_tuple({"configurable": {"thread_id": str(uuid4())}})
                    stale = ClaimCheckpointer(conn, *claim)
                    with self.assertRaises(LostClaim):
                        stale.put(latest.config, latest.checkpoint, latest.metadata, {})
                    with self.assertRaises(LostClaim):
                        stale.put_writes(latest.config, [("outcomes", {})], "stale-task")
            finally:
                release.set()
            with self.assertRaises(LostClaim):
                active.result(timeout=15)
        provider = Mock(side_effect=demo_provider)
        execute_claim(restarted, replacement, provider)
        recomputed = [call.args[0] for call in provider.call_args_list]
        self.assertNotIn("problem_refined", recomputed)
        self.assertNotIn("startup_idea", recomputed)
        self.assertIn("market_research", recomputed)
        self.assertIn("competitor_analysis", recomputed)
        final = restarted.snapshot("alice", run_id)
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(replay(initial, restarted.events("alice", run_id, 0)), final)

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_graph_distinguishes_invalid_required_output_and_optional_timeout(self):
        for failing_step, code in (("financial_projections", "invalid_output"), ("risk_register", "provider_timeout")):
            with self.subTest(step=failing_step):
                initial = self.graph_run(failing_step)
                run_id = initial["run_id"]

                def provider(step, body, upstream):
                    if step == failing_step:
                        if code == "invalid_output":
                            return {}
                        raise ProviderTimeout()
                    if step == "executive_summary" and failing_step == "risk_register":
                        self.assertNotIn("risk_register", upstream)
                    return demo_provider(step, body, upstream)

                execute_claim(self.database, self.database.claim(), provider)
                final = self.database.snapshot("alice", run_id)
                self.assertEqual(final["status"], "partial")
                steps = {s["step_id"]: s for s in final["steps"]}
                self.assertEqual(steps[failing_step]["error"]["code"], code)
                self.assertEqual(steps["product_design"]["status"], "succeeded")
                if failing_step == "financial_projections":
                    self.assertEqual(steps["pitch_deck"]["error"]["code"], "dependency_blocked")
                else:
                    self.assertEqual(steps["executive_summary"]["status"], "succeeded")
                report = self.client.get(f"/runs/{run_id}/exports/markdown", headers=self.headers())
                self.assertIn("Missing sections:", report.text)
                self.assertIn("Fake-provider demonstration", report.text)

    def test_graph_capacity_is_shared_across_workers_and_modes_are_pinned(self):
        self.graph_run("first-fake")
        self.graph_run("second-fake")
        live = self.graph_run("live", mode="live")
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda _: Store(self.dsn).claim(graph_mode="fake", active_limit=1), range(4)))
        active = [claim for claim in claims if claim]
        self.assertEqual(len(active), 1)
        self.assertIsNone(self.database.claim(graph_mode="live", active_limit=1))
        self.expire(active[0][0])
        self.assertEqual(self.database.claim(graph_mode="live", active_limit=1)[0], live["run_id"])

    def test_postgres_checkpointer_migration_is_concurrent_private_and_repeatable(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: Store(self.dsn).migrate(), range(2)))
        with self.database.connect() as connection:
            secured = connection.execute("""SELECT relname FROM pg_class
                WHERE relnamespace=current_schema()::regnamespace AND relrowsecurity
                  AND relname IN ('checkpoints', 'checkpoint_writes', 'checkpoint_blobs', 'checkpoint_migrations')""").fetchall()
            self.assertEqual(len(secured), 4)
            self.assertEqual(connection.execute("SELECT count(*) AS count FROM checkpoint_migrations").fetchone()["count"],
                             len(PostgresSaver.MIGRATIONS))

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_graph_uses_adapter_fallback_and_stops_after_retry_exhaustion(self):
        for exhaust in (False, True):
            with self.subTest(exhaust=exhaust):
                initial = self.graph_run(f"provider-{exhaust}", mode="live")
                claim = self.database.claim()
                attempted = []

                class FlakyGroq(FixtureGroq):
                    async def complete(self, model, messages, **kwargs):
                        attempted.append(model)
                        if exhaust or len(attempted) == 1:
                            request = httpx.Request("POST", "https://example.test/provider")
                            response = httpx.Response(503 if exhaust else 429, request=request,
                                                      headers={"Retry-After": "0"})
                            raise APIStatusError("simulated provider failure", response=response, body={})
                        reply = await super().complete("openai/gpt-oss-120b", messages, **kwargs)
                        reply.model = model
                        return reply

                def provider(step, body, upstream):
                    if step == "problem_refined":
                        return fixture_provider(step, body, upstream, groq=FlakyGroq, store=self.database, claim=claim)
                    return demo_provider(step, body, upstream)

                with patch("backend.llm.client.uniform", return_value=0):
                    execute_claim(self.database, claim, provider)
                final = self.database.snapshot("alice", initial["run_id"])
                with self.database.connect() as connection:
                    ledger = connection.execute("""SELECT status, requested_model, actual_model FROM v1_llm_attempts
                        WHERE run_id=%s ORDER BY attempt_no""", (initial["run_id"],)).fetchall()
                if exhaust:
                    self.assertEqual(final["status"], "failed")
                    self.assertEqual(final["error"]["code"], "provider_failed")
                    self.assertEqual([entry["status"] for entry in ledger], ["transient"] * 3)
                    self.assertEqual(len(attempted), 3)
                else:
                    self.assertEqual(final["status"], "succeeded")
                    self.assertEqual([entry["status"] for entry in ledger], ["rate_limited", "succeeded"])
                    self.assertEqual(ledger[1]["actual_model"], "openai/gpt-oss-20b")
                    self.assertEqual(attempted, ["openai/gpt-oss-120b", "openai/gpt-oss-20b"])

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

    def test_submission_contract_with_and_without_idempotency_key(self):
        headers = {**self.headers(), "Idempotency-Key": "browser-submission"}
        first = self.client.post("/runs", json={"problem": self.body["problem"]}, headers=headers)
        self.assertEqual(first.status_code, 202)
        duplicate = self.client.post("/runs", json=self.body, headers=headers)
        self.assertEqual(duplicate.json(), first.json())
        conflict = self.client.post("/runs", json={**self.body, "domain": "different"}, headers=headers)
        self.assertEqual(conflict.status_code, 409)
        unkeyed = [self.client.post("/runs", json=self.body, headers=self.headers()).json()["run_id"] for _ in range(2)]
        self.assertEqual(len(set(unkeyed + [first.json()["run_id"]])), 3)

    def test_run_budget_serializes_concurrent_reservations_and_retains_crash_charge(self):
        model = PROFILES[PROFILE_VERSION][0]
        fixtures = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for token_limit, cost_limit in [(100, 1_000_000), (10_000, model.cost(50, 50))]:
            with self.subTest(token_limit=token_limit, cost_limit=cost_limit):
                run = self.database.submit("alice", str(uuid4()), self.body, version=LIVE_VERSION,
                                           token_limit=token_limit, cost_limit=cost_limit)
                claim = self.database.claim()
                self.assertEqual(claim[0], run["run_id"])
                self.assertEqual(self.database.live_configuration(*claim),
                                 {"model_profile": PROFILE_VERSION, "prompt_version": PROMPT_VERSION})
                for step in ("problem_refined", "startup_idea"):
                    self.database.begin_step(*claim, step)
                    self.database.complete_step(*claim, step, fixtures[step])
                steps = ("market_research", "competitor_analysis")
                for step in steps:
                    self.database.begin_step(*claim, step)
                barrier = Barrier(2)

                def reserve(step):
                    ledger = AttemptLedger(Store(self.dsn), *claim, step)
                    barrier.wait(5)
                    try:
                        return step, ledger.reserve(model, 50, 50)
                    except BudgetExceeded:
                        return step, None

                with ThreadPoolExecutor(max_workers=2) as executor:
                    reservations = dict(executor.map(reserve, steps))
                self.assertEqual(sum(attempt is not None for attempt in reservations.values()), 1)
                step, reservation = next((s, a) for s, a in reservations.items() if a)
                self.expire(run["run_id"])
                restarted = Store(self.dsn)
                replacement = restarted.claim()
                old = AttemptLedger(self.database, *claim, step)
                with self.assertRaises(LostClaim):
                    old.settle(reservation, "succeeded", actual_model=model.name, usage=(2, 3), cost=model.cost(2, 3))
                restarted.begin_step(*replacement, step)
                ledger = AttemptLedger(restarted, *replacement, step)
                self.assertEqual(ledger.history()[0]["status"], "unknown")
                with self.assertRaises(BudgetExceeded):
                    ledger.reserve(model, 50, 50)
                with restarted.connect() as connection:
                    row = connection.execute(
                        "SELECT charged_tokens, charged_cost_nanousd FROM v1_llm_attempts WHERE attempt_id=%s",
                        (reservation,)).fetchone()
                    self.assertEqual(row, {"charged_tokens": 100, "charged_cost_nanousd": model.cost(50, 50)})

    def test_reported_usage_releases_headroom_and_attempt_cap_survives_reclaim(self):
        model = PROFILES[PROFILE_VERSION][0]
        run_id = self.database.submit("alice", "usage", self.body, version=LIVE_VERSION,
                                      token_limit=100, cost_limit=100_000)["run_id"]
        claim = self.database.claim()
        step = "problem_refined"
        self.database.begin_step(*claim, step)
        ledger = AttemptLedger(self.database, *claim, step)
        for _ in range(2):
            attempt = ledger.reserve(model, 50, 40)
            ledger.settle(attempt, "rate_limited", usage=(0, 0), cost=0, retry_delay=1)
        attempt = ledger.reserve(model, 50, 40)
        ledger.settle(attempt, "succeeded", actual_model=model.name, usage=(10, 4), cost=model.cost(10, 4))
        self.expire(run_id)
        restarted = Store(self.dsn)
        replacement = restarted.claim()
        restarted.begin_step(*replacement, step)
        resumed = AttemptLedger(restarted, *replacement, step)
        self.assertEqual([a["status"] for a in resumed.history()], ["rate_limited", "rate_limited", "succeeded"])
        with self.assertRaises(ProviderFailure):
            resumed.reserve(model, 1, 1)

    def test_migration_backfills_unfinished_live_runs_and_enables_rls(self):
        run_id = self.database.submit("alice", "pre-ledger", self.body, version=LIVE_VERSION)["run_id"]
        with self.database.connect() as connection:
            connection.execute("""UPDATE v1_runs SET model_profile=NULL, prompt_version=NULL,
                                  token_limit=NULL, cost_limit_nanousd=NULL WHERE run_id=%s""", (run_id,))
        self.database.migrate()
        claim = self.database.claim()
        self.assertEqual(self.database.live_configuration(*claim),
                         {"model_profile": PROFILE_VERSION, "prompt_version": PROMPT_VERSION})
        with self.database.connect() as connection:
            limits = connection.execute(
                "SELECT token_limit, cost_limit_nanousd FROM v1_runs WHERE run_id=%s", (run_id,)
            ).fetchone()
            self.assertEqual(limits, {"token_limit": 500_000, "cost_limit_nanousd": 250_000_000})
            secured = connection.execute(
                """SELECT count(*) AS n FROM pg_class
                   WHERE relnamespace=current_schema()::regnamespace AND relname LIKE 'v1\_%' AND relrowsecurity"""
            ).fetchone()
            self.assertEqual(secured["n"], 6)

    def test_supabase_rotation_claim_validation_and_owner_scope(self):
        es = ec.generate_private_key(ec.SECP256R1())
        rs = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwks = [dict(jwt.algorithms.ECAlgorithm.to_jwk(es.public_key(), as_dict=True), kid="es", alg="ES256"),
                dict(jwt.algorithms.RSAAlgorithm.to_jwk(rs.public_key(), as_dict=True), kid="rs", alg="RS256")]
        project = "https://test-project.supabase.co"
        issuer = project + "/auth/v1"
        subject = str(uuid4())
        signed_claims = dict(sub=subject, iat=int(time.time() - 1), exp=int(time.time() + 120),
                             iss=issuer, aud="authenticated", role="authenticated", session_id=str(uuid4()))

        def headers(key=es, alg="ES256", kid="es", **changes):
            token = jwt.encode({**signed_claims, **changes}, key, algorithm=alg, headers={"kid": kid})
            return {"Authorization": "Bearer " + token}

        active = jwks[:1]
        def load(url, **kwargs):
            self.assertEqual(url, issuer + "/.well-known/jwks.json")
            self.assertFalse(kwargs["follow_redirects"])
            return httpx.Response(200, json={"keys": active}, request=httpx.Request("GET", url))

        with patch.multiple(settings, environment="production", supabase_url=project, v1_provider_mode="live",
                            groq_api_key="synthetic"), patch("backend.run_worker.auth.httpx.get", side_effect=load):
            self.addCleanup(supabase_keys.cache_clear)
            first = self.client.post("/runs", headers=headers(), json=self.body)
            self.assertEqual(first.status_code, 202)
            run = f'/runs/{first.json()["run_id"]}'
            self.assertEqual(self.client.get(run, headers=headers()).status_code, 200)
            self.assertEqual(self.client.get(run, headers=headers(sub=str(uuid4()))).status_code, 404)
            self.assertEqual(self.client.get("/runs", headers=headers(sub=str(uuid4()))).json()["runs"], [])
            for changes in (dict(role="service_role"), dict(aud="anon"), dict(iss="https://wrong.invalid/auth/v1"),
                            dict(exp=1), dict(is_anonymous=True), dict(session_id="missing")):
                response = self.client.get(run, headers=headers(**changes))
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
            self.assertEqual(self.client.get(run, headers=self.headers(subject)).status_code, 401)
            active[:] = jwks[1:]
            supabase_keys(issuer).refresh_after = 0
            self.assertEqual(self.client.get(run, headers=headers(rs, "RS256", "rs")).status_code, 200)
            self.assertEqual(self.client.get(run, headers=headers()).status_code, 401)

    def test_readiness_requires_migration_and_recent_worker(self):
        from backend.main import app as main_app

        with TestClient(main_app) as client, patch.object(settings, "database_url", self.dsn):
            self.assertEqual(client.get("/health").json(), {"status": "healthy"})
            self.assertEqual(client.get("/ready").status_code, 503)
            with self.database.connect() as connection:
                connection.execute("INSERT INTO v1_worker_heartbeats VALUES ('fake', clock_timestamp())")
            self.assertEqual(client.get("/ready").status_code, 503)
            self.database.heartbeat("fake")
            self.assertEqual(client.get("/ready").json(), {"status": "ready"})
            with self.database.connect() as connection:
                connection.execute("UPDATE v1_worker_heartbeats SET seen_at=clock_timestamp()-interval '1 minute'")
            self.assertEqual(client.get("/ready").status_code, 503)
            with patch.object(Store, "ready", side_effect=psycopg.errors.UndefinedTable("sensitive database detail")):
                unavailable = client.get("/ready")
            self.assertEqual(unavailable.status_code, 503)
            self.assertEqual(unavailable.json(), {"status": "unready"})

    def test_production_cors_and_redacted_unexpected_errors(self):
        from backend.main import create_app

        with patch.multiple(settings, environment="production", cors_origins="https://ui.example.com",
                            supabase_url="https://test-project.supabase.co", v1_provider_mode="live",
                            groq_api_key="synthetic", database_url=self.dsn):
            with TestClient(create_app()) as client:
                headers = {"Origin": "https://ui.example.com", "Access-Control-Request-Method": "POST",
                           "Access-Control-Request-Headers": "authorization,idempotency-key,last-event-id"}
                allowed = client.options("/api/v1/runs", headers=headers)
                self.assertEqual(allowed.headers["access-control-allow-origin"], headers["Origin"])
                self.assertNotIn("access-control-allow-credentials", allowed.headers)
                denied = client.options("/api/v1/runs", headers={**headers, "Origin": "https://evil.example.com"})
                self.assertNotIn("access-control-allow-origin", denied.headers)
                denied_method = client.options("/api/v1/runs", headers={**headers, "Access-Control-Request-Method": "DELETE"})
                self.assertEqual(denied_method.status_code, 400)
                no_token = client.get("/api/v1/runs", params={"access_token": "secret"})
                self.assertEqual(no_token.status_code, 401)
                self.assertEqual(no_token.headers["Cache-Control"], "private, no-store")
                with patch.object(Store, "ready", side_effect=RuntimeError("credentials=secret")), self.assertLogs() as logs:
                    response = client.get("/ready?private=secret")
                self.assertEqual(response.status_code, 500)
                self.assertNotIn("secret", response.text + "".join(logs.output))

            for value in ("*", "http://ui.example.com", "https://ui.example.com/path", "https://user:secret@ui.example.com"):
                with patch.object(settings, "cors_origins", value), self.assertRaises(ValueError):
                    create_app()

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_live_review_is_pinned_owner_scoped_and_recovers_without_reexecution(self):
        outputs = json.loads(FIXTURE.read_text(encoding="utf-8"))

        def provider(step_id, body, upstream):
            if step_id == "pitch_deck":
                return {"slides": outputs[step_id]}
            return outputs[step_id]["personas"] if step_id == "customer_personas" else outputs[step_id]

        for verdict, expected in (("approve", "succeeded"), ("reject", "partial")):
            with patch.multiple(settings, v1_provider_mode="live", groq_api_key="synthetic", v1_require_founder_review=True):
                initial = self.client.post("/runs", headers=self.headers(), json=self.body).json()
            run_id = initial["run_id"]
            execute_claim(self.database, self.database.claim(), provider)
            paused = self.database.snapshot("alice", run_id)
            self.assertEqual(paused["status"], "awaiting_review")
            self.assertIsNone(self.database.claim())
            review = paused["pending_review"]
            self.assertEqual(review["artifact_ids"], ["executive_summary"])
            self.assertEqual(len(paused["artifacts"]), 16)
            path = f'/runs/{run_id}/reviews/{review["review_id"]}/decisions'
            body = {"decision_id": str(uuid4()), "decision": verdict}
            self.assertEqual(self.client.post(path, headers=self.headers("bob"), json=body).status_code, 404)
            receipt = self.client.post(path, headers=self.headers(), json=body)
            self.assertEqual(receipt.status_code, 200)
            self.assertEqual(self.client.post(path, headers=self.headers(), json=body).json(), receipt.json())
            self.assertEqual(self.client.post(path, headers=self.headers(), json={**body, "comment": "changed"}).status_code, 409)
            if verdict == "approve":
                restarted = Store(self.dsn)
                execute_claim(restarted, restarted.claim(), Mock(side_effect=AssertionError("Agents already completed")))
            final = self.client.get(f"/runs/{run_id}", headers=self.headers()).json()
            self.assertEqual(final["status"], expected)
            stream = self.client.get(f"/runs/{run_id}/events", headers=self.headers())
            events = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
            decision = next(event["data"] for event in events if event["type"] == "review.decided")
            self.assertEqual(decision, receipt.json())
            self.assertEqual(replay(initial, events), final)

    def test_live_worker_marks_budget_failure_before_dispatch(self):
        initial = self.graph_run("tiny", mode="live", token_limit=1)
        with patch("backend.run_worker.worker.live_provider", fixture_provider):
            execute_claim(self.database, self.database.claim())
        final = self.database.snapshot("alice", initial["run_id"])
        self.assertEqual(final["status"], "failed")
        self.assertEqual(final["error"]["code"], "budget_exceeded")
        with self.database.connect() as connection:
            self.assertEqual(connection.execute("SELECT count(*) AS n FROM v1_llm_attempts").fetchone()["n"], 0)

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
        persisted = self.database.events("alice", run_id, 0)
        self.assertTrue(persisted[-1]["occurred_at"].endswith("+00:00"))
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
        initial = self.client.post("/runs", headers=self.headers(), json=self.body).json()
        path = f'/runs/{initial["run_id"]}'
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
                stream = pool.submit(self.client.get, f"{path}/events", headers=self.headers())
                self.assertTrue(subscribed.wait(5))
                execute_claim(self.database, self.database.claim())
                response = stream.result(timeout=10)
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            self.assertEqual(replay(initial, events), self.client.get(path, headers=self.headers()).json())
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
        forged = {"Authorization": "Bearer " + jwt.encode(dict(sub="alice", exp=int(time.time()+60)),
                                                          secrets.token_hex(32), algorithm="HS256")}
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

    def test_exports_and_legacy_routes_disabled(self):
        run_id = self.submit()["run_id"]
        self.assertEqual(self.client.get(f"/runs/{run_id}/exports/pdf", headers=self.headers()).status_code, 409)
        execute_claim(self.database, self.database.claim())
        for format, prefix in [("markdown", b"#"), ("pdf", b"%PDF"), ("pptx", b"PK")]:
            response = self.client.get(f"/runs/{run_id}/exports/{format}", headers=self.headers())
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content.startswith(prefix))
            self.assertIn("attachment", response.headers["content-disposition"])
        from backend.main import app as main_app
        client = TestClient(main_app)
        legacy = [("POST", "/api/run"), ("GET", "/api/runs"), ("GET", f"/api/run/{run_id}"),
                  ("GET", f"/api/run/{run_id}/result"), ("GET", f"/api/run/{run_id}/stream"),
                  ("GET", f"/api/run/{run_id}/export/markdown"), ("DELETE", f"/api/run/{run_id}")]
        for method, path in legacy:
            self.assertEqual(client.request(method, path).status_code, 404, path)
            self.assertEqual(client.request(method, path, headers=self.headers()).status_code, 404, path)
        response = client.get(f"/api/v1/runs/{run_id}", headers=self.headers())
        self.assertEqual(response.status_code, 200)
        client.close()

    def test_live_submission_fails_without_provider_credentials(self):
        with patch.object(settings, "v1_provider_mode", "live"), patch.object(settings, "groq_api_key", ""):
            response = self.client.post("/runs", json=self.body, headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertIn("GROQ_API_KEY", response.json()["error"]["message"])
        self.assertIsNone(self.database.claim())

    @patch("backend.run_worker.worker.call_with_deadline", inline_call)
    def test_older_pinned_runs_complete_after_new_prompt_default(self):
        claim_options = dict(versions=(LIVE_VERSION,), prompt_versions=PROMPT_BUNDLES, model_profiles=PROFILES)
        model = PROFILES[PROFILE_VERSION][0]
        step = "problem_refined"
        for prior in (None, "reserved", "succeeded"):
            with self.subTest(prior=prior):
                initial = self.database.submit("alice", f"older-{prior}", self.body, version=LIVE_VERSION)
                run_id = initial["run_id"]
                if prior:
                    claim = self.database.claim(**claim_options)
                    self.database.begin_step(*claim, step)
                    ledger = AttemptLedger(self.database, *claim, step)
                    attempt = ledger.reserve(model, 200, 100)
                    if prior == "succeeded":
                        ledger.settle(attempt, prior, actual_model=model.name, usage=(200, 100),
                                      cost=model.cost(200, 100))
                    self.expire(run_id)

                with patch("backend.run_worker.store.PROMPT_VERSION", "startup-prompts-v2"), \
                     patch("backend.run_worker.live_agents.PROMPT_VERSION", "startup-prompts-v2"), \
                     patch("backend.run_worker.worker.live_provider", fixture_provider), \
                     patch.object(settings, "v1_step_concurrency", 1):
                    newer = self.database.submit("alice", "new-prompt-default", self.body, version=LIVE_VERSION)
                    restarted = Store(self.dsn)
                    replacement = restarted.claim(**claim_options)
                    self.assertEqual(replacement[0], run_id)
                    self.assertEqual(restarted.live_configuration(*replacement)["prompt_version"], PROMPT_VERSION)
                    if prior:
                        history = AttemptLedger(restarted, *replacement, step).history()
                        self.assertEqual(history[0]["wait"], 0)
                    execute_claim(restarted, replacement)
                    self.assertIsNone(restarted.claim(**claim_options))

                final = restarted.snapshot("alice", run_id)
                self.assertEqual(final["status"], "succeeded")
                self.assertEqual(len(final["artifacts"]), 16)
                self.assertEqual(replay(initial, restarted.events("alice", run_id, 0)), final)
                self.assertEqual(restarted.snapshot("alice", newer["run_id"])["status"], "queued")
                with restarted.connect() as connection:
                    attempts = connection.execute(
                        """SELECT status, charged_tokens FROM v1_llm_attempts
                           WHERE run_id=%s AND step_id=%s ORDER BY attempt_no""", (run_id, step)
                    ).fetchall()
                expected = [{"status": "succeeded", "charged_tokens": 400}]
                if prior:
                    previous = "unknown" if prior == "reserved" else prior
                    expected.insert(0, {"status": previous, "charged_tokens": 300})
                self.assertEqual(attempts, expected)

    def test_all_live_agents_publish_committed_artifacts_and_export_real_content(self):
        from io import BytesIO
        from pptx import Presentation
        from reportlab import rl_config

        with patch.object(settings, "v1_provider_mode", "live"), patch.object(settings, "groq_api_key", "synthetic"):
            response = self.client.post("/runs", json=self.body, headers=self.headers())
        self.assertEqual(response.status_code, 202)
        initial = response.json()
        run_id = initial["run_id"]
        self.assertEqual(initial["manifest"]["version"], REVIEWED_VERSION)
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
            execute_claim(self.database, self.database.claim(versions=(REVIEWED_VERSION,)))
        final = self.client.get(f"/runs/{run_id}", headers=self.headers()).json()
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(set(seen), set(LIVE_STEPS))
        self.assertEqual(len(final["artifacts"]), 16)
        with self.database.connect() as connection:
            usage = connection.execute(
                """SELECT count(*) AS attempts, count(DISTINCT step_id) AS steps,
                   SUM(charged_tokens) AS tokens, SUM(charged_cost_nanousd) AS cost,
                   array_agg(DISTINCT actual_model) AS models FROM v1_llm_attempts WHERE run_id=%s""", (run_id,)
            ).fetchone()
        self.assertEqual(usage, {"attempts": 16, "steps": 16, "tokens": 6400, "cost": 1_680_000,
                                 "models": ["openai/gpt-oss-120b"]})
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
        self.assertIn("**Estimated Infra Cost:** Unavailable", markdown.text)
        self.assertNotIn("Fake-provider demonstration", markdown.text)
        with patch.object(rl_config, "pageCompression", 0):
            pdf = self.client.get(f"{exports}/pdf", headers=self.headers())
        self.assertEqual(pdf.status_code, 200)
        self.assertIn(b"Campus Bridge connects busy students", pdf.content)
        self.assertIn(b"Campus Pilot", pdf.content)
        for expected in (b"Customer Personas", b"Product Design", b"MVP Roadmap", b"Business Model",
                         b"Technical Architecture", b"CREATE TABLE verified_roles", b"Security and Compliance",
                         b"A Verified Internship Gap"):
            self.assertIn(expected, pdf.content)
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
