"""
Layer 3: Agent 13 — Security & Compliance Advisor
Identifies security requirements and compliance checklist.
"""
from backend.agents.base import BaseAgent
from backend.context import RunContext


PROMPT_TEMPLATE = """You are a Startup Security Architect who specializes in SaaS compliance for small teams.

Startup: {startup_name}
Business Type: {business_type}
Target Geography: {geography}
Handles User Data: {handles_data}
Auth Method: {auth_method}
Key Features: {features}

Produce a comprehensive security and compliance analysis.

Output EXACTLY this JSON:

```json
{{
  "owasp_top10_checklist": [
    {{"item": "A01 - Broken Access Control", "status": "required", "action": "Implement RBAC with Supabase RLS policies"}},
    {{"item": "A02 - Cryptographic Failures", "status": "required", "action": "HTTPS everywhere, bcrypt for passwords"}},
    {{"item": "A03 - Injection", "status": "required", "action": "Use parameterized queries, never string concatenation"}},
    {{"item": "A04 - Insecure Design", "status": "required", "action": "Threat model before building auth"}},
    {{"item": "A05 - Security Misconfiguration", "status": "required", "action": "Audit all default configs"}},
    {{"item": "A06 - Vulnerable Components", "status": "required", "action": "Dependabot + weekly npm/pip audit"}},
    {{"item": "A07 - Auth Failures", "status": "required", "action": "Rate limit login, force strong passwords"}},
    {{"item": "A08 - Software/Data Integrity", "status": "required", "action": "Verify LLM outputs before storing"}},
    {{"item": "A09 - Logging Failures", "status": "required", "action": "Structured logging all auth events"}},
    {{"item": "A10 - Server-Side Request Forgery", "status": "low-risk", "action": "Validate all user-supplied URLs"}}
  ],
  "compliance_requirements": [
    {{"regulation": "GDPR", "applicable": true, "reason": "EU users", "key_actions": ["Right to deletion", "Data processing consent", "Privacy policy"]}},
    {{"regulation": "CCPA", "applicable": true, "reason": "California users", "key_actions": ["Do Not Sell disclosure"]}},
    {{"regulation": "SOC2", "applicable": false, "reason": "Only needed at enterprise scale"}}
  ],
  "auth_recommendation": {{
    "strategy": "Supabase Auth (JWT + email magic links)",
    "mfa_required": false,
    "session_duration": "24 hours with refresh tokens",
    "password_policy": "Min 8 chars, 1 special, 1 number"
  }},
  "data_privacy_actions": [
    "Privacy Policy page before sign-up",
    "User data deletion endpoint (GDPR Article 17)",
    "Data export endpoint (GDPR Article 20)",
    "Cookie consent banner for EU users"
  ],
  "llm_safety_measures": [
    "Wrap all user inputs in XML tags to prevent injection",
    "Hard limit user input to 500 characters",
    "Strip known injection patterns before sending to LLM",
    "Never include system secrets in LLM context"
  ],
  "security_launch_checklist": [
    "Enable HTTPS everywhere",
    "Set CORS to production domain only",
    "Enable Supabase RLS on all tables",
    "Add rate limiting on all API endpoints",
    "Remove all debug endpoints before launch",
    "Security headers (CSP, X-Frame-Options, etc.)"
  ]
}}
```
"""


class Agent13_Security(BaseAgent):
    name = "Agent13_Security"
    layer = 3

    def build_prompt(self, ctx: RunContext) -> str:
        idea = ctx.startup_idea
        product = ctx.product_design
        features = [f.get("feature", "") for f in product.get("must_have_features", [])[:4]]
        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            business_type=idea.get("business_type", "SaaS"),
            geography=ctx.geography or "Global",
            handles_data="Yes — user accounts, generated outputs",
            auth_method="Email + Password with JWT tokens",
            features=", ".join(features) if features else "user auth, data storage, API access",
        )

    def parse_output(self, raw: str) -> dict:
        return self.extract_json(raw)

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.security_compliance = parsed
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.security_compliance = {"owasp_top10_checklist": [], "compliance_requirements": []}
        return ctx
