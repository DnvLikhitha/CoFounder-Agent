"""Versioned execution graphs and publication schemas for the durable worker."""
from dataclasses import dataclass
from graphlib import TopologicalSorter
import json
from types import MappingProxyType

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from backend import agents
from backend.agents.base import BaseAgent
from backend.contracts.v1 import StepDefinition, StepManifest
from backend.run_worker import live_outputs


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
    output: type[BaseModel] | None
    agent: type[BaseAgent] | None = None
    label: str | None = None
    phase: str = "Business"


LIVE_VERSION = "live-startup-v1"
GRAPH_VERSION = "startup-langgraph-v1"
FAKE_VERSIONS = ("fake-business-v1", "fake-business-v2")
LIVE_STEPS = MappingProxyType({
    "problem_refined": StepSpec((), (), live_outputs.RefinedProblem,
                                agents.Agent0_Refiner, "Problem Refiner", "Foundation"),
    "startup_idea": StepSpec(("problem_refined",), (), live_outputs.StartupIdea,
                             agents.Agent1_IdeaGenerator, "Idea Generator", "Foundation"),
    "market_research": StepSpec(("problem_refined", "startup_idea"), (), live_outputs.MarketResearch,
                                 agents.Agent2_MarketResearch, "Market Research", "Research"),
    "competitor_analysis": StepSpec(("problem_refined", "startup_idea"), (), live_outputs.CompetitorAnalysis,
                                    agents.Agent3_Competitors, "Competitor Analysis", "Research"),
    "customer_personas": StepSpec(("problem_refined", "startup_idea", "market_research"),
                                  (), live_outputs.CustomerPersonas, agents.Agent4_Personas,
                                  "Customer Personas", "Research"),
    "product_design": StepSpec(("problem_refined", "startup_idea", "customer_personas"),
                               (), live_outputs.ProductDesign, agents.Agent5_ProductDesigner,
                               "Product Designer", "Product"),
    "mvp_roadmap": StepSpec(("startup_idea", "product_design"), (), live_outputs.Roadmap,
                            agents.Agent6_MVPRoadmap, "MVP Roadmap", "Product"),
    "business_model": StepSpec(("startup_idea", "market_research", "competitor_analysis"),
                                (), live_outputs.BusinessModel, agents.Agent7_BusinessModel, "Business Model"),
    "pricing_strategy": StepSpec(("startup_idea", "business_model"), ("competitor_analysis", "customer_personas"),
                                 live_outputs.Pricing, agents.Agent8_Pricing, "Pricing Strategy"),
    "financial_projections": StepSpec(("startup_idea", "market_research", "business_model", "pricing_strategy"),
                                       (), live_outputs.Financials, agents.Agent9_Financials, "Financial Projections"),
    "risk_register": StepSpec(("startup_idea", "business_model"), (), live_outputs.RiskRegister,
                               agents.Agent10_RiskAnalyst, "Risk Analyst"),
    "tech_architecture": StepSpec(("startup_idea", "product_design"), ("market_research",),
                                  live_outputs.Architecture, agents.Agent11_TechArchitecture,
                                  "Technical Architecture", "Technical"),
    "database_schema": StepSpec(("startup_idea", "product_design", "business_model", "customer_personas"),
                                 (), live_outputs.DatabaseSchema, agents.Agent12_DatabaseSchema,
                                 "Database Schema", "Technical"),
    "security_compliance": StepSpec(("startup_idea", "product_design"), (), live_outputs.SecurityCompliance,
                                     agents.Agent13_Security, "Security and Compliance", "Technical"),
    "pitch_deck": StepSpec(("problem_refined", "startup_idea", "market_research", "business_model",
                           "pricing_strategy", "financial_projections"), ("competitor_analysis",),
                          live_outputs.PitchDeck, agents.Agent14_PitchDeck, "Pitch Deck", "Investor"),
    "executive_summary": StepSpec(("problem_refined", "startup_idea", "market_research", "business_model",
                                   "pricing_strategy", "financial_projections"), ("risk_register",),
                                  live_outputs.ExecutiveSummary, agents.Agent15_ExecutiveSummary,
                                  "Executive Summary", "Investor"),
})


def check_graph(dependencies):
    for name, inputs in dependencies.items():
        missing = set(inputs) - dependencies.keys()
        if missing:
            raise ValueError(f"{name} references missing dependencies: {', '.join(sorted(missing))}")
    TopologicalSorter(dependencies).prepare()


check_graph({name: spec.required + spec.optional for name, spec in LIVE_STEPS.items()})


# Released entries and their output models are retained for in-flight runs.
WORKFLOWS = MappingProxyType({
    LIVE_VERSION: LIVE_STEPS,
    GRAPH_VERSION: LIVE_STEPS,
    "fake-business-v1": MappingProxyType({
        # The original worker validated Artifact.content as JSON only.
        "business_model": StepSpec((), (), None),
        "pricing_strategy": StepSpec(("business_model",), (), None),
        "financial_projections": StepSpec(("business_model", "pricing_strategy"), (), None),
        "risk_register": StepSpec(("business_model",), (), None),
    }),
    "fake-business-v2": MappingProxyType({
        "business_model": StepSpec((), ("startup_idea", "market_research", "competitor_analysis"), BusinessModel),
        "pricing_strategy": StepSpec(("business_model",), ("startup_idea", "competitor_analysis", "customer_personas"), Pricing),
        "financial_projections": StepSpec(("business_model", "pricing_strategy"), ("startup_idea", "market_research"), Financials),
        "risk_register": StepSpec(("business_model",), ("startup_idea",), RiskRegister),
    }),
})
CURRENT_VERSION = "fake-business-v2"


def current_manifest(version=None):
    version = version or CURRENT_VERSION
    return StepManifest(version=version, steps=[
        StepDefinition(step_id=name, label=spec.label or name.replace("_", " ").title(),
                       phase=spec.phase, order=index, depends_on=list(spec.required),
                       required=True, artifact_kinds=[name])
        for index, (name, spec) in enumerate(WORKFLOWS[version].items())
    ])


class ProviderFailure(Exception):
    """Expected provider failure with a sanitized public error."""


class ProviderTimeout(ProviderFailure):
    pass


@dataclass(frozen=True)
class PartialOutput:
    """A provider explicitly identifies usable but incomplete output."""
    content: dict


class InvalidOutput(ValueError):
    pass


JSON_VALUE = TypeAdapter(JsonValue)


def validate_output(version, step_id, content):
    try:
        model = WORKFLOWS[version][step_id].output
        if model is not None:
            model.model_validate(content)
        JSON_VALUE.validate_python(content)
        json.dumps(content, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise InvalidOutput(step_id) from exc


def fake_provider(step_id, run_input, upstream):
    outputs = {
        "business_model": {"model": "subscription", "revenue_streams": []},
        "pricing_strategy": {"tiers": [{"tier_name": "Starter", "price_monthly_usd": 10}]},
        "financial_projections": {"monthly_projections": [], "breakeven_month": 12},
        "risk_register": {"risks": []},
    }
    return {**outputs[step_id], "provider": "fake", "problem": run_input["problem"],
            "upstream": upstream}
