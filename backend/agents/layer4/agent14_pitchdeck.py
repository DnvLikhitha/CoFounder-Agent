"""
Layer 4: Agent 14 — Pitch Deck Writer
Writes all 12 slides of an investor pitch deck.
"""
from backend.agents.base import BaseAgent
from backend.agents.investor_metrics import investor_metrics
from backend.context import RunContext


PROMPT_TEMPLATE = """You are a world-class pitch deck coach who has reviewed 1,000+ YC applications and helped raise $500M+.

Startup: {startup_name}
Tagline: {tagline}
Problem: {problem_refined}
Market estimates: TAM {tam}, SAM {sam}, CAGR {cagr}
Solution: {value_prop}
Business Model: {revenue_model}
Top Competitor: {top_competitor}
Key Advantage: {key_differentiator}
Financial projections: Break-even {breakeven}, month-12 ARR {arr}
Pricing: {pricing_summary}

Write a 12-slide investor pitch deck. Make every slide compelling, specific, and data-driven.
Use only the figures supplied. Label projections and estimates and omit unavailable facts.
Investors read Slides 1-3 and skip to Slide 10 — make those count.

Output EXACTLY this JSON array:

```json
[
  {{
    "slide_number": 1,
    "title": "The Problem",
    "headline": "Punchy one-line headline",
    "bullet_points": ["Specific stat or pain point", "Another data point", "Third compelling point"],
    "key_stat": "1 compelling statistic",
    "speaker_notes": "What to say while showing this slide (2-3 sentences)",
    "visual_suggestion": "What visual/chart to show"
  }}
]
```

Include all 12 slides:
1. Problem  2. Solution  3. Market Size  4. Product  5. Business Model
6. Traction/Roadmap  7. Competition  8. Team  9. Financials  10. The Ask
11. Vision  12. Appendix
"""


class Agent14_PitchDeck(BaseAgent):
    name = "Agent14_PitchDeck"
    layer = 4

    def build_prompt(self, ctx: RunContext, external_research: str = "") -> str:
        idea = ctx.startup_idea
        market = ctx.market_research
        biz = ctx.business_model
        pricing = ctx.pricing_strategy
        comp = ctx.competitor_analysis
        fin = ctx.financial_projections

        revenue_stream = biz.get("revenue_streams", [])
        model = revenue_stream[0].get("model", "Unavailable") if revenue_stream else "Unavailable"
        top_comp = comp["competitors"][0].get("name", "Unavailable") if comp.get("competitors") else "Unavailable"
        tiers = pricing.get("tiers", [])
        pricing_summary = " / ".join(f"{t['tier_name']}: ${t['price_monthly_usd']}/mo" for t in tiers[:3]
                                     if t.get("tier_name") and t.get("price_monthly_usd") is not None)

        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            tagline=idea.get("tagline", ""),
            problem_refined=ctx.problem_refined[:300],
            value_prop=idea.get("value_proposition", "")[:200],
            revenue_model=model,
            top_competitor=top_comp,
            key_differentiator=idea.get("key_differentiator", "")[:150],
            pricing_summary=pricing_summary or "Unavailable",
            **investor_metrics(market, fin),
        )

    def parse_output(self, raw: str) -> dict:
        slides = self.extract_json(raw)
        if isinstance(slides, list):
            return {"slides": slides}
        return slides

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.pitch_deck = parsed
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.pitch_deck = {"slides": []}
        return ctx
