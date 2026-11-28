"""Provider-free checks for the domain rubric and evidence attribution."""
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from backend.run_worker.evaluator import DIMENSIONS, domain_errors, evidence_links, heuristic, judge_provider
from backend.run_worker.workflow import LIVE_STEPS, REVIEWED_VERSION, InvalidOutput, validate_output

FIXTURE = Path(__file__).parent / "fixtures" / "evaluation_cases.json"


class DeterministicEvaluationTests(unittest.TestCase):
    def test_judge_preserves_artifact_and_marks_context_dependent_checks_when_inputs_are_omitted(self):
        content = {"slides": [{"speaker_notes": 'Detailed "notes" ' * 480}, {"title": "Final slide"}]}
        upstream = {"financial_projections": {"note": "x" * 18_000}, "pricing_strategy": {"tier": "Starter"}}
        scores = {name: 0 if name in {"consistency", "grounding"} else 2 for name in DIMENSIONS}
        with patch("backend.llm.client.LLMClient") as client:
            call = client.return_value.complete = AsyncMock(return_value=json.dumps(scores))
            evaluation = judge_provider("pitch_deck", {"input": {}, "content": content}, upstream,
                                        database=None, claim=("run", "claim"), profile=None, timeout=2)
        prompt = call.await_args.args[0]
        self.assertLessEqual(len(prompt), 18_000)
        payload = json.loads(prompt)
        self.assertEqual(payload["artifact"], content)
        self.assertEqual(payload["upstream"], {"pricing_strategy": upstream["pricing_strategy"]})
        self.assertEqual(payload["omitted_upstream"], ["financial_projections"])
        self.assertEqual(evaluation["outcome"], "needs_review")
        self.assertEqual({item["dimension"] for item in evaluation["dimensions"] if item["outcome"] == "needs_review"},
                         {"consistency", "grounding"})

    def test_oversized_artifact_skips_the_optional_judge_before_dispatch(self):
        with patch("backend.llm.client.LLMClient") as client:
            evaluation = judge_provider("database_schema", {"input": {}, "content": {"sql_schema": "x" * 18_001}},
                                        {}, database=None, claim=("run", "claim"), profile=None, timeout=2)
        client.assert_not_called()
        self.assertEqual(evaluation["outcome"], "not_evaluated")

    def test_revised_forecast_checks_annual_allocations_and_stale_revenue(self):
        from backend.run_worker.graph import demo_provider

        pricing = demo_provider("pricing_strategy", {}, {})
        tier = pricing["tiers"][0]
        tier.update(price_monthly_usd=37, price_annual_usd=370)
        pricing["founder_price_revision"] = tier
        upstream = {"pricing_strategy": pricing}
        forecast = demo_provider("financial_projections", {}, upstream)
        row = forecast["monthly_projections"][0]
        row["tier_customers"][tier["tier_name"]] = {"monthly": 0, "annual": 1}
        row.update(mrr_usd=30.83, revenue_usd=30.83)
        forecast["total_12mo_revenue_usd"] = 2879.83
        self.assertEqual(domain_errors("financial_projections", forecast, upstream), [])
        row.update(mrr_usd=125, revenue_usd=125)
        self.assertIn("approved prices", domain_errors("financial_projections", forecast, upstream)[0])

    def test_all_live_schemas_reject_empty_output_and_demo_passes_domain_checks(self):
        from backend.run_worker.graph import demo_provider

        for step in LIVE_STEPS:
            with self.subTest(step=step):
                with self.assertRaises(InvalidOutput):
                    validate_output(REVIEWED_VERSION, step, {})
                artifact = demo_provider(step, {}, {})
                validate_output(REVIEWED_VERSION, step, artifact)
                self.assertEqual(domain_errors(step, artifact), [])

    def test_fixture_dimensional_outcomes_are_stable(self):
        from backend.run_worker.graph import demo_provider

        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for case in fixture["checks"]:
            step = case["step"]
            with self.subTest(step=step, patch=case["patch"]):
                content = {**demo_provider(step, fixture["founder"], {}), **case["patch"]}
                validate_output(REVIEWED_VERSION, step, content)
                self.assertEqual(bool(domain_errors(step, content)), case.get("domain_error", False))
                evaluation = heuristic(step, content, fixture["founder"], {}, step)
                dimensions = {entry["dimension"]: entry["outcome"] for entry in evaluation["dimensions"]}
                self.assertEqual(set(dimensions), set(DIMENSIONS))
                for dimension in ("relevance", "consistency"):
                    if dimension in case:
                        self.assertEqual(dimensions[dimension], case[dimension])

    def test_citations_require_an_actual_path_and_source_from_committed_research(self):
        url = "https://example.org/research"
        research = {"reference": {"artifact_id": "market_research-r2"},
                    "content": {"tam_usd_billions": 10, "tool_evidence": {"serpapi_sources": [url],
                        "fred_data": "- Federal Funds Rate (%): 4.25 (as of 2025-06-01)"}}}
        fred_url = "https://fred.stlouisfed.org/series/FEDFUNDS"
        body = {"tam_usd_billions": 10, "headline": "Estimate", "rates": f"Current rates: {fred_url}.",
                "evidence_claims": [
            {"claim_path": "/headline", "source_url": url},
            {"claim_path": "/missing", "source_url": url},
            {"claim_path": "/headline", "source_url": "https://example.org/invented"},
        ]}
        links = evidence_links(body, "pitch_deck", {"market_research": research})
        self.assertEqual({link["relationship"] for link in links}, {"citation", "matched_value", "research_context"})
        self.assertTrue(all(link["artifact_id"] == "market_research-r2" for link in links))
        self.assertEqual([(link["claim_path"], link["source_url"]) for link in links if link["relationship"] == "citation"],
                         [("/headline", url), ("/rates", fred_url)])
