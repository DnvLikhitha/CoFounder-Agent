"""
Layer 4: Agent 14 — Pitch Deck Writer
Writes all 12 slides of an investor pitch deck.
"""
from backend.agents.base import BaseAgent
from backend.context import RunContext
import json


PROMPT_TEMPLATE = """You are a world-class pitch deck coach who has reviewed 1,000+ YC applications and helped raise $500M+.

Startup: {startup_name}
Tagline: {tagline}
Problem: {problem_refined}
Market: ${tam}B TAM, ${sam}B SAM growing at {cagr}% CAGR
Solution: {value_prop}
Business Model: {revenue_model}
Top Competitor: {top_competitor}
Key Advantage: {key_differentiator}
Financial Highlight: Break-even at Month {breakeven}, {arr}K ARR by Month 12
Pricing: {pricing_summary}

Write a 12-slide investor pitch deck. Make every slide compelling, specific, and data-driven.
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

        revenue_stream = biz.get("revenue_streams", [{}])
        model = revenue_stream[0].get("model", "SaaS subscription") if revenue_stream else "SaaS"
        top_comp = comp.get("competitors", [{}])[0].get("name", "Legacy solutions") if comp.get("competitors") else "Legacy solutions"
        tiers = pricing.get("tiers", [])
        pricing_summary = " / ".join([f"{t.get('tier_name','?')}: ${t.get('price_monthly_usd',0)}/mo" for t in tiers[:3]])

        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            tagline=idea.get("tagline", ""),
            problem_refined=ctx.problem_refined[:300],
            tam=market.get("tam_usd_billions", 10),
            sam=market.get("sam_usd_billions", 1),
            cagr=market.get("cagr_percent", 15),
            value_prop=idea.get("value_proposition", "")[:200],
            revenue_model=model,
            top_competitor=top_comp,
            key_differentiator=idea.get("key_differentiator", "")[:150],
            breakeven=fin.get("breakeven_month", 8),
            arr=int(fin.get("arr_month_12_usd", 50000) / 1000),
            pricing_summary=pricing_summary or "Freemium + Pro $49/mo + Team $149/mo",
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
