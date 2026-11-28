"""Provider-free checks for the domain rubric and evidence attribution."""
import json
from pathlib import Path
import unittest

from backend.run_worker.evaluator import DIMENSIONS, domain_errors, evidence_links, heuristic
from backend.run_worker.workflow import LIVE_STEPS, REVIEWED_VERSION, InvalidOutput, validate_output

FIXTURE = Path(__file__).parent / "fixtures" / "evaluation_cases.json"


class DeterministicEvaluationTests(unittest.TestCase):
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
