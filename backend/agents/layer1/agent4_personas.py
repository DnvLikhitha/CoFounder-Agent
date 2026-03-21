"""
Layer 1: Agent 4 — Customer Persona Builder
Creates 2 detailed Ideal Customer Profile (ICP) personas.
"""
from backend.agents.base import BaseAgent
from backend.context import RunContext


PROMPT_TEMPLATE = """You are a UX Researcher and Customer Development expert.

Startup: {startup_name}
Problem: {problem_refined}
Target Customer Hypothesis: {target_customer}
Market Segments: {segments}

Create 2 detailed Ideal Customer Profile (ICP) personas that represent the best customers for this startup.

These should be realistic, named people — not generic archetypes.

Output EXACTLY this JSON:

```json
{{
  "personas": [
    {{
      "persona_id": "primary",
      "name": "A realistic full name",
      "age": 32,
      "job_title": "Specific job title",
      "company_type": "Type and size of company",
      "location": "City, Country",
      "annual_income_usd": 85000,
      "tech_savviness": "high|medium|low",
      "pain_points": [
        "Specific pain point 1",
        "Specific pain point 2",
        "Specific pain point 3"
      ],
      "goals": [
        "What they're trying to achieve",
        "Career or business goal"
      ],
      "current_tools_used": ["Tool 1", "Tool 2", "Tool 3"],
      "buying_triggers": ["What event makes them look for a solution"],
      "buying_blockers": ["What stops them from buying"],
      "preferred_channels": ["LinkedIn", "Google Search", "Word of mouth"],
      "willingness_to_pay_monthly_usd": 79,
      "quote": "A realistic quote they might say about this problem"
    }},
    {{
      "persona_id": "secondary",
      "name": "Second persona name",
      "age": 45,
      "job_title": "Different role",
      "company_type": "Different company type",
      "location": "City, Country",
      "annual_income_usd": 120000,
      "tech_savviness": "medium",
      "pain_points": ["Pain 1", "Pain 2"],
      "goals": ["Goal 1"],
      "current_tools_used": ["Tool 1"],
      "buying_triggers": ["Trigger 1"],
      "buying_blockers": ["Blocker 1"],
      "preferred_channels": ["Email", "Industry conferences"],
      "willingness_to_pay_monthly_usd": 199,
      "quote": "Their realistic quote"
    }}
  ]
}}
```
"""


class Agent4_Personas(BaseAgent):
    name = "Agent4_Personas"
    layer = 1

    def build_prompt(self, ctx: RunContext, external_research: str = "") -> str:
        idea = ctx.startup_idea
        market = ctx.market_research
        segments = [s.get("segment", "") for s in market.get("target_segments", [])]
        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            problem_refined=ctx.problem_refined,
            target_customer=idea.get("target_customer", ""),
            segments=", ".join(segments) if segments else "general market",
        )

    def parse_output(self, raw: str) -> dict:
        return self.extract_json(raw)

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.customer_personas = parsed.get("personas", [])
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.customer_personas = []
        return ctx
