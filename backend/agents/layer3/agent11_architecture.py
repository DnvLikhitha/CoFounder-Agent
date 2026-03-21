"""
Layer 3: Agent 11 — Tech Architecture Designer
Designs the full tech stack and system architecture.
"""
from backend.agents.base import BaseAgent
from backend.context import RunContext


PROMPT_TEMPLATE = """You are a Senior Software Architect at a YC-backed startup with a $0 infrastructure budget.
You specialize in free/open-source tools and free cloud tiers.

Startup: {startup_name}
Core Features: {core_features}
Business Type: {business_type}
Scale Target: {scale_target} users in year 1
Domain: {domain}

Design the complete technical architecture using ONLY free or open-source tools.

Output EXACTLY this JSON:

```json
{{
  "frontend_stack": {{
    "framework": "Next.js 14",
    "styling": "Tailwind CSS + shadcn/ui",
    "state_management": "Zustand",
    "hosting": "Vercel (free tier)",
    "deployment_url": "https://app.startup.vercel.app"
  }},
  "backend_stack": {{
    "language": "Python 3.11",
    "framework": "FastAPI",
    "async_runtime": "asyncio",
    "hosting": "Railway (free $5/mo credit)",
    "key_libraries": ["pydantic", "sqlalchemy", "httpx", "loguru"]
  }},
  "database": {{
    "primary": "PostgreSQL via Supabase (free 500MB)",
    "cache": "Redis via Upstash (free 10K req/day)",
    "file_storage": "Supabase Storage (free 1GB)",
    "orm": "SQLAlchemy 2.0 async"
  }},
  "ai_layer": {{
    "primary_llm": "Groq API (free tier: 14,400 req/day)",
    "models_used": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    "fallback_llm": "Google AI Studio (Gemini Flash free tier)"
  }},
  "infrastructure": {{
    "ci_cd": "GitHub Actions (free 2000 min/month)",
    "monitoring": "Sentry free tier",
    "logging": "Loguru + Logtail free tier"
  }},
  "architecture_pattern": "Monolithic API with async worker pattern",
  "architecture_description": "Multi-paragraph description of the system architecture",
  "component_interactions": [
    "Frontend → FastAPI via REST + SSE streaming",
    "FastAPI → Orchestrator → 16 AI Agents (asyncio)",
    "Agents → Groq LLM API",
    "FastAPI → Supabase PostgreSQL for persistence"
  ],
  "scalability_notes": "How this scales when growth happens",
  "estimated_monthly_infra_cost_usd": 0
}}
```
"""


class Agent11_TechArchitecture(BaseAgent):
    name = "Agent11_TechArchitecture"
    layer = 3

    def build_prompt(self, ctx: RunContext, external_research: str = "") -> str:
        idea = ctx.startup_idea
        product = ctx.product_design
        market = ctx.market_research
        features = [f.get("feature", "") for f in product.get("must_have_features", [])[:4]]
        som = market.get("som_usd_millions", 20)
        scale = int(som * 10)  # rough user estimate
        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            core_features=", ".join(features) if features else "core product features",
            business_type=idea.get("business_type", "SaaS"),
            scale_target=f"{scale:,}",
            domain=ctx.domain or "Technology",
        )

    def parse_output(self, raw: str) -> dict:
        return self.extract_json(raw)

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.tech_architecture = parsed
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.tech_architecture = {
            "frontend_stack": {"framework": "Next.js", "hosting": "Vercel"},
            "backend_stack": {"framework": "FastAPI", "hosting": "Railway"},
        }
        return ctx
