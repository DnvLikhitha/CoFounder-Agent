"""
Layer 2: Agent 5 — Product Designer
Defines core features, UX flows, and design principles.
"""
from backend.agents.base import BaseAgent
from backend.context import RunContext


PROMPT_TEMPLATE = """You are a Senior Product Designer who has shipped 10+ SaaS products.

Startup: {startup_name}
Problem: {problem_refined}
Value Proposition: {value_prop}
Primary Persona: {primary_persona}
Secondary Persona: {secondary_persona}

Design the product from scratch. Think like a YC-backed founder with limited resources.

Output EXACTLY this JSON:

```json
{{
  "must_have_features": [
    {{"feature": "Feature name", "description": "What it does", "user_story": "As a [user], I want to [action] so that [benefit]"}},
    {{"feature": "Feature name", "description": "What it does", "user_story": "..."}}
  ],
  "should_have_features": [
    {{"feature": "Feature name", "description": "What it does"}}
  ],
  "nice_to_have_features": [
    {{"feature": "Feature name", "description": "What it does"}}
  ],
  "core_ux_flows": [
    {{
      "flow_name": "Onboarding Flow",
      "steps": ["Step 1: User lands on homepage", "Step 2: Clicks Sign Up", "Step 3: ..."],
      "estimated_completion_time": "3 minutes"
    }},
    {{
      "flow_name": "Core Value Flow",
      "steps": ["Step 1", "Step 2"],
      "estimated_completion_time": "5 minutes"
    }},
    {{
      "flow_name": "Export/Share Flow",
      "steps": ["Step 1"],
      "estimated_completion_time": "1 minute"
    }}
  ],
  "core_screens": ["Screen 1", "Screen 2", "Screen 3", "Screen 4", "Screen 5"],
  "design_principles": ["Principle 1", "Principle 2", "Principle 3"],
  "design_system_recommendation": "Minimal dark/light mode with brand color palette",
  "accessibility_notes": "WCAG 2.1 AA compliance requirements"
}}
```
"""


class Agent5_ProductDesigner(BaseAgent):
    name = "Agent5_ProductDesigner"
    layer = 2

    def build_prompt(self, ctx: RunContext, external_research: str = "") -> str:
        idea = ctx.startup_idea
        personas = ctx.customer_personas
        primary = personas[0].get("name", "Primary user") if personas else "Primary user"
        secondary = personas[1].get("name", "Secondary user") if len(personas) > 1 else "Secondary user"
        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            problem_refined=ctx.problem_refined,
            value_prop=idea.get("value_proposition", ""),
            primary_persona=primary,
            secondary_persona=secondary,
        )

    def parse_output(self, raw: str) -> dict:
        return self.extract_json(raw)

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.product_design = parsed
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.product_design = {"must_have_features": [], "should_have_features": [], "core_ux_flows": []}
        return ctx
