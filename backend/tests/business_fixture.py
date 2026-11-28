"""Small graph used by focused storage and fault-injection tests."""
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from backend.run_worker.workflow import StepSpec


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


BUSINESS_FIXTURE_VERSION = "test-business-fixture"
BUSINESS_FIXTURE_STEPS = {
    "business_model": StepSpec((), ("startup_idea", "market_research", "competitor_analysis"), BusinessModel),
    "pricing_strategy": StepSpec(("business_model",), ("startup_idea", "competitor_analysis", "customer_personas"), Pricing),
    "financial_projections": StepSpec(("business_model", "pricing_strategy"), ("startup_idea", "market_research"), Financials),
    "risk_register": StepSpec(("business_model",), ("startup_idea",), RiskRegister),
}


def business_response(step_id, run_input, upstream):
    outputs = {
        "business_model": {"model": "subscription", "revenue_streams": []},
        "pricing_strategy": {"tiers": [{"tier_name": "Starter", "price_monthly_usd": 10}]},
        "financial_projections": {"monthly_projections": [], "breakeven_month": 12},
        "risk_register": {"risks": []},
    }
    return {**outputs[step_id], "provider": "test-fixture", "problem": run_input["problem"],
            "upstream": upstream}
