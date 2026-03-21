"""
Layer 2: Agent 7 — Business Model Strategist (parallel-eligible)
Designs monetization model and go-to-market strategy.
"""
from backend.agents.base import BaseAgent
from backend.context import RunContext


PROMPT_TEMPLATE = """You are a Business Model Strategist who has designed GTM strategies for 50+ startups.

Startup: {startup_name}
Value Proposition: {value_prop}
Target Customer: {target_customer}
Business Type: {business_type}
Top Competitors: {competitors}
Market Segments: {segments}

Design the complete business model and go-to-market strategy.

Output EXACTLY this JSON:

```json
{{
  "revenue_streams": [
    {{"stream": "Primary revenue stream", "model": "subscription|transaction|licensing|freemium", "description": "How it works"}},
    {{"stream": "Secondary revenue stream", "model": "...", "description": "..."}}
  ],
  "cost_structure": {{
    "fixed_costs": ["Infrastructure", "Team salaries", "Office"],
    "variable_costs": ["LLM API usage", "Customer support", "Marketing spend"],
    "estimated_monthly_burn_usd": 5000
  }},
  "customer_acquisition_strategy": {{
    "primary_channel": "Channel description",
    "secondary_channels": ["Channel 2", "Channel 3"],
    "early_traction_tactics": ["Tactic 1: post in X communities", "Tactic 2: cold email Y personas"],
    "viral_loop_potential": "high|medium|low",
    "expected_cac_usd": 150
  }},
  "gtm_phases": [
    {{"phase": "Phase 1 (Month 1-3)", "strategy": "Description", "target": "First 100 users"}},
    {{"phase": "Phase 2 (Month 4-6)", "strategy": "Description", "target": "1000 users"}},
    {{"phase": "Phase 3 (Month 7-12)", "strategy": "Description", "target": "Scale to 5000 users"}}
  ],
  "key_partnerships": ["Partner type 1", "Partner type 2"],
  "key_activities": ["Core activity 1", "Core activity 2"],
  "value_delivered_to_customer": "ROI or improvement quantified (e.g. saves 10 hours/week)"
}}
```
"""


class Agent7_BusinessModel(BaseAgent):
    name = "Agent7_BusinessModel"
    layer = 2

    def build_prompt(self, ctx: RunContext, external_research: str = "") -> str:
        idea = ctx.startup_idea
        market = ctx.market_research
        comp = ctx.competitor_analysis
        competitors = [c.get("name", "") for c in comp.get("competitors", [])[:3]]
        segments = [s.get("segment", "") for s in market.get("target_segments", [])]
        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            value_prop=idea.get("value_proposition", ""),
            target_customer=idea.get("target_customer", ""),
            business_type=idea.get("business_type", "B2B SaaS"),
            competitors=", ".join(competitors) if competitors else "existing alternatives",
            segments=", ".join(segments) if segments else "general market",
        )

    def parse_output(self, raw: str) -> dict:
        return self.extract_json(raw)

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.business_model = parsed
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.business_model = {"revenue_streams": [], "gtm_phases": []}
        return ctx
