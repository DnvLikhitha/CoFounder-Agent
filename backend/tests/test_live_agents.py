"""Existing agents exercised through the durable adapter without external services."""
import asyncio
from importlib import import_module
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from backend import agents
from backend.config import Settings
from backend.context import RunContext
from backend.run_worker import live_agents
from backend.run_worker.provider_call import ClaimCalls, call_with_deadline
from backend.run_worker.workflow import LIVE_STEPS, LIVE_VERSION, InvalidOutput, check_graph, validate_output


FIXTURE = Path(__file__).parent / "fixtures" / "live_agent_outputs.json"


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


def fixture_provider(step_id, body, upstream, **options):
    # This function is importable by spawned worker children on Windows.
    search = "Verified internship research\nSource: https://example.org/audit-source"
    fred = "Federal Funds Rate: 4.25 (synthetic fixture)"
    with (
        patch("backend.llm.client.AsyncGroq", FixtureGroq),
        patch("backend.agents.layer1.agent1_idea.search_web", new=AsyncMock(return_value=search)),
        patch("backend.agents.layer1.agent2_market.search_web", new=AsyncMock(return_value=search)),
        patch("backend.agents.layer1.agent2_market.fetch_fred_data", new=AsyncMock(return_value=fred)),
        patch("backend.agents.layer1.agent3_competitors.search_web", new=AsyncMock(return_value=search)),
        patch("backend.agents.layer2.agent9_financials.fetch_fred_data", new=AsyncMock(return_value=fred)),
    ):
        return live_agents.live_provider(step_id, body, upstream, **options)


def invalid_provider(step_id, body, upstream):
    raise InvalidOutput(step_id)


class LiveAgentTests(unittest.TestCase):
    def test_versioned_prompt_bundle_matches_its_fingerprint(self):
        self.assertEqual(live_agents.prompt_fingerprint(), live_agents.PROMPT_FINGERPRINT)

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
        ctx = RunContext(problem_refined="A concrete problem")
        for agent in (agents.Agent14_PitchDeck, agents.Agent15_ExecutiveSummary):
            prompt = agent(None).build_prompt(ctx)
            self.assertIn("TAM Unavailable, SAM Unavailable, CAGR Unavailable", prompt)
            self.assertNotIn("Month 8", prompt)
            self.assertNotIn("$50K", prompt)

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
