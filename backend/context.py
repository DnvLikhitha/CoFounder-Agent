"""Inputs for one agent and data collected for one exported report."""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class AgentInputs:
    problem_raw: str = ""
    domain: str | None = None
    geography: str | None = None

    problem_refined: str = ""               # Agent 0
    startup_idea: dict = field(default_factory=dict)           # Agent 1
    market_research: dict = field(default_factory=dict)        # Agent 2
    competitor_analysis: dict = field(default_factory=dict)    # Agent 3
    customer_personas: list = field(default_factory=list)      # Agent 4
    product_design: dict = field(default_factory=dict)         # Agent 5
    mvp_roadmap: dict = field(default_factory=dict)            # Agent 6
    business_model: dict = field(default_factory=dict)         # Agent 7
    pricing_strategy: dict = field(default_factory=dict)       # Agent 8
    financial_projections: dict = field(default_factory=dict)  # Agent 9
    risk_register: dict = field(default_factory=dict)          # Agent 10
    tech_architecture: dict = field(default_factory=dict)      # Agent 11
    database_schema: dict = field(default_factory=dict)        # Agent 12
    security_compliance: dict = field(default_factory=dict)    # Agent 13
    pitch_deck: dict = field(default_factory=dict)             # Agent 14
    executive_summary: dict = field(default_factory=dict)      # Agent 15


@dataclass
class ReportData:
    run_id: str
    problem_raw: str
    domain: str | None
    geography: str | None
    created_at: datetime
    completed_at: datetime

    problem_refined: str = ""               # Agent 0
    startup_idea: dict = field(default_factory=dict)           # Agent 1
    market_research: dict = field(default_factory=dict)        # Agent 2
    competitor_analysis: dict = field(default_factory=dict)    # Agent 3
    customer_personas: list = field(default_factory=list)      # Agent 4
    product_design: dict = field(default_factory=dict)         # Agent 5
    mvp_roadmap: dict = field(default_factory=dict)            # Agent 6
    business_model: dict = field(default_factory=dict)         # Agent 7
    pricing_strategy: dict = field(default_factory=dict)       # Agent 8
    financial_projections: dict = field(default_factory=dict)  # Agent 9
    risk_register: dict = field(default_factory=dict)          # Agent 10
    tech_architecture: dict = field(default_factory=dict)      # Agent 11
    database_schema: dict = field(default_factory=dict)        # Agent 12
    security_compliance: dict = field(default_factory=dict)    # Agent 13
    pitch_deck: dict = field(default_factory=dict)             # Agent 14
    executive_summary: dict = field(default_factory=dict)      # Agent 15
