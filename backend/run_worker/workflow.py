"""Small deterministic provider and dependency graph for the worker slice."""
from backend.contracts.v1 import StepDefinition, StepManifest

DEPENDENCIES = {
    "business_model": [],
    "pricing_strategy": ["business_model"],
    "financial_projections": ["business_model", "pricing_strategy"],
    "risk_register": ["business_model"],
}
MANIFEST = StepManifest(version="fake-business-v1", steps=[
    StepDefinition(step_id=name, label=name.replace("_", " ").title(),
                   phase="Business", order=index, depends_on=dependencies,
                   required=True, artifact_kinds=[name])
    for index, (name, dependencies) in enumerate(DEPENDENCIES.items())
])


class ProviderFailure(Exception):
    """Expected provider failure with a sanitized public error."""


def fake_provider(step_id, run_input, upstream):
    if set(upstream) != set(DEPENDENCIES[step_id]):
        raise ValueError("Provider received incorrect dependencies")
    outputs = {
        "business_model": {"model": "subscription", "revenue_streams": []},
        "pricing_strategy": {"tiers": [{"tier_name": "Starter", "price_monthly_usd": 10}]},
        "financial_projections": {"monthly_projections": [], "breakeven_month": 12},
        "risk_register": {"risks": []},
    }
    return {**outputs[step_id], "provider": "fake", "problem": run_input["problem"],
            "upstream": upstream}
