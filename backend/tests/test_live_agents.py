"""Existing agents exercised through the durable adapter without external services."""
import asyncio
from dataclasses import replace
from importlib import import_module
import json
from pathlib import Path
from threading import Event
from time import sleep
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from os import getpid

from backend import agents
from backend.agents.base import Research
from backend.config import Settings
from backend.context import AgentInputs
from backend.llm.profiles import STARTUP_PROMPTS_V1
from backend.run_worker import live_agents
from backend.run_worker.provider_call import ClaimCalls, call_with_deadline
from backend.run_worker.workflow import LIVE_STEPS, LIVE_VERSION, InvalidOutput, check_graph, validate_output
from backend.tests.business_fixture import business_response


FIXTURE = Path(__file__).parents[1] / "run_worker" / "demo_outputs.json"


class FixtureGroq:
    def __init__(self, *, api_key, **kwargs):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.complete))
        self.outputs = json.loads(FIXTURE.read_text(encoding="utf-8"))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def complete(self, model, messages, **kwargs):
        assert model == "openai/gpt-oss-120b"
        prompt = messages[-1]["content"]
        # Match an existing prompt by its stable introduction, before its inputs.
        for step_id, spec in LIVE_STEPS.items():
            module = import_module(spec.agent.__module__)
            if prompt.startswith(module.PROMPT_TEMPLATE.splitlines()[0]):
                payload = self.outputs[step_id]
                return SimpleNamespace(model=model, usage=SimpleNamespace(prompt_tokens=300, completion_tokens=100),
                                       choices=[SimpleNamespace(
                    message=SimpleNamespace(content=f"```json\n{json.dumps(payload)}\n```")
                )])
        raise AssertionError("No existing agent prompt matched")


def fixture_provider(step_id, body, upstream, *, prompt_version=STARTUP_PROMPTS_V1, groq=FixtureGroq, **options):
    # This function is importable by spawned worker children on Windows.
    search = "Verified internship research\nSource: https://example.org/audit-source"
    fred = "Federal Funds Rate: 4.25 (synthetic fixture)"
    with (
        patch("backend.llm.client.AsyncGroq", groq),
        patch("backend.agents.layer1.agent1_idea.search_web", new=AsyncMock(return_value=search)),
        patch("backend.agents.layer1.agent2_market.search_web", new=AsyncMock(return_value=search)),
        patch("backend.agents.layer1.agent2_market.fetch_fred_data", new=AsyncMock(return_value=fred)),
        patch("backend.agents.layer1.agent3_competitors.search_web", new=AsyncMock(return_value=search)),
        patch("backend.agents.layer2.agent9_financials.fetch_fred_data", new=AsyncMock(return_value=fred)),
    ):
        return live_agents.live_provider(step_id, body, upstream, prompt_version=prompt_version, **options)


def invalid_provider(step_id, body, upstream):
    raise InvalidOutput(step_id)


def hang_during_pricing(step_id, body, upstream):
    if step_id == "pricing_strategy":
        Event().wait()
    return business_response(step_id, body, upstream)


def wait_in_sibling_steps(marker_dir, step_id, body, upstream):
    if step_id in {"pricing_strategy", "risk_register"}:
        (Path(marker_dir) / f"{getpid()}.started").touch()
        while not (Path(marker_dir) / "release").exists():
            sleep(0.05)
    return business_response(step_id, body, upstream)


class LiveAgentTests(unittest.TestCase):
    def test_versioned_prompt_bundle_matches_its_fingerprint(self):
        live_agents.verify_prompt_bundles()

    def test_prompt_fingerprint_rejects_changes_in_rendering_dependencies(self):
        changes = {
            "backend/run_worker/prompts_v1.py": ('inputs["problem_refined"]["problem_refined"]', 'inputs["problem_refined"]["alternate_refinement"]'),
            "backend/context.py": ('problem_refined: str = ""', 'problem_refined: str = "Default refinement"'),
            "backend/agents/layer1/agent2_market.py": ('async def fetch_research', 'async def fetch_updated_research'),
            "backend/tools/search.py": ("--- Web Search Results ---", "--- Alternate Search Results ---"),
            "backend/tools/fred_client.py": ("Federal Funds Rate (%)", "Alternate Federal Funds Rate (%)"),
            "backend/llm/messages.py": ('"role": "system"', '"role": "developer"'),
        }
        original_read = Path.read_text
        for file, (before, after) in changes.items():
            with self.subTest(file=file):
                def changed_source(path, *args, **kwargs):
                    source = original_read(path, *args, **kwargs)
                    if path.as_posix().endswith("/" + file):
                        self.assertIn(before, source)
                        return source.replace(before, after, 1)
                    return source

                with patch.object(Path, "read_text", changed_source):
                    with self.assertRaisesRegex(ValueError, "startup-prompts-v1.*recorded fingerprint"):
                        live_agents.verify_prompt_bundles()

    def test_prompt_fingerprint_validates_the_registered_system_prompt(self):
        bundle = live_agents.PROMPT_BUNDLES[STARTUP_PROMPTS_V1]
        changed = replace(bundle, system_prompt="A different system prompt")
        with patch.object(live_agents, "PROMPT_BUNDLES", {STARTUP_PROMPTS_V1: changed}):
            with self.assertRaisesRegex(ValueError, "startup-prompts-v1.*recorded fingerprint"):
                live_agents.verify_prompt_bundles()

    def test_provider_dispatches_the_pinned_renderer_and_system_prompt(self):
        old = live_agents.PROMPT_BUNDLES[STARTUP_PROMPTS_V1]
        older_run = AsyncMock(return_value={"problem_refined": "Old render"})
        newer_run = AsyncMock(return_value={"problem_refined": "New render"})
        bundles = {
            STARTUP_PROMPTS_V1: replace(old, run_agent=older_run),
            "startup-prompts-v2": replace(old, run_agent=newer_run, system_prompt="New system prompt"),
        }
        step, body = "problem_refined", {"problem": "Synthetic problem"}
        with patch.object(live_agents, "PROMPT_BUNDLES", bundles), \
             patch.object(live_agents, "PROMPT_VERSION", "startup-prompts-v2"), \
             patch("backend.llm.client.AsyncGroq", FixtureGroq):
            for version, bundle in bundles.items():
                with self.subTest(version=version):
                    self.assertEqual(live_agents.live_provider(step, body, {}, prompt_version=version),
                                     bundle.run_agent.return_value)
                    called_step, called_body, upstream, client = bundle.run_agent.await_args.args
                    self.assertEqual((called_step, called_body, upstream), (step, body, {}))
                    self.assertEqual(client.system_prompt, bundle.system_prompt)
                    bundle.run_agent.assert_awaited_once()

    def test_registration_matches_all_existing_agents_and_rejects_empty_output(self):
        legacy = {getattr(agents, name) for name in dir(agents) if name.startswith("Agent")}
        self.assertEqual(len(legacy), 16)
        self.assertEqual({spec.agent for spec in LIVE_STEPS.values()}, legacy)
        for step_id in LIVE_STEPS:
            with self.subTest(step=step_id), self.assertRaises(InvalidOutput):
                validate_output(LIVE_VERSION, step_id, {})

    def test_graph_rejects_missing_dependency_and_cycle(self):
        with self.assertRaisesRegex(ValueError, "missing dependencies"):
            check_graph({"pricing": {"business"}})
        with self.assertRaisesRegex(ValueError, "cycle"):
            check_graph({"a": {"b"}, "b": {"a"}})

    def test_live_response_rejects_truncated_json_before_legacy_repair(self):
        llm = SimpleNamespace(complete=AsyncMock(return_value='{"problem_refined": "Truncated'))
        with self.assertRaises(InvalidOutput):
            asyncio.run(live_agents.run_agent("problem_refined", {"problem": "Synthetic problem"}, {}, llm))

    def test_invalid_output_survives_the_process_boundary(self):
        with ClaimCalls() as calls, self.assertRaises(InvalidOutput):
            call_with_deadline(invalid_provider, "pricing_strategy", {}, {}, 20, calls)

    def test_investor_prompts_keep_unavailable_metrics_explicit(self):
        ctx = AgentInputs(problem_refined="A concrete problem")
        for agent in (agents.Agent14_PitchDeck, agents.Agent15_ExecutiveSummary):
            prompt = agent().build_prompt(ctx)
            self.assertIn("TAM Unavailable, SAM Unavailable, CAGR Unavailable", prompt)
            self.assertNotIn("Month 8", prompt)
            self.assertNotIn("$50K", prompt)

    def test_reviewed_live_financial_prompt_includes_approved_annual_price(self):
        step_id = "financial_projections"
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        upstream = {name: fixture[name] for name in LIVE_STEPS[step_id].required}
        pricing = upstream["pricing_strategy"]
        tier = pricing["tiers"][0]
        tier.update(price_monthly_usd=37, price_annual_usd=369.50)
        pricing["founder_price_revision"] = {"tier_name": tier["tier_name"]}
        body = {"problem": "Find internships for university students."}
        llm = SimpleNamespace(complete=AsyncMock(return_value=json.dumps(fixture[step_id])))
        with patch.object(LIVE_STEPS[step_id].agent, "fetch_research", new=AsyncMock(return_value=Research())):
            asyncio.run(live_agents.run_audited_forecast_agent(step_id, body, upstream, llm))
            reviewed = llm.complete.await_args.args[0]
            asyncio.run(live_agents.run_agent(step_id, body, upstream, llm))
            historical = llm.complete.await_args.args[0]
        self.assertIn('"price_annual_usd": 369.5', reviewed)
        self.assertIn('"price_monthly_usd": 37', reviewed)
        self.assertIn("tier_customers", reviewed)
        self.assertIn("pricing_assumptions", reviewed)
        self.assertNotIn('"price_annual_usd": 369.5', historical)

    def test_finance_and_risk_regenerate_only_once_and_keep_strict_validation(self):
        outputs = json.loads(FIXTURE.read_text(encoding="utf-8"))
        run_agent = live_agents.PROMPT_BUNDLES[live_agents.REVIEWED_PROMPT_VERSION].run_agent
        founder_input = {"problem": "Find internships for university students."}
        for kind in ("financial_projections", "risk_register"):
            spec = LIVE_STEPS[kind]
            upstream = {name: outputs[name] for name in spec.required}
            valid = json.dumps(outputs[kind])
            malformed = '{"monthly_projections": [' if kind == "financial_projections" else valid.replace(
                '"probability": "medium"', '"probability": "Medium"').replace(
                '"probability": "high"', '"probability": "High"').replace('"probability": "low"', '"probability": "Low"')
            with self.subTest(kind=kind), patch.object(spec.agent, "fetch_research", new=AsyncMock(return_value=Research())) as research:
                llm = SimpleNamespace(complete=AsyncMock(side_effect=[malformed, valid]))
                result = asyncio.run(run_agent(kind, founder_input, upstream, llm))
                validate_output(LIVE_VERSION, kind, result)
                self.assertEqual(research.await_count, 1)
                self.assertEqual(llm.complete.await_count, 2)
                self.assertIn("Regenerate the entire JSON", llm.complete.await_args.args[0])
                self.assertGreater(llm.complete.await_args.kwargs["max_tokens"], 4096)
                llm.complete = AsyncMock(return_value=malformed)
                with self.assertRaises(InvalidOutput):
                    asyncio.run(run_agent(kind, founder_input, upstream, llm))
                self.assertEqual(llm.complete.await_count, 2)

    def test_supabase_loopback_is_available_in_development_with_asymmetric_auth(self):
        cfg = Settings(_env_file=None, supabase_url="http://127.0.0.1:55451", environment="development")
        self.assertTrue(cfg.uses_supabase)
        self.assertEqual(cfg.supabase_issuer, "http://127.0.0.1:55451/auth/v1")
        for origin, environment in [("http://example.test", "development"),
                                    ("http://127.0.0.1:55451", "production")]:
            with self.subTest(origin=origin, environment=environment):
                cfg = Settings(_env_file=None, supabase_url=origin, environment=environment)
                with self.assertRaises(ValueError):
                    _ = cfg.supabase_issuer

    def test_settings_require_explicit_mode_and_groq_credentials(self):
        for mode, key, environment, error in [
            ("", "", "production", "V1_PROVIDER_MODE"),
            ("fake", "", "production", "must be live"),
            ("live", "  ", "development", "GROQ_API_KEY"),
        ]:
            cfg = Settings(_env_file=None, v1_provider_mode=mode, groq_api_key=key, environment=environment)
            with self.subTest(mode=mode, env=environment), self.assertRaisesRegex(ValueError, error):
                cfg.require_v1_provider_mode()
        cfg = Settings(_env_file=None, v1_provider_mode="live", groq_api_key="synthetic", environment="production")
        self.assertEqual(cfg.require_v1_provider_mode(), "live")
