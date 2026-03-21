"""
Layer 2: Agent 10 — Risk Analyst (parallel-eligible)
Identifies top 10 startup risks and mitigation strategies.
"""
from backend.agents.base import BaseAgent
from backend.context import RunContext


PROMPT_TEMPLATE = """You are a Startup Risk Management Consultant using PESTLE + startup risk frameworks.

Startup: {startup_name}
Domain: {domain}
Business Model: {business_model_type}
Tech Stack: {tech_hint}
Target Market: {target_market}

Identify the 10 most critical risks this startup faces. Be specific to this startup — not generic.

Output EXACTLY this JSON:

```json
{{
  "risks": [
    {{
      "risk_id": "R-01",
      "category": "market|technical|financial|regulatory|operational|competitive",
      "title": "Short risk title",
      "description": "Specific description of this risk for this startup",
      "probability": "high|medium|low",
      "impact": "high|medium|low",
      "risk_score": "critical|high|medium|low",
      "time_horizon": "immediate|short-term (0-6mo)|long-term (6mo+)",
      "mitigation_strategy": "Specific actionable mitigation for this startup",
      "early_warning_signals": "How would you detect this risk early?"
    }}
  ],
  "top_3_critical_risks": ["R-01", "R-03", "R-07"],
  "risk_summary": "Two-sentence summary of the overall risk profile",
  "recommended_risk_reviews": "Monthly|Quarterly"
}}
```
"""


class Agent10_RiskAnalyst(BaseAgent):
    name = "Agent10_RiskAnalyst"
    layer = 2

    def build_prompt(self, ctx: RunContext, external_research: str = "") -> str:
        idea = ctx.startup_idea
        biz = ctx.business_model
        revenue = biz.get("revenue_streams", [{}])
        model_type = revenue[0].get("model", "SaaS") if revenue else "SaaS"
        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            domain=ctx.domain or "Technology",
            business_model_type=model_type,
            tech_hint="Cloud SaaS, AI/ML, API-driven",
            target_market=idea.get("target_customer", ""),
        )

    def parse_output(self, raw: str) -> dict:
        return self.extract_json(raw)

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.risk_register = parsed
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.risk_register = {"risks": []}
        return ctx
