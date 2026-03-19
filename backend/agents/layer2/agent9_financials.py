"""
Layer 2: Agent 9 — Financial Projection Analyst (parallel-eligible)
Builds 12-month P&L projection with unit economics.
"""
from backend.agents.base import BaseAgent
from backend.context import RunContext


PROMPT_TEMPLATE = """You are a CFO with 15 years of experience building financial models for Series A startups.

Startup: {startup_name}
Pricing Tiers: {pricing_tiers}
SAM: ${sam}B
GTM Strategy: {gtm_channels}

Build a realistic 12-month financial projection. Apply S-curve growth pattern:
- Months 1-2: Pre-launch / beta (0 to beta users)
- Months 3-6: Early traction (initial paying customers)
- Months 7-12: Growth phase (scaling)

Assumptions must be realistic — conservative scenario.

Output EXACTLY this JSON:

```json
{{
  "assumptions": {{
    "avg_monthly_churn_percent": 5,
    "avg_revenue_per_user_usd": 49,
    "cac_usd": 150,
    "monthly_marketing_spend_usd": 2000,
    "team_monthly_cost_usd": 8000,
    "infrastructure_monthly_usd": 500
  }},
  "monthly_projections": [
    {{
      "month": 1,
      "month_name": "Month 1 (Pre-launch)",
      "new_customers": 0,
      "churned_customers": 0,
      "total_customers": 0,
      "mrr_usd": 0,
      "revenue_usd": 0,
      "total_costs_usd": 8500,
      "gross_profit_usd": 0,
      "net_profit_usd": -8500,
      "cumulative_loss_usd": -8500
    }}
  ],
  "breakeven_month": 8,
  "total_12mo_revenue_usd": 185000,
  "total_12mo_costs_usd": 120000,
  "arr_month_12_usd": 54000,
  "ltv_usd": 980,
  "cac_usd": 150,
  "ltv_cac_ratio": 6.5,
  "payback_period_months": 3,
  "key_assumptions_note": "Based on conservative S-curve growth; actual results depend on marketing execution"
}}
```

Include all 12 months in monthly_projections array. Be mathematically consistent.
"""


class Agent9_Financials(BaseAgent):
    name = "Agent9_Financials"
    layer = 2

    def build_prompt(self, ctx: RunContext) -> str:
        idea = ctx.startup_idea
        market = ctx.market_research
        biz = ctx.business_model
        pricing = ctx.pricing_strategy
        tiers = [
            f"{t.get('tier_name', '?')}: ${t.get('price_monthly_usd', 0)}/mo"
            for t in pricing.get("tiers", [])
        ]
        channels = biz.get("customer_acquisition_strategy", {}).get("primary_channel", "direct outreach")
        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            pricing_tiers=", ".join(tiers) if tiers else "Freemium: $0, Pro: $49/mo, Team: $149/mo",
            sam=market.get("sam_usd_billions", 1),
            gtm_channels=str(channels),
        )

    def parse_output(self, raw: str) -> dict:
        return self.extract_json(raw)

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.financial_projections = parsed
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.financial_projections = {"monthly_projections": [], "breakeven_month": 12}
        return ctx
