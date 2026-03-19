"""
context.py — Shared RunContext dataclass passed between all 16 agents
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid


@dataclass
class RunContext:
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    problem_raw: str = ""
    domain: Optional[str] = None
    geography: Optional[str] = None

    # Agent outputs
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

    # Pipeline metadata
    status: dict = field(default_factory=dict)  # Per-agent status tracking
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    user_id: Optional[str] = None

    def merge(self, other: "RunContext") -> None:
        """Merge another RunContext's agent outputs into this one (for parallel phase)."""
        fields_to_merge = [
            "mvp_roadmap", "business_model", "pricing_strategy",
            "financial_projections", "risk_register",
            "pitch_deck", "executive_summary"
        ]
        for f in fields_to_merge:
            val = getattr(other, f)
            if val:
                setattr(self, f, val)
        # Merge statuses
        self.status.update(other.status)

    def to_summary_dict(self) -> dict:
        """Return a lightweight summary for SSE status events."""
        return {
            "run_id": self.run_id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
