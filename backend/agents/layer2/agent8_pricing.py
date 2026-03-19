"""
Layer 2: Agent 8 — Pricing Strategist (parallel-eligible)
Recommends specific pricing with psychological pricing rationale.
"""
from backend.agents.base import BaseAgent
from backend.context import RunContext


PROMPT_TEMPLATE = """You are a Pricing Strategy expert who uses value-based and behavioral economics frameworks.

Startup: {startup_name}
Business Type: {business_type}
Target Customers: {primary_persona} (primary), {secondary_persona} (secondary)
Competitor Pricing: {competitor_pricing}
Value Delivered: {value_delivered}

Design a 3-tier pricing structure (Freemium / Growth / Enterprise).

Output EXACTLY this JSON:

```json
{{
  "pricing_philosophy": "Value-based|Cost-plus|Competitive|Penetration",
  "pricing_rationale": "Why this pricing makes sense for this market",
  "tiers": [
    {{
      "tier_name": "Free",
      "price_monthly_usd": 0,
      "price_annual_usd": 0,
      "tagline": "Get started, no credit card needed",
      "target_persona": "Students, solo founders",
      "features_included": ["Feature 1", "Feature 2"],
      "features_locked": ["Feature 3", "Feature 4"],
      "usage_limits": "3 runs/month, no exports",
      "conversion_goal": "25% convert to paid within 30 days",
      "psychological_hook": "Show premium features as locked to create desire"
    }},
    {{
      "tier_name": "Pro",
      "price_monthly_usd": 49,
      "price_annual_usd": 470,
      "tagline": "For serious founders",
      "target_persona": "Solo founders, early-stage startups",
      "features_included": ["Everything in Free", "Feature 3", "Feature 4"],
      "features_locked": [],
      "usage_limits": "Unlimited runs, PDF exports",
      "psychological_hook": "Annual = 2 months free"
    }},
    {{
      "tier_name": "Team",
      "price_monthly_usd": 149,
      "price_annual_usd": 1430,
      "tagline": "For teams and agencies",
      "target_persona": "Startups with teams, consulting firms",
      "features_included": ["Everything in Pro", "Team collaboration", "Priority support"],
      "features_locked": [],
      "usage_limits": "5 seats, white-label exports",
      "psychological_hook": "Price anchored against Consulting firm rate ($5000/project)"
    }}
  ],
  "freemium_conversion_strategy": "How to convert free users to paid",
  "annual_discount_percent": 20,
  "enterprise_pricing_note": "Custom pricing via sales call for 20+ seat deals"
}}
```
"""


class Agent8_Pricing(BaseAgent):
    name = "Agent8_Pricing"
    layer = 2

    def build_prompt(self, ctx: RunContext) -> str:
        idea = ctx.startup_idea
        comp = ctx.competitor_analysis
        biz = ctx.business_model
        personas = ctx.customer_personas
        primary = personas[0].get("name", "Primary user") if personas else "Primary user"
        secondary = personas[1].get("name", "Secondary user") if len(personas) > 1 else "Secondary user"
        competitor_prices = [
            f"{c.get('name', '?')}: ${c.get('starting_price_monthly', '?')}/mo"
            for c in comp.get("competitors", [])[:3]
        ]
        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            business_type=idea.get("business_type", "SaaS"),
            primary_persona=primary,
            secondary_persona=secondary,
            competitor_pricing=", ".join(competitor_prices) if competitor_prices else "not known",
            value_delivered=biz.get("value_delivered_to_customer", "significant time and cost savings"),
        )

    def parse_output(self, raw: str) -> dict:
        return self.extract_json(raw)

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.pricing_strategy = parsed
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.pricing_strategy = {"tiers": []}
        return ctx
