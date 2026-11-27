"""Small deterministic provider and dependency graph for the worker slice."""
from dataclasses import dataclass
import json

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from backend.contracts.v1 import StepDefinition, StepManifest


class Output(BaseModel):
    # Keep agent-specific fields in the original payload after checking its shape.
    model_config = ConfigDict(strict=True, allow_inf_nan=False)


class RevenueStream(Output):
    stream: str
    model: str
    description: str


class BusinessModel(Output):
    model: str = Field(min_length=1)
    revenue_streams: list[RevenueStream]
    gtm_phases: list[dict] = Field(default_factory=list)


class Tier(Output):
    tier_name: str = Field(min_length=1, validation_alias=AliasChoices("tier_name", "name"))
    price_monthly_usd: float = Field(ge=0)
    price_annual_usd: float = Field(default=0, ge=0)
    target_persona: str = ""


class Pricing(Output):
    tiers: list[Tier] = Field(min_length=1)


class Projection(Output):
    month: int = Field(ge=1)
    total_customers: int = Field(ge=0)
    mrr_usd: float = Field(ge=0)
    net_profit_usd: float


class Financials(Output):
    monthly_projections: list[Projection]
    breakeven_month: int = Field(ge=0)
    arr_month_12_usd: float = Field(default=0, ge=0)
    ltv_usd: float = Field(default=0, ge=0)
    cac_usd: float = Field(default=0, ge=0)
    ltv_cac_ratio: float = Field(default=0, ge=0)


class Risk(Output):
    risk_id: str
    title: str = Field(min_length=1)
    probability: str
    impact: str
    mitigation_strategy: str


class RiskRegister(Output):
    risks: list[Risk]


@dataclass(frozen=True)
class StepSpec:
    required: tuple[str, ...]
    optional: tuple[str, ...]
    output: type[Output]


STEPS = {
    "business_model": StepSpec((), ("startup_idea", "market_research", "competitor_analysis"), BusinessModel),
    "pricing_strategy": StepSpec(("business_model",), ("startup_idea", "competitor_analysis", "customer_personas"), Pricing),
    "financial_projections": StepSpec(("business_model", "pricing_strategy"), ("startup_idea", "market_research"), Financials),
    "risk_register": StepSpec(("business_model",), ("startup_idea",), RiskRegister),
}
DEPENDENCIES = {name: list(spec.required) for name, spec in STEPS.items()}
MANIFEST = StepManifest(version="fake-business-v2", steps=[
    StepDefinition(step_id=name, label=name.replace("_", " ").title(),
                   phase="Business", order=index, depends_on=dependencies,
                   required=True, artifact_kinds=[name])
    for index, (name, dependencies) in enumerate(DEPENDENCIES.items())
])


class ProviderFailure(Exception):
    """Expected provider failure with a sanitized public error."""


@dataclass(frozen=True)
class PartialOutput:
    """A provider explicitly identifies usable but incomplete output."""
    content: dict


class InvalidOutput(ValueError):
    pass


JSON_VALUE = TypeAdapter(JsonValue)


def validate_output(step_id, content):
    try:
        STEPS[step_id].output.model_validate(content)
        JSON_VALUE.validate_python(content)
        json.dumps(content, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise InvalidOutput(step_id) from exc


def fake_provider(step_id, run_input, upstream):
    spec = STEPS[step_id]
    if not set(spec.required) <= upstream.keys() <= set(spec.required + spec.optional):
        raise ValueError("Provider received incorrect dependencies")
    outputs = {
        "business_model": {"model": "subscription", "revenue_streams": []},
        "pricing_strategy": {"tiers": [{"tier_name": "Starter", "price_monthly_usd": 10}]},
        "financial_projections": {"monthly_projections": [], "breakeven_month": 12},
        "risk_register": {"risks": []},
    }
    return {**outputs[step_id], "provider": "fake", "problem": run_input["problem"],
            "upstream": upstream}
