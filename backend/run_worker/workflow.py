"""Versioned execution graphs and publication schemas for the durable worker."""
from dataclasses import dataclass
from graphlib import TopologicalSorter
import json
from types import MappingProxyType

from pydantic import BaseModel, JsonValue, TypeAdapter

from backend import agents
from backend.agents.base import BaseAgent
from backend.contracts.v1 import StepDefinition, StepManifest
from backend.run_worker import live_outputs


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
REVIEWED_VERSION = "startup-reviewed-v1"
GRAPH_VERSIONS = (GRAPH_VERSION, REVIEWED_VERSION)
RETIRED_DEMO_VERSIONS = ("fake-business-v1", "fake-business-v2")
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
    REVIEWED_VERSION: LIVE_STEPS,
})


def current_manifest(version=REVIEWED_VERSION):
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
