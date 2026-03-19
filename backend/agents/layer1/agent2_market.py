"""
Layer 1: Agent 2 — Market Research Analyst
Estimates market size, growth, and dynamics like a McKinsey analyst.
"""
from backend.agents.base import BaseAgent
from backend.context import RunContext


PROMPT_TEMPLATE = """You are a Senior Market Research Analyst at McKinsey & Company.

Startup: {startup_name}
Problem: {problem_refined}
Domain: {domain}
Target Customer: {target_customer}

Conduct a comprehensive market sizing analysis.

Use the TAM-SAM-SOM framework:
- TAM (Total Addressable Market): Everyone who has this problem globally
- SAM (Serviceable Addressable Market): The portion you can realistically reach
- SOM (Serviceable Obtainable Market): What you can capture in years 1-3

Output EXACTLY this JSON:

```json
{{
  "tam_usd_billions": 12.5,
  "sam_usd_billions": 2.1,
  "som_usd_millions": 45,
  "cagr_percent": 18.5,
  "market_maturity": "emerging|growing|mature|declining",
  "market_trends": [
    "Trend 1: description",
    "Trend 2: description",
    "Trend 3: description"
  ],
  "target_segments": [
    {{"segment": "Segment name", "size_percent": 40, "pain_level": "high"}},
    {{"segment": "Segment name", "size_percent": 35, "pain_level": "medium"}}
  ],
  "key_market_drivers": ["driver1", "driver2", "driver3"],
  "regulatory_environment": "Brief description of relevant regulations",
  "market_timing": "Why NOW is the right time to enter this market",
  "data_sources_referenced": ["IBISWorld", "Statista", "Gartner", "Industry reports"]
}}
```

Be realistic with numbers. Cite the reasoning in market_timing.
"""


class Agent2_MarketResearch(BaseAgent):
    name = "Agent2_MarketResearch"
    layer = 1

    def build_prompt(self, ctx: RunContext) -> str:
        idea = ctx.startup_idea
        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            problem_refined=ctx.problem_refined,
            domain=ctx.domain or "General",
            target_customer=idea.get("target_customer", ""),
        )

    def parse_output(self, raw: str) -> dict:
        return self.extract_json(raw)

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.market_research = parsed
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.market_research = {
            "tam_usd_billions": 10,
            "sam_usd_billions": 1,
            "som_usd_millions": 20,
            "cagr_percent": 15,
            "market_trends": ["Growing digital adoption"],
            "target_segments": [],
        }
        return ctx
