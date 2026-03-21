"""
Layer 3: Agent 12 — Database Schema Designer
Designs database tables, relationships, and indexes.
"""
from backend.agents.base import BaseAgent
from backend.context import RunContext


PROMPT_TEMPLATE = """You are a Database Architect specializing in PostgreSQL for SaaS applications.

Startup: {startup_name}
Core Features: {core_features}
User Personas Data Needs: Primary user: {primary_persona}, Secondary: {secondary_persona}
Business Model: {business_model}

Design the complete PostgreSQL database schema for this product's MVP.
Use best practices: UUID primary keys, proper constraints, appropriate indexes.

Output EXACTLY this JSON:

```json
{{
  "entities": [
    {{"entity": "users", "purpose": "User accounts and authentication"}},
    {{"entity": "entity_name", "purpose": "What it stores"}}
  ],
  "sql_schema": "-- Complete PostgreSQL SQL DDL here\\nCREATE TABLE users (\\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\\n  email VARCHAR(255) UNIQUE NOT NULL,\\n  created_at TIMESTAMPTZ DEFAULT NOW()\\n);\\n\\n -- Add all other tables...",
  "relationships": [
    {{"from": "orders", "to": "users", "type": "many-to-one", "on": "user_id"}},
    {{"from": "entity1", "to": "entity2", "type": "one-to-many|many-to-many|one-to-one", "on": "foreign_key"}}
  ],
  "indexes_created": [
    "CREATE INDEX idx_table_column ON table(column);",
    "CREATE INDEX idx_table2_col ON table2(col);"
  ],
  "rls_policies_notes": "Which tables need Row Level Security and key policy descriptions",
  "estimated_row_counts_year1": {{
    "users": 5000,
    "entity2": 50000
  }},
  "backup_strategy": "Supabase automatic daily backups on free tier"
}}
```
"""


class Agent12_DatabaseSchema(BaseAgent):
    name = "Agent12_DatabaseSchema"
    layer = 3

    def build_prompt(self, ctx: RunContext, external_research: str = "") -> str:
        idea = ctx.startup_idea
        product = ctx.product_design
        biz = ctx.business_model
        personas = ctx.customer_personas
        features = [f.get("feature", "") for f in product.get("must_have_features", [])[:5]]
        primary = personas[0].get("name", "Primary user") if personas else "Primary user"
        secondary = personas[1].get("name", "Secondary user") if len(personas) > 1 else "Secondary user"
        revenue_streams = [s.get("stream", "") for s in biz.get("revenue_streams", [])]
        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            core_features=", ".join(features) if features else "core CRUD operations",
            primary_persona=primary,
            secondary_persona=secondary,
            business_model=", ".join(revenue_streams) if revenue_streams else "SaaS subscription",
        )

    def parse_output(self, raw: str) -> dict:
        return self.extract_json(raw)

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.database_schema = parsed
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.database_schema = {"entities": [], "sql_schema": "-- Could not generate schema", "relationships": []}
        return ctx
