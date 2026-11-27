"""
Layer 4: Agent 15 — Executive Summary Writer
Synthesizes everything into a 1-page investor memo.
"""
from backend.agents.base import BaseAgent
from backend.agents.investor_metrics import investor_metrics
from backend.context import RunContext


PROMPT_TEMPLATE = """You are Paul Graham's writing assistant. Write like Paul Graham — clear, direct, no fluff.

You are synthesizing a full startup analysis into a 1-page executive summary that an investor reads in 60 seconds.

Startup: {startup_name}
One-liner: {one_liner}
Problem: {problem_refined}
Solution: {value_prop}
Market estimates: TAM {tam}, SAM {sam}, CAGR {cagr}
Business Model: {revenue_model}
Key Differentiator: {differentiator}
Pricing: {pricing_summary}
Financial Projections:
  - Break-even: {breakeven}
  - 12-month ARR: {arr}
  - LTV:CAC Ratio: {ltv_cac}
Top Risk: {top_risk}

Write a compelling investor memo. Use supplied numbers only, label estimates, and omit unavailable facts.

Output EXACTLY this JSON (Don't mention any other things):

```json
{{
  "executive_summary": "A 400-600 word investor memo in flowing paragraphs. Reference specific numbers from the analysis. Structure: Problem → Solution → Market → Business Model → Traction Plan → Team Need → The Ask.",
  "one_liner": "One sentence that captures the entire startup (under 15 words)",
  "mission_statement": "Why this company exists beyond making money",
  "key_metrics_snapshot": {{
    "market_size": "{tam}",
    "growth_rate": "{cagr}",
    "target_customer": "...",
    "revenue_model": "...",
    "pricing": "{pricing_summary}",
    "break_even": "{breakeven}",
    "ltv_cac": "{ltv_cac}",
    "12mo_arr": "{arr}"
  }},
  "elevator_pitch": "30-second verbal pitch for a founder to deliver at a networking event",
  "investor_email_subject": "Subject line for a cold investor email"
}}
```
"""


class Agent15_ExecutiveSummary(BaseAgent):
    name = "Agent15_ExecutiveSummary"
    layer = 4

    def build_prompt(self, ctx: RunContext, external_research: str = "") -> str:
        idea = ctx.startup_idea
        market = ctx.market_research
        biz = ctx.business_model
        pricing = ctx.pricing_strategy
        fin = ctx.financial_projections
        risk = ctx.risk_register

        revenue_stream = biz.get("revenue_streams", [])
        model = revenue_stream[0].get("model", "Unavailable") if revenue_stream else "Unavailable"
        tiers = pricing.get("tiers", [])
        pricing_summary = " / ".join(f"${t['price_monthly_usd']}/mo ({t['tier_name']})" for t in tiers[:3]
                                     if t.get("tier_name") and t.get("price_monthly_usd") is not None)

        risks = risk.get("risks", [])
        top_risk = risks[0].get("title", "Unavailable") if risks else "Unavailable"

        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            one_liner=idea.get("one_liner", ""),
            problem_refined=ctx.problem_refined[:300],
            value_prop=idea.get("value_proposition", "")[:200],
            revenue_model=model,
            differentiator=idea.get("key_differentiator", "")[:150],
            pricing_summary=pricing_summary or "Unavailable",
            top_risk=top_risk,
            **investor_metrics(market, fin),
        )

    def parse_output(self, raw: str) -> dict:
        return self.extract_json(raw)

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.executive_summary = parsed
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.executive_summary = {
            "executive_summary": "Executive summary generation failed. Please try again.",
            "one_liner": ctx.startup_idea.get("one_liner", ""),
            "key_metrics_snapshot": {},
        }
        return ctx
