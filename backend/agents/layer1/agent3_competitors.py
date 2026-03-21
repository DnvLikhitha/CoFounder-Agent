"""
Layer 1: Agent 3 — Competitor Intelligence Agent
Analyzes 5 real or closely analogous competitors and identifies market gaps.
Uses SerpAPI to discover real competitors and their pricing.
"""
from backend.agents.base import BaseAgent
from backend.context import RunContext
from backend.tools.search import search_web


PROMPT_TEMPLATE = """You are a Competitive Intelligence Analyst specializing in startup ecosystems.

Startup: {startup_name}
Problem Being Solved: {problem_refined}
Domain: {domain}
Our Value Proposition: {value_prop}
{external_research_block}

Analyze the competitive landscape. Prefer REAL competitors from the research above when available. Identify 5 real or closely analogous competitors.

Output EXACTLY this JSON:

```json
{{
  "competitors": [
    {{
      "name": "Competitor name",
      "founded_year": 2019,
      "funding_stage": "Series B",
      "estimated_funding_usd_millions": 50,
      "pricing_model": "SaaS subscription",
      "starting_price_monthly": 99,
      "target_customer": "SMBs",
      "strengths": ["Brand recognition", "Strong API"],
      "weaknesses": ["Expensive", "Complex setup", "No mobile app"],
      "market_position": "leader|challenger|niche|follower"
    }}
  ],
  "market_gaps": [
    "Gap 1: What competitors are NOT doing that customers want",
    "Gap 2: Underserved segment or use case",
    "Gap 3: Price-performance gap"
  ],
  "our_competitive_advantages": ["advantage1", "advantage2", "advantage3"],
  "threat_level": "low|medium|high",
  "competitive_moat_recommendation": "What moat should our startup build? (e.g. data network effects, switching costs, brand)"
}}
```
"""


class Agent3_Competitors(BaseAgent):
    name = "Agent3_Competitors"
    layer = 1

    async def fetch_research(self, ctx: RunContext) -> str:
        idea = ctx.startup_idea
        startup = idea.get("startup_name", "startup")
        domain = ctx.domain or "software"
        query = f"{startup} competitors alternatives {domain} pricing"
        return await search_web(query, num_results=8, caller=self.name)

    def build_prompt(self, ctx: RunContext, external_research: str = "") -> str:
        idea = ctx.startup_idea
        block = f"\nExternal Research (real competitors and pricing - use these when possible):\n{external_research}\n" if external_research else ""
        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            problem_refined=ctx.problem_refined,
            domain=ctx.domain or "General",
            value_prop=idea.get("value_proposition", ""),
            external_research_block=block,
        )

    def parse_output(self, raw: str) -> dict:
        return self.extract_json(raw)

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.competitor_analysis = parsed
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.competitor_analysis = {"competitors": [], "market_gaps": [], "our_competitive_advantages": []}
        return ctx
