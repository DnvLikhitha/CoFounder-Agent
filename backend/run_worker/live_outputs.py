"""Publication schemas for the existing agents' live JSON artifacts."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints, model_validator


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Money = Annotated[float, Field(ge=0)]
OneToTwelve = Annotated[int, Field(ge=1, le=12)]


class Output(BaseModel):
    # The original JSON is persisted, including agent-specific fields and tool evidence.
    model_config = ConfigDict(strict=True, allow_inf_nan=False)


class RefinedProblem(Output):
    problem_refined: Text
    domain_confirmed: Text | None = None


class StartupIdea(Output):
    startup_name: Text
    tagline: Text
    one_liner: Text
    value_proposition: Text
    target_customer: Text
    key_differentiator: Text
    business_type: Text
    unfair_advantage: str = ""


class Segment(Output):
    segment: Text


class MarketResearch(Output):
    tam_usd_billions: Money | None
    sam_usd_billions: Money | None
    som_usd_millions: Money | None
    cagr_percent: float | None
    market_trends: list[Text] = Field(min_length=1)
    market_timing: Text
    target_segments: list[Segment] = Field(default_factory=list)


class Competitor(Output):
    name: Text
    strengths: list[Text]
    weaknesses: list[Text]


class CompetitorAnalysis(Output):
    # An explicit empty list is valid if the analysis still identifies market gaps.
    competitors: list[Competitor]
    market_gaps: list[Text] = Field(min_length=1)


class Persona(Output):
    name: Text
    job_title: Text
    pain_points: list[Text] = Field(min_length=1)
    willingness_to_pay_monthly_usd: Money | None = None


class CustomerPersonas(RootModel[Annotated[list[Persona], Field(min_length=1)]]):
    model_config = ConfigDict(strict=True)


class Feature(Output):
    feature: Text
    description: Text


class Flow(Output):
    flow_name: Text
    steps: list[Text] = Field(min_length=1)


class ProductDesign(Output):
    must_have_features: list[Feature] = Field(min_length=1)
    core_ux_flows: list[Flow] = Field(min_length=1)


class Story(Output):
    title: Text


class Sprint(Output):
    sprint_number: int = Field(ge=1)
    sprint_goal: Text
    duration_weeks: int = Field(ge=1)
    deliverable: Text
    user_stories: list[Story] = Field(default_factory=list)


class Roadmap(Output):
    sprints: list[Sprint] = Field(min_length=1)
    total_weeks: int = Field(ge=1)


class RevenueStream(Output):
    stream: Text
    model: Text
    description: Text


class LaunchPhase(Output):
    phase: Text
    strategy: Text
    target: Text


class Acquisition(Output):
    primary_channel: Text


class BusinessModel(Output):
    revenue_streams: list[RevenueStream] = Field(min_length=1)
    gtm_phases: list[LaunchPhase] = Field(min_length=1)
    customer_acquisition_strategy: Acquisition
    value_delivered_to_customer: Text


class Tier(Output):
    tier_name: Text
    price_monthly_usd: Money
    price_annual_usd: Money
    target_persona: Text


class Pricing(Output):
    pricing_rationale: Text
    tiers: list[Tier] = Field(min_length=1)


class Projection(Output):
    month: OneToTwelve
    total_customers: int = Field(ge=0)
    mrr_usd: Money
    net_profit_usd: float


class Financials(Output):
    assumptions: dict = Field(min_length=1)
    monthly_projections: list[Projection] = Field(min_length=12, max_length=12)
    # Zero denotes no projected break-even in the period, as in the v1 contract.
    breakeven_month: Annotated[int, Field(ge=0, le=12)] | None
    arr_month_12_usd: Money | None
    ltv_usd: Money | None
    cac_usd: Money | None
    ltv_cac_ratio: Money | None

    @model_validator(mode="after")
    def chronological_months(self):
        if [row.month for row in self.monthly_projections] != list(range(1, 13)):
            raise ValueError("Expected one projection for each month in order")
        return self


class Risk(Output):
    risk_id: Text
    title: Text
    probability: Literal["high", "medium", "low"]
    impact: Literal["high", "medium", "low"]
    mitigation_strategy: Text


class RiskRegister(Output):
    risks: list[Risk] = Field(min_length=1)


class Stack(Output):
    framework: Text


class Architecture(Output):
    architecture_description: Text
    frontend_stack: Stack
    backend_stack: Stack
    database: dict = Field(min_length=1)
    ai_layer: dict = Field(min_length=1)


class Entity(Output):
    entity: Text
    purpose: Text


class DatabaseSchema(Output):
    sql_schema: Text
    entities: list[Entity] = Field(min_length=1)
    relationships: list[dict]


class Control(Output):
    item: Text
    status: Text
    action: Text


class SecurityCompliance(Output):
    owasp_top10_checklist: list[Control] = Field(min_length=1)
    compliance_requirements: list[dict]
    security_launch_checklist: list[Text] = Field(min_length=1)
    llm_safety_measures: list[Text] = Field(default_factory=list)


class Slide(Output):
    slide_number: OneToTwelve
    title: Text
    headline: Text
    bullet_points: list[Text] = Field(min_length=1)
    speaker_notes: str = ""


class PitchDeck(Output):
    slides: list[Slide] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def complete_deck(self):
        if {slide.slide_number for slide in self.slides} != set(range(1, 13)):
            raise ValueError("Expected one slide for each number from one to twelve")
        return self


class ExecutiveSummary(Output):
    executive_summary: Text
    one_liner: Text
    elevator_pitch: Text
    key_metrics_snapshot: dict[str, str | float | None] = Field(min_length=1)
