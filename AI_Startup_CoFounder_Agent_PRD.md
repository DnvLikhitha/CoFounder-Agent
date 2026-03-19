# AI Startup Co-Founder Agent — PRD & Tech Architecture

> **Version:** 1.0 | **Author:** AI Product Team | **Date:** 2026-03-17
> **Audience:** Indie Developers, Hackathon Teams, Student Builders
> **Stack Constraint:** 100% Free / Open-Source / Free-Tier Only

---

## TABLE OF CONTENTS

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Product Vision & Goals](#3-product-vision--goals)
4. [User Personas](#4-user-personas)
5. [Feature Requirements (PRD)](#5-feature-requirements-prd)
6. [Multi-Agent System Design](#6-multi-agent-system-design)
7. [Agent Orchestration Flow](#7-agent-orchestration-flow)
8. [Tech Stack (Free/OSS Only)](#8-tech-stack-freeoss-only)
9. [System Architecture](#9-system-architecture)
10. [Data Models](#10-data-models)
11. [API Design](#11-api-design)
12. [Frontend Architecture](#12-frontend-architecture)
13. [Infrastructure & Deployment](#13-infrastructure--deployment)
14. [Security & Rate Limiting](#14-security--rate-limiting)
15. [MVP Roadmap](#15-mvp-roadmap)
16. [Success Metrics](#16-success-metrics)
17. [Risk Register](#17-risk-register)
18. [Appendix: Prompt Templates](#18-appendix-prompt-templates)

---

## 1. Executive Summary

**AI Startup Co-Founder Agent** is an agentic AI platform that transforms a one-line problem statement into a complete, investor-ready startup package in under 10 minutes. A pipeline of 16 specialized AI agents collaborates sequentially and in parallel to produce market research, product specs, financial models, tech blueprints, and a downloadable pitch deck.

**Core Value Proposition:**
- From problem → fundable startup plan in one session
- No MBA, no consultant, no $500/hr advisors needed
- Built entirely on free/open-source infrastructure — runs on a student laptop or a free-tier cloud VM

---

## 2. Problem Statement

Early-stage founders and student entrepreneurs face a brutal bootstrapping problem:

| Pain Point | Current Solution | Why It Fails |
|---|---|---|
| No market data | Manual Google research | Takes days, unstructured |
| Can't write a pitch deck | PowerPoint templates | Generic, not tailored |
| No tech architecture knowledge | Hire a CTO | Too expensive |
| No financial model | Excel from scratch | Error-prone, intimidating |
| Don't know competitors | Crunchbase free tier | Surface-level only |
| Can't write an MVP roadmap | Notion templates | Not actionable |

A single AI agent (like plain ChatGPT) gives fragmented, shallow outputs. What's needed is a **team of specialized agents** that think like domain experts, collaborate, and produce coherent, cross-referenced outputs.

---

## 3. Product Vision & Goals

**Vision:** "Be the AI co-founder every solo founder wishes they had on day zero."

### Goals (Ordered by Priority)

**P0 — Must Have (MVP)**
- Accept a problem statement as input
- Run a 16-agent pipeline producing all 10 startup documents
- Display real-time streaming progress to the user
- Generate a downloadable PDF + Markdown report

**P1 — Should Have (v1.1)**
- Allow users to edit/regenerate any individual section
- Save sessions to a user account (Supabase free tier)
- Support follow-up Q&A on the generated plan

**P2 — Nice to Have (v2.0)**
- Investor email generator (based on pitch deck content)
- Export to Google Slides / Notion
- Multi-problem comparison mode

---

## 4. User Personas

### Persona A — "Solo Founder" (Primary)
- **Profile:** Computer science student, 21, building their first startup
- **Goal:** Validate an idea before spending 6 months building it
- **Frustration:** Wastes 2 weeks on market research that's still shallow
- **Key Need:** Fast, structured, credible output to show early investors

### Persona B — "Hackathon Builder"
- **Profile:** 3-person team, 48-hour hackathon
- **Goal:** Win with a complete, polished idea presentation
- **Key Need:** Investor pitch deck + business model in under 30 minutes

### Persona C — "Product Manager at Startup"
- **Profile:** Early PM, validating a new product line idea internally
- **Goal:** Build a business case document for leadership
- **Key Need:** Financial projections + competitor analysis + tech architecture

---

## 5. Feature Requirements (PRD)

### 5.1 Input Module

| ID | Feature | Priority | Notes |
|---|---|---|---|
| INP-01 | Single text input field for problem statement | P0 | Min 10 chars, max 500 chars |
| INP-02 | Optional: industry/domain tag | P1 | Dropdown: SaaS, HealthTech, EdTech, etc. |
| INP-03 | Optional: target geography | P1 | Dropdown or free text |
| INP-04 | Optional: budget range | P2 | Bootstrap / Seed / Series A |
| INP-05 | Input validation + auto-refine suggestion | P1 | Agent 0 refines vague inputs |

### 5.2 Agent Pipeline Module

| ID | Feature | Priority | Notes |
|---|---|---|---|
| AGT-01 | 16-agent sequential + parallel pipeline | P0 | Core product |
| AGT-02 | Real-time streaming output per agent | P0 | SSE or WebSocket |
| AGT-03 | Agent status indicators (pending/running/done/error) | P0 | UI progress tracker |
| AGT-04 | Agent retry on failure (max 3x) | P0 | Error resilience |
| AGT-05 | Context passing between agents | P0 | Shared state object |
| AGT-06 | Parallel execution for independent agents | P1 | Agents 6-10 can run in parallel |
| AGT-07 | Agent output confidence score | P2 | Self-evaluation sub-prompt |

### 5.3 Output Module

| ID | Feature | Priority | Notes |
|---|---|---|---|
| OUT-01 | Render all 10 sections in UI | P0 | Tabbed / accordion layout |
| OUT-02 | Download full report as PDF | P0 | WeasyPrint / ReportLab |
| OUT-03 | Download full report as Markdown | P0 | Raw .md file |
| OUT-04 | Download pitch deck as HTML slides | P1 | Reveal.js template |
| OUT-05 | Copy individual section to clipboard | P1 | Per-section copy button |
| OUT-06 | Regenerate individual section | P1 | Re-run single agent |
| OUT-07 | Share via public URL | P2 | UUID-based public link |

### 5.4 User Account Module (P1)

| ID | Feature | Priority | Notes |
|---|---|---|---|
| USR-01 | Email + password auth | P1 | Supabase Auth |
| USR-02 | Save up to 5 sessions per user | P1 | Free tier limit |
| USR-03 | Session history dashboard | P1 | List view with timestamps |
| USR-04 | Delete session | P1 | GDPR compliance |

---

## 6. Multi-Agent System Design

The system uses **16 specialized agents** organized into 4 layers. Each agent has a defined role, input, output, and prompt strategy.

---

### LAYER 0 — Input Intelligence

#### Agent 0: Problem Refiner
- **Role:** Clarify and enrich the raw user input
- **Input:** Raw problem string
- **Output:** Refined problem statement + domain tags + target user hypothesis
- **Prompt Strategy:** Chain-of-thought, ask "who suffers from this, when, why"
- **Model:** Groq `llama3-8b-8192` (fast, free)
- **Downstream:** All other agents receive Agent 0's output

---

### LAYER 1 — Research & Discovery (Agents 1–4)

#### Agent 1: Startup Idea Generator
- **Role:** Generate 3 startup concepts, then select the best one
- **Input:** Refined problem + domain
- **Output:** Selected startup idea with name, tagline, one-liner, and value proposition
- **Prompt Strategy:** Generate-rank-select pattern (multi-turn in single prompt)
- **Model:** Groq `llama3-70b-8192`
- **Key Output Fields:** `startup_name`, `tagline`, `value_prop`, `target_customer`, `key_differentiator`

#### Agent 2: Market Research Analyst
- **Role:** Estimate market size, growth, and dynamics
- **Input:** Startup idea + domain
- **Output:** TAM/SAM/SOM estimates, market trends, growth rate, key drivers
- **Prompt Strategy:** Role-play as a McKinsey analyst; force structured JSON output
- **Model:** Groq `llama3-70b-8192`
- **Key Output Fields:** `tam_usd`, `sam_usd`, `som_usd`, `cagr_percent`, `market_trends[]`, `target_segments[]`

#### Agent 3: Competitor Intelligence Agent
- **Role:** Identify and analyze 5 real or hypothetical competitors
- **Input:** Startup idea + market data
- **Output:** Competitor table with positioning, pricing, weaknesses, and market gaps
- **Prompt Strategy:** Structured table output; force "gap analysis" section
- **Model:** Groq `mixtral-8x7b-32768`
- **Key Output Fields:** `competitors[]` (name, funding, pricing, strengths, weaknesses), `market_gaps[]`

#### Agent 4: Customer Persona Builder
- **Role:** Define 2 detailed ICP (Ideal Customer Profile) personas
- **Input:** Refined problem + startup idea + market segments
- **Output:** 2 customer persona cards with demographics, psychographics, pain points, buying behavior
- **Prompt Strategy:** Persona card template with structured fields
- **Model:** Groq `llama3-8b-8192`
- **Key Output Fields:** `personas[]` (name, age, job, pains, goals, channels, willingness_to_pay)

---

### LAYER 2 — Product & Business Design (Agents 5–10, parallel-eligible)

#### Agent 5: Product Designer
- **Role:** Define the product — core features, UX flows, and design principles
- **Input:** Startup idea + customer personas
- **Output:** Feature list (MoSCoW), 3 key UX flows, UI component inventory, design system recommendations
- **Prompt Strategy:** Think as a senior product designer at a YC company
- **Model:** Groq `llama3-70b-8192`
- **Key Output Fields:** `must_have_features[]`, `should_have[]`, `ux_flows[]`, `core_screens[]`

#### Agent 6: MVP Roadmap Planner *(parallel-eligible)*
- **Role:** Break MVP into 3 sprints with tasks, owners, and dependencies
- **Input:** Feature list from Agent 5
- **Output:** Sprint plan with epics, user stories, time estimates, and tech dependencies
- **Prompt Strategy:** Agile planning format; output as structured sprint table
- **Model:** Groq `llama3-70b-8192`
- **Key Output Fields:** `sprints[]` (sprint_num, goal, user_stories[], duration_weeks)

#### Agent 7: Business Model Strategist *(parallel-eligible)*
- **Role:** Design the monetization model and go-to-market strategy
- **Input:** Startup idea + competitor pricing + customer personas
- **Output:** Business model canvas (condensed), revenue streams, pricing tiers, GTM strategy
- **Prompt Strategy:** "Fill the Business Model Canvas" structured prompt
- **Model:** Groq `mixtral-8x7b-32768`
- **Key Output Fields:** `revenue_streams[]`, `pricing_tiers[]`, `gtm_channels[]`, `customer_acquisition_strategy`

#### Agent 8: Pricing Strategist *(parallel-eligible)*
- **Role:** Recommend specific pricing with psychological pricing rationale
- **Input:** Competitor pricing + customer personas + business model
- **Output:** 3-tier pricing table (Freemium / Growth / Enterprise) with feature gates and rationale
- **Prompt Strategy:** Value-based pricing framework; compare to 3 competitors
- **Model:** Groq `llama3-8b-8192`
- **Key Output Fields:** `tiers[]` (name, price_monthly, price_annual, features[], target_persona)

#### Agent 9: Financial Projection Analyst *(parallel-eligible)*
- **Role:** Build a 12-month P&L projection with unit economics
- **Input:** Pricing tiers + market size + GTM strategy
- **Output:** Monthly revenue/cost table, break-even analysis, CAC, LTV, LTV:CAC ratio
- **Prompt Strategy:** Force output as a structured data table; include assumptions explicitly
- **Model:** Groq `llama3-70b-8192`
- **Key Output Fields:** `monthly_projections[]`, `breakeven_month`, `cac_usd`, `ltv_usd`, `ltv_cac_ratio`

#### Agent 10: Risk Analyst *(parallel-eligible)*
- **Role:** Identify top 10 startup risks and mitigation strategies
- **Input:** Full context (all above agents)
- **Output:** Risk register with probability, impact, and mitigation per risk
- **Prompt Strategy:** PESTLE + startup-specific risk framework
- **Model:** Groq `llama3-8b-8192`
- **Key Output Fields:** `risks[]` (category, description, probability, impact, mitigation)

---

### LAYER 3 — Technical Design (Agents 11–13)

#### Agent 11: Tech Architecture Designer
- **Role:** Design the full tech stack and system architecture
- **Input:** MVP features + product design + target scale
- **Output:** Tech stack table, system architecture description, component diagram (text-based), database schema, API design overview
- **Prompt Strategy:** "You are a senior architect at a YC-backed startup with a $0 infra budget"
- **Model:** Groq `llama3-70b-8192`
- **Key Output Fields:** `frontend_stack`, `backend_stack`, `database`, `infra`, `third_party_services[]`, `architecture_description`

#### Agent 12: Database Schema Designer
- **Role:** Design database tables, relationships, and indexes
- **Input:** Product features + tech stack
- **Output:** SQL schema with tables, columns, types, constraints, and indexes
- **Prompt Strategy:** Force PostgreSQL-compatible SQL output; include comments
- **Model:** Groq `llama3-70b-8192`
- **Key Output Fields:** `sql_schema` (raw SQL), `entities[]`, `relationships[]`

#### Agent 13: Security & Compliance Advisor
- **Role:** Identify security requirements and compliance checklist
- **Input:** Product design + tech architecture + target market
- **Output:** OWASP Top 10 checklist, data privacy requirements (GDPR/CCPA), auth strategy, compliance roadmap
- **Prompt Strategy:** Security audit mindset
- **Model:** Groq `llama3-8b-8192`
- **Key Output Fields:** `security_checklist[]`, `compliance_requirements[]`, `auth_recommendation`

---

### LAYER 4 — Investor-Ready Output (Agents 14–15)

#### Agent 14: Pitch Deck Writer
- **Role:** Write all 12 slides of an investor pitch deck
- **Input:** All previous agent outputs (full context)
- **Output:** 12 structured slide objects with title, content, speaker notes, and visual suggestion
- **Prompt Strategy:** "You are a pitch deck coach who has reviewed 1000 YC applications"
- **Model:** Groq `llama3-70b-8192`
- **Key Output Fields:** `slides[]` (slide_num, title, content, speaker_notes, visual_suggestion)
- **Slide Order:** Problem → Solution → Market → Product → Business Model → Traction/Roadmap → Competition → Team → Financials → Ask → Vision → Appendix

#### Agent 15: Executive Summary Writer
- **Role:** Synthesize everything into a 1-page executive summary
- **Input:** All previous agent outputs
- **Output:** 600-word executive summary formatted as investor memo
- **Prompt Strategy:** "Write like Paul Graham would read this in 60 seconds"
- **Model:** Groq `llama3-70b-8192`
- **Key Output Fields:** `executive_summary` (markdown text), `one_liner`, `key_metrics_snapshot`

---

### Agent Dependency Graph

```
Agent 0 (Refiner)
    |
    +---> Agent 1 (Idea Generator)
    |         |
    |         +---> Agent 2 (Market Research)
    |         |         |
    |         |         +---> Agent 3 (Competitors)
    |         |
    |         +---> Agent 4 (Personas)
    |                   |
    |         +---------+
    |         |
    |         +---> Agent 5 (Product Design)
    |                   |
    |    +--------------+-------------------------------------+
    |    |              |              |           |          |
    |  Agent 6      Agent 7        Agent 8     Agent 9   Agent 10
    | (Roadmap)  (Biz Model)    (Pricing)  (Financials)  (Risk)
    |    |              |              |           |          |
    |    +--------------+--------------+-----------+----------+
    |                              |
    |                    +---------+
    |                    |         |
    |                 Agent 11  Agent 12   Agent 13
    |             (Architecture) (DB)   (Security)
    |                    |
    |                    +----------------------------------+
    |                                                       |
    |                                              Agent 14 (Pitch Deck)
    |                                                       |
    +---------------------------------------------> Agent 15 (Exec Summary)
```

---

## 7. Agent Orchestration Flow

### Orchestration Strategy

The system uses a **hybrid sequential-parallel orchestration** model:

```
Phase 1 (Sequential): Agents 0 -> 1 -> 2 -> 3 -> 4 -> 5
Phase 2 (Parallel):   Agents 6, 7, 8, 9, 10 run concurrently (asyncio.gather)
Phase 3 (Sequential): Agents 11 -> 12 -> 13
Phase 4 (Parallel):   Agents 14, 15 run concurrently
Phase 5 (Final):      Report assembler collects all outputs -> PDF/MD generation
```

### Context Object (Shared State)

Each agent reads from and writes to a central `RunContext` object:

```python
@dataclass
class RunContext:
    run_id: str
    problem_raw: str
    problem_refined: str           # Agent 0
    startup_idea: dict             # Agent 1
    market_research: dict          # Agent 2
    competitor_analysis: dict      # Agent 3
    customer_personas: list[dict]  # Agent 4
    product_design: dict           # Agent 5
    mvp_roadmap: dict              # Agent 6
    business_model: dict           # Agent 7
    pricing_strategy: dict         # Agent 8
    financial_projections: dict    # Agent 9
    risk_register: dict            # Agent 10
    tech_architecture: dict        # Agent 11
    database_schema: dict          # Agent 12
    security_compliance: dict      # Agent 13
    pitch_deck: dict               # Agent 14
    executive_summary: dict        # Agent 15
    status: dict                   # Per-agent status tracking
    created_at: datetime
    completed_at: datetime | None
```

### Orchestrator Implementation (Python)

```python
# orchestrator.py — Core pipeline runner
import asyncio
from agents import *
from context import RunContext

class StartupOrchestrator:
    def __init__(self, llm_client):
        self.llm = llm_client

    async def run(self, problem: str, run_id: str) -> RunContext:
        ctx = RunContext(run_id=run_id, problem_raw=problem)

        # Phase 1: Sequential foundation
        ctx = await Agent0_Refiner(self.llm).run(ctx)
        ctx = await Agent1_IdeaGenerator(self.llm).run(ctx)
        ctx = await Agent2_MarketResearch(self.llm).run(ctx)
        ctx = await Agent3_Competitors(self.llm).run(ctx)
        ctx = await Agent4_Personas(self.llm).run(ctx)
        ctx = await Agent5_ProductDesigner(self.llm).run(ctx)

        # Phase 2: Parallel business layer
        results = await asyncio.gather(
            Agent6_MVPRoadmap(self.llm).run(ctx),
            Agent7_BusinessModel(self.llm).run(ctx),
            Agent8_Pricing(self.llm).run(ctx),
            Agent9_Financials(self.llm).run(ctx),
            Agent10_RiskAnalyst(self.llm).run(ctx),
        )
        for result in results:
            ctx.merge(result)

        # Phase 3: Sequential technical layer
        ctx = await Agent11_TechArchitecture(self.llm).run(ctx)
        ctx = await Agent12_DatabaseSchema(self.llm).run(ctx)
        ctx = await Agent13_Security(self.llm).run(ctx)

        # Phase 4: Parallel investor output
        results = await asyncio.gather(
            Agent14_PitchDeck(self.llm).run(ctx),
            Agent15_ExecutiveSummary(self.llm).run(ctx),
        )
        for result in results:
            ctx.merge(result)

        ctx.completed_at = datetime.utcnow()
        return ctx
```

### Base Agent Class

```python
# agents/base.py
from abc import ABC, abstractmethod
import json
import re

class BaseAgent(ABC):
    MAX_RETRIES = 3
    name: str = "BaseAgent"

    def __init__(self, llm_client):
        self.llm = llm_client

    @abstractmethod
    def build_prompt(self, ctx: RunContext) -> str:
        pass

    @abstractmethod
    def parse_output(self, raw: str) -> dict:
        pass

    @abstractmethod
    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        pass

    async def run(self, ctx: RunContext) -> RunContext:
        ctx.status[self.name] = "running"
        prompt = self.build_prompt(ctx)

        for attempt in range(self.MAX_RETRIES):
            try:
                raw = await self.llm.complete(prompt)
                parsed = self.parse_output(raw)
                ctx = self.write_to_context(ctx, parsed)
                ctx.status[self.name] = "done"
                return ctx
            except Exception as e:
                if attempt == self.MAX_RETRIES - 1:
                    ctx.status[self.name] = f"error: {str(e)}"
                    ctx = self.write_fallback(ctx)
        return ctx

    def extract_json(self, text: str) -> dict:
        """Extract JSON from LLM output that may contain markdown fences."""
        match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if match:
            return json.loads(match.group(1))
        return json.loads(text)
```

---

## 8. Tech Stack (Free/OSS Only)

### LLM Layer

| Component | Tool | Free Tier | Notes |
|---|---|---|---|
| Primary LLM API | **Groq API** | 14,400 req/day (free) | Llama3-70b, Mixtral, Gemma |
| Fallback LLM | **Ollama** (local) | Unlimited (local) | Run llama3 locally if Groq is down |
| LLM Router | **LiteLLM** | OSS | Unified interface for multiple providers |
| Prompt Templates | **Jinja2** | OSS | Templated prompts with context injection |

### Backend

| Component | Tool | Notes |
|---|---|---|
| Language | **Python 3.11+** | Your background |
| Web Framework | **FastAPI** | Async-native, auto OpenAPI docs |
| Async Runtime | **asyncio** | Built-in Python |
| Task Queue | **Celery + Redis** (free tier) | Background agent jobs |
| Agent Orchestration | **Custom (asyncio.gather)** | No LangChain overhead |
| HTTP Client | **httpx** | Async HTTP for LLM calls |
| Data Validation | **Pydantic v2** | Strict type validation |
| PDF Generation | **WeasyPrint** or **ReportLab** | Both OSS |
| Markdown Processing | **mistune** | Fast Markdown parser |

### Database & Storage

| Component | Tool | Free Tier | Notes |
|---|---|---|---|
| Primary DB | **PostgreSQL** (Supabase) | 500MB free | Hosted free tier |
| ORM | **SQLAlchemy 2.0** | OSS | Async support |
| Migrations | **Alembic** | OSS | Schema versioning |
| Cache / Sessions | **Redis** (Upstash) | 10K req/day free | Session + job state |
| File Storage | **Supabase Storage** | 1GB free | PDFs, exports |

### Frontend

| Component | Tool | Notes |
|---|---|---|
| Framework | **Next.js 14** (App Router) | React + SSR |
| Styling | **Tailwind CSS** | Utility-first |
| UI Components | **shadcn/ui** | OSS, accessible |
| Real-time | **Server-Sent Events (SSE)** | Agent streaming |
| State Management | **Zustand** | Lightweight |
| Charts | **Recharts** | Financial projections display |
| Pitch Deck Export | **Reveal.js** | HTML slides |
| Icons | **Lucide React** | OSS icons |

### DevOps & Infrastructure

| Component | Tool | Free Tier | Notes |
|---|---|---|---|
| Backend Hosting | **Railway** | $5 credit/month | Python/FastAPI deploy |
| Frontend Hosting | **Vercel** | Unlimited hobby | Next.js native |
| CI/CD | **GitHub Actions** | 2000 min/month free | Auto deploy on push |
| Monitoring | **Sentry** | 5K errors/month free | Error tracking |
| Logging | **Loguru** (local) + **Logtail** | 1GB/month free | Structured logs |
| Env Management | **python-dotenv** | OSS | .env file handling |

### Alternative Free LLM Providers (Fallback Chain)

```
Primary:    Groq (Llama3-70b)        -> 14,400 req/day free
Fallback 1: Google AI Studio          -> Gemini 1.5 Flash free tier
Fallback 2: Cerebras Inference        -> Llama3.1-70b free tier
Fallback 3: Ollama (local)            -> Any model, fully free
```

---

## 9. System Architecture

### High-Level Architecture

```
+----------------------------------------------------------------------+
|                          CLIENT LAYER                                |
|  Browser (Next.js 14)                                                |
|  +---------------+   +--------------+   +--------------------------+ |
|  |  Input Form   |   | Progress UI  |   | Output Viewer + Export   | |
|  +-------+-------+   +------+-------+   +--------------------------+ |
|          |                  | SSE Stream                             |
+----------+------------------+----------------------------------------+
           |                  |
           | POST /api/run    | GET /api/run/{id}/stream
           v                  v
+----------------------------------------------------------------------+
|                       API GATEWAY (FastAPI)                          |
|  +-------------+   +--------------+   +---------------------------+  |
|  | /api/run    |   | /api/stream  |   | /api/export  /api/regen   |  |
|  +------+------+   +------+-------+   +---------------------------+  |
+----------+------------------+-----------------------------------------+
           |                  |
           v                  v
+----------------------------------------------------------------------+
|                     ORCHESTRATION LAYER                              |
|  +----------------------------------------------------------------+  |
|  |            StartupOrchestrator (asyncio)                       |  |
|  |  +----------+ +-----------+ +----------+ +------------------+  |  |
|  |  | Phase 1  | |  Phase 2  | | Phase 3  | |    Phase 4       |  |  |
|  |  | Agents   | | Parallel  | |  Tech    | | Investor Output  |  |  |
|  |  |  0-5     | | 6,7,8,9,10| | 11,12,13 | |    14, 15        |  |  |
|  |  +----------+ +-----------+ +----------+ +------------------+  |  |
|  +----------------------------------------------------------------+  |
|              RunContext (shared state dataclass)                      |
+----------------------------------------------------------------------+
           |
           v
+----------------------------------------------------------------------+
|                      LLM ROUTER (LiteLLM)                            |
|   Groq -> Google AI Studio -> Cerebras -> Ollama (fallback chain)    |
+----------------------------------------------------------------------+
           |
           v
+----------------------------------------------------------------------+
|                      PERSISTENCE LAYER                               |
|  +----------------------+  +--------------+  +------------------+   |
|  | PostgreSQL (Supabase)|  | Redis (Cache)|  | Supabase Storage |   |
|  | runs, users, outputs |  | session state|  | (PDFs, exports)  |   |
|  +----------------------+  +--------------+  +------------------+   |
+----------------------------------------------------------------------+
```

### Project Directory Structure

```
ai-cofounder-agent/
|-- backend/
|   |-- main.py                  # FastAPI app entry
|   |-- orchestrator.py          # Pipeline orchestrator
|   |-- context.py               # RunContext dataclass
|   |-- agents/
|   |   |-- __init__.py
|   |   |-- base.py              # BaseAgent ABC
|   |   |-- layer0/
|   |   |   +-- agent0_refiner.py
|   |   |-- layer1/
|   |   |   |-- agent1_idea.py
|   |   |   |-- agent2_market.py
|   |   |   |-- agent3_competitors.py
|   |   |   +-- agent4_personas.py
|   |   |-- layer2/
|   |   |   |-- agent5_product.py
|   |   |   |-- agent6_roadmap.py
|   |   |   |-- agent7_bizmodel.py
|   |   |   |-- agent8_pricing.py
|   |   |   |-- agent9_financials.py
|   |   |   +-- agent10_risk.py
|   |   |-- layer3/
|   |   |   |-- agent11_architecture.py
|   |   |   |-- agent12_database.py
|   |   |   +-- agent13_security.py
|   |   +-- layer4/
|   |       |-- agent14_pitchdeck.py
|   |       +-- agent15_execsummary.py
|   |-- llm/
|   |   |-- client.py            # LiteLLM wrapper
|   |   |-- router.py            # Fallback chain logic
|   |   +-- prompts/             # Jinja2 prompt templates
|   |-- api/
|   |   |-- routes/
|   |   |   |-- run.py           # POST /api/run
|   |   |   |-- stream.py        # GET /api/run/{id}/stream
|   |   |   |-- export.py        # GET /api/run/{id}/export
|   |   |   +-- auth.py          # POST /api/auth/*
|   |   +-- middleware.py        # Rate limiting, CORS
|   |-- db/
|   |   |-- models.py            # SQLAlchemy models
|   |   |-- session.py           # DB session management
|   |   +-- migrations/          # Alembic migrations
|   |-- export/
|   |   |-- pdf_generator.py     # WeasyPrint PDF
|   |   |-- markdown_writer.py   # .md file generator
|   |   +-- pitchdeck_html.py    # Reveal.js deck generator
|   |-- tests/
|   |   |-- test_agents.py
|   |   |-- test_orchestrator.py
|   |   +-- fixtures/
|   |-- requirements.txt
|   |-- .env.example
|   +-- Dockerfile
|
|-- frontend/
|   |-- app/
|   |   |-- page.tsx             # Landing + input form
|   |   |-- run/[id]/page.tsx    # Live pipeline view
|   |   +-- history/page.tsx     # Past sessions
|   |-- components/
|   |   |-- InputForm.tsx
|   |   |-- AgentProgressTracker.tsx
|   |   |-- OutputSection.tsx
|   |   |-- PitchDeckPreview.tsx
|   |   +-- ExportButtons.tsx
|   |-- lib/
|   |   |-- api.ts               # API client
|   |   +-- store.ts             # Zustand store
|   |-- public/
|   +-- package.json
|
|-- docker-compose.yml           # Local dev: postgres + redis
|-- .github/
|   +-- workflows/
|       |-- deploy-backend.yml
|       +-- deploy-frontend.yml
+-- README.md
```

---

## 10. Data Models

### PostgreSQL Schema

```sql
-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Runs table (one row per pipeline execution)
CREATE TABLE runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    problem_raw TEXT NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    -- Status: pending | running | completed | failed
    agent_statuses JSONB DEFAULT '{}',
    -- { "Agent0_Refiner": "done", "Agent1_Idea": "running", ... }
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

-- Outputs table (one row per agent output per run)
CREATE TABLE agent_outputs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES runs(id) ON DELETE CASCADE,
    agent_name VARCHAR(100) NOT NULL,
    agent_layer INTEGER,                    -- 0, 1, 2, 3, 4
    output_data JSONB NOT NULL,             -- Agent's structured output
    raw_llm_response TEXT,                  -- Raw LLM text for debugging
    tokens_used INTEGER,
    latency_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(run_id, agent_name)
);

-- Exports table
CREATE TABLE exports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES runs(id) ON DELETE CASCADE,
    format VARCHAR(20) NOT NULL,            -- pdf | markdown | html_deck
    storage_path TEXT,                      -- Supabase Storage path
    file_size_bytes INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_runs_user_id ON runs(user_id);
CREATE INDEX idx_runs_status ON runs(status);
CREATE INDEX idx_agent_outputs_run_id ON agent_outputs(run_id);
CREATE INDEX idx_runs_created_at ON runs(created_at DESC);
```

### Pydantic Models (Python)

```python
# models/run.py
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional

class RunCreateRequest(BaseModel):
    problem: str = Field(..., min_length=10, max_length=500)
    domain: Optional[str] = None
    geography: Optional[str] = None

class RunStatusResponse(BaseModel):
    run_id: UUID
    status: str
    agent_statuses: dict[str, str]
    progress_percent: int
    created_at: datetime
    completed_at: Optional[datetime]

class AgentOutputResponse(BaseModel):
    agent_name: str
    agent_layer: int
    output_data: dict
    latency_ms: int
```

---

## 11. API Design

### REST Endpoints

```
POST   /api/run                    -> Start new pipeline run
GET    /api/run/{run_id}           -> Get run status + outputs
GET    /api/run/{run_id}/stream    -> SSE stream for live updates
POST   /api/run/{run_id}/regen     -> Regenerate specific agent
GET    /api/run/{run_id}/export    -> Download PDF / Markdown
GET    /api/runs                   -> List user's past runs
DELETE /api/run/{run_id}           -> Delete a run
POST   /api/auth/register          -> Create account
POST   /api/auth/login             -> Get JWT token
POST   /api/auth/refresh           -> Refresh JWT
```

### SSE Stream Format

Each server-sent event follows this schema:

```
event: agent_start
data: {"agent": "Agent2_MarketResearch", "layer": 1, "timestamp": "..."}

event: agent_chunk
data: {"agent": "Agent2_MarketResearch", "chunk": "Analyzing market size..."}

event: agent_done
data: {"agent": "Agent2_MarketResearch", "output": {...}, "latency_ms": 3420}

event: pipeline_complete
data: {"run_id": "...", "total_time_ms": 89000, "export_ready": true}

event: agent_error
data: {"agent": "Agent9_Financials", "error": "JSON parse failed, retrying..."}
```

### FastAPI SSE Implementation

```python
# api/routes/stream.py
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from redis import Redis
import asyncio, json

router = APIRouter()

@router.get("/api/run/{run_id}/stream")
async def stream_run(run_id: str):
    async def event_generator():
        pubsub = Redis().pubsub()
        pubsub.subscribe(f"run:{run_id}:events")
        
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"].decode()
                yield f"data: {data}\n\n"
                
                parsed = json.loads(data)
                if parsed.get("event") == "pipeline_complete":
                    break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
```

---

## 12. Frontend Architecture

### Component Tree

```
app/
|-- page.tsx                     <- Landing + InputForm
|   +-- InputForm
|       |-- ProblemTextarea
|       |-- DomainSelector
|       +-- SubmitButton
|
+-- run/[id]/page.tsx            <- Pipeline View (main screen)
    |-- AgentProgressTracker     <- Left sidebar
    |   +-- AgentStatusCard x15
    |-- OutputViewer             <- Main content area
    |   |-- SectionTab x10      <- Tabbed sections
    |   +-- StreamingMarkdown   <- Live markdown render
    +-- ExportBar                <- Bottom bar
        |-- DownloadPDFButton
        |-- DownloadMDButton
        +-- ShareLinkButton
```

### Zustand Store

```typescript
// lib/store.ts
import { create } from 'zustand'

interface AgentStatus {
  name: string
  status: 'pending' | 'running' | 'done' | 'error'
  latency_ms?: number
}

interface RunStore {
  runId: string | null
  problem: string
  agentStatuses: Record<string, AgentStatus>
  outputs: Record<string, any>
  isStreaming: boolean
  
  setRunId: (id: string) => void
  updateAgentStatus: (agent: string, status: AgentStatus) => void
  setAgentOutput: (agent: string, output: any) => void
  setStreaming: (val: boolean) => void
}

export const useRunStore = create<RunStore>((set) => ({
  runId: null,
  problem: '',
  agentStatuses: {},
  outputs: {},
  isStreaming: false,
  
  setRunId: (id) => set({ runId: id }),
  updateAgentStatus: (agent, status) =>
    set((state) => ({
      agentStatuses: { ...state.agentStatuses, [agent]: status }
    })),
  setAgentOutput: (agent, output) =>
    set((state) => ({
      outputs: { ...state.outputs, [agent]: output }
    })),
  setStreaming: (val) => set({ isStreaming: val }),
}))
```

---

## 13. Infrastructure & Deployment

### Local Development Setup

```bash
# 1. Clone repo
git clone https://github.com/yourname/ai-cofounder-agent
cd ai-cofounder-agent

# 2. Start local services
docker-compose up -d   # PostgreSQL + Redis

# 3. Backend setup
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Add your Groq API key
alembic upgrade head   # Run migrations
uvicorn main:app --reload --port 8000

# 4. Frontend setup
cd ../frontend
npm install
npm run dev            # Runs on localhost:3000
```

### docker-compose.yml (Local Dev)

```yaml
version: "3.9"
services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: cofounder_db
      POSTGRES_USER: dev
      POSTGRES_PASSWORD: devpassword
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres_data:
```

### .env.example

```bash
# LLM APIs
GROQ_API_KEY=gsk_your_key_here
GOOGLE_AI_API_KEY=your_key_here          # Fallback
CEREBRAS_API_KEY=your_key_here           # Fallback 2

# Database
DATABASE_URL=postgresql+asyncpg://dev:devpassword@localhost:5432/cofounder_db

# Redis
REDIS_URL=redis://localhost:6379

# Supabase (for prod)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_anon_key

# Auth
JWT_SECRET=your-256-bit-secret
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

# App
ENVIRONMENT=development
MAX_CONCURRENT_RUNS=5
```

### Production Deployment (Free Tier)

```
Frontend  -> Vercel (free hobby plan)
            Auto-deploys from GitHub main branch
            Environment vars set in Vercel dashboard

Backend   -> Railway (free $5/month credit)
            Dockerfile-based deployment
            Add env vars in Railway dashboard

Database  -> Supabase (free tier: 500MB, 2 projects)
            Enable connection pooling (PgBouncer)
            
Redis     -> Upstash (free: 10K req/day)
            Add REDIS_URL to Railway env vars

Files     -> Supabase Storage (free: 1GB)
            PDFs stored here, served via signed URLs
```

### GitHub Actions CI/CD

```yaml
# .github/workflows/deploy-backend.yml
name: Deploy Backend
on:
  push:
    branches: [main]
    paths: ["backend/**"]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Tests
        run: |
          cd backend
          pip install -r requirements.txt
          pytest tests/ -v
      - name: Deploy to Railway
        uses: railwayapp/railway-deploy@v1
        with:
          railway-token: ${{ secrets.RAILWAY_TOKEN }}
          service: backend
```

---

## 14. Security & Rate Limiting

### Rate Limiting (FastAPI + Redis)

```python
# middleware.py
from fastapi import Request, HTTPException
from redis import Redis
import time

redis = Redis.from_url(settings.REDIS_URL)

async def rate_limit_middleware(request: Request, call_next):
    ip = request.client.host
    key = f"rate_limit:{ip}"
    
    current = redis.get(key)
    if current and int(current) > 10:  # 10 runs/hour per IP
        raise HTTPException(429, "Rate limit exceeded. Try again later.")
    
    redis.incr(key)
    redis.expire(key, 3600)
    
    return await call_next(request)
```

### Security Checklist

- JWT tokens with 24-hour expiry + refresh tokens
- Passwords hashed with bcrypt (cost factor 12)
- All API endpoints require auth except `/api/run` (public, rate-limited)
- SQL injection prevention via SQLAlchemy parameterized queries
- LLM prompt injection mitigation: user input sandboxed in `<user_input>` XML tags
- CORS configured to allow only Vercel domain in production
- Supabase Row Level Security (RLS) enabled on all tables
- All secrets in environment variables, never in code
- HTTPS enforced on all endpoints (handled by Vercel/Railway)

### LLM Prompt Injection Protection

```python
def safe_inject_problem(problem: str) -> str:
    """Wrap user input to prevent prompt injection."""
    # Strip potential injection patterns
    sanitized = problem.replace("Ignore previous", "")
    sanitized = sanitized.replace("System:", "")
    sanitized = sanitized[:500]  # Hard truncation
    
    return f"<user_problem>{sanitized}</user_problem>"
```

---

## 15. MVP Roadmap

### Sprint 0 — Foundation (Week 1)

- [ ] Set up Python/FastAPI project structure
- [ ] Configure Groq API client with LiteLLM wrapper
- [ ] Build BaseAgent class and RunContext dataclass
- [ ] Set up PostgreSQL schema + Alembic migrations
- [ ] Basic Next.js frontend with input form

**Deliverable:** "Hello World" agent that takes input and returns LLM response

---

### Sprint 1 — Core Pipeline (Weeks 2–3)

- [ ] Implement Agents 0–5 (Layer 0 + Layer 1 + Agent 5)
- [ ] Build orchestrator with sequential Phase 1 execution
- [ ] SSE streaming endpoint + frontend progress tracker
- [ ] Basic output viewer (raw JSON -> formatted sections)
- [ ] Implement RunContext persistence to PostgreSQL

**Deliverable:** Working 6-agent pipeline from problem -> product design

---

### Sprint 2 — Full Pipeline (Weeks 4–5)

- [ ] Implement Agents 6–10 (parallel business layer)
- [ ] Implement Agents 11–13 (tech architecture layer)
- [ ] Implement Agents 14–15 (investor output layer)
- [ ] asyncio.gather for parallel phases
- [ ] Error handling + retry logic per agent
- [ ] PDF export with WeasyPrint

**Deliverable:** Complete 16-agent pipeline -> full startup plan -> PDF download

---

### Sprint 3 — Polish & Auth (Weeks 6–7)

- [ ] User auth (Supabase Auth + JWT)
- [ ] Session history dashboard
- [ ] Regenerate individual section feature
- [ ] Pitch deck HTML export (Reveal.js)
- [ ] Mobile-responsive UI polish
- [ ] Rate limiting + security hardening
- [ ] Deploy to Vercel + Railway

**Deliverable:** Production-ready v1.0 — shareable link to users

---

### Sprint 4 — v1.1 Enhancements (Week 8+)

- [ ] Follow-up Q&A agent (chat on top of generated plan)
- [ ] Markdown export
- [ ] Public share URL (UUID-based, no auth required)
- [ ] Groq -> Google AI fallback chain
- [ ] Ollama local mode for dev

---

## 16. Success Metrics

### Technical KPIs

| Metric | Target | Measurement |
|---|---|---|
| Pipeline completion rate | > 90% | `completed / started` runs |
| Avg pipeline time | < 10 minutes | `completed_at - created_at` |
| Agent error rate | < 5% per agent | `error status / total runs` |
| API p95 latency | < 500ms (non-pipeline) | FastAPI middleware timing |
| LLM token efficiency | < 150K tokens/run | `sum(agent_outputs.tokens_used)` |

### Product KPIs

| Metric | Target | Measurement |
|---|---|---|
| Run completion rate | > 70% | Users who download output |
| Return usage | > 30% weekly | Users with 2+ runs in 7 days |
| Export rate | > 50% of completed runs | PDF/MD downloads |
| User-reported quality | > 4/5 stars | In-app rating widget |
| Hackathon wins using tool | 3+ in first month | User submissions |

---

## 17. Risk Register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Groq free tier exhausted during demo | High | High | Implement Google AI + Cerebras fallback chain |
| LLM outputs invalid JSON (parse errors) | Medium | Medium | Retry with stricter prompt; JSON schema enforcement |
| Pipeline takes > 15 min (user abandons) | Medium | High | Run parallel phases; show partial results as agents complete |
| Groq rate limit per model per minute | High | Medium | Queue requests; use multiple models (llama3-8b for fast agents, 70b for complex) |
| Supabase 500MB free tier exceeded | Low | Medium | Compress JSONB; archive old runs after 30 days |
| LLM prompt injection from user input | Medium | Medium | Sanitize + sandbox all user inputs |
| Context window overflow (15 agents x output) | Low | High | Summarize earlier agent outputs before passing to later agents; use mixtral-32k for context-heavy agents |
| Railway free tier $5 credit depleted | Medium | Medium | Monitor spend; fall back to Render.com free tier |

---

## 18. Appendix: Prompt Templates

### Agent 1 — Startup Idea Generator

```
You are a serial entrepreneur and YC partner. Analyze this problem and generate the best startup idea.

Problem: {{ ctx.problem_refined }}
Domain: {{ ctx.domain | default("General") }}

Generate EXACTLY 3 distinct startup ideas for this problem. Then select the best one.

For each idea, provide:
1. Name (2-3 words, memorable)
2. One-liner (under 15 words)
3. Core differentiator vs existing solutions
4. Primary target customer (specific, not broad)

Then output your SELECTED BEST IDEA as JSON:

{
  "startup_name": "...",
  "tagline": "...",
  "one_liner": "...",
  "value_proposition": "...",
  "target_customer": "...",
  "key_differentiator": "...",
  "unfair_advantage": "..."
}

Think step by step. Be specific and concrete, not generic.
```

---

### Agent 9 — Financial Projections

```
You are a CFO at a Series A startup building a financial model for investors.

Startup: {{ ctx.startup_idea.startup_name }}
Pricing Tiers: {{ ctx.pricing_strategy.tiers | tojson }}
Target Market: {{ ctx.market_research.sam_usd }} SAM
GTM Strategy: {{ ctx.business_model.gtm_channels }}

Build a 12-month financial projection. Assume:
- Month 1: 0 customers (pre-launch)
- Month 2-3: Beta (10-50 customers)
- Month 4+: Growth following an S-curve

Output as JSON with this exact structure:

{
  "assumptions": {
    "avg_monthly_churn_percent": ...,
    "cac_usd": ...,
    "avg_revenue_per_user_usd": ...
  },
  "monthly_projections": [
    {
      "month": 1,
      "new_customers": 0,
      "total_customers": 0,
      "mrr_usd": 0,
      "costs_usd": ...,
      "net_profit_usd": ...
    }
  ],
  "breakeven_month": ...,
  "ltv_usd": ...,
  "cac_usd": ...,
  "ltv_cac_ratio": ...,
  "arr_month_12_usd": ...
}

Be realistic. Do not inflate numbers.
```

---

### Agent 14 — Pitch Deck

```
You are a pitch deck coach who has reviewed 1,000+ YC applications.

Create a 12-slide investor pitch deck for:
Startup: {{ ctx.startup_idea.startup_name }}
Problem: {{ ctx.problem_refined }}
Market: ${{ ctx.market_research.tam_usd }}B TAM
Revenue Model: {{ ctx.business_model.revenue_streams }}

Output as JSON array of slide objects:

[
  {
    "slide_number": 1,
    "title": "The Problem",
    "headline": "...",
    "bullet_points": ["...", "...", "..."],
    "key_stat": "...",
    "speaker_notes": "...",
    "visual_suggestion": "..."
  }
]

Slides (in order):
1. Problem, 2. Solution, 3. Market Size, 4. Product Demo,
5. Business Model, 6. Traction / Roadmap, 7. Competition,
8. Team, 9. Financials, 10. The Ask, 11. Vision, 12. Appendix

Make every slide punchy. Investors read slide 1-3 and skip to 10.
Use the market data, financials, and competitor analysis from context.
```

---

*End of Document*

---

**Document Info**
- Total Agents: 16 (Agent 0-15)
- Total Sections: 18
- Target Build Time: 7-8 weeks (solo dev)
- Estimated Infra Cost: $0-$5/month
- Stack: Python (FastAPI) + Next.js + Groq + Supabase + Railway + Vercel
