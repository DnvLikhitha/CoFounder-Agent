"use client";
/**
 * app/run/[id]/page.tsx — Live pipeline view with real-time SSE updates
 */

import { useEffect, useState, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { useRunStore, AGENT_LIST } from "@/lib/store";
import { createEventSource, getExportUrl } from "@/lib/api";
import { Download, Sparkles, ArrowLeft, History } from "lucide-react";
import { AgentProgressTracker } from "@/components/AgentProgressTracker";
import { OutputSection } from "@/components/OutputSection";

// ── Agent metadata ────────────────────────────────────────────
const AGENT_META: Record<string, { label: string; emoji: string; layer: number }> = {
  Agent0_Refiner:          { label: "Problem Refiner",      emoji: "🔎", layer: 0 },
  Agent1_IdeaGenerator:    { label: "Idea Generator",       emoji: "💡", layer: 1 },
  Agent2_MarketResearch:   { label: "Market Research",      emoji: "📊", layer: 1 },
  Agent3_Competitors:      { label: "Competitor Analysis",  emoji: "🥊", layer: 1 },
  Agent4_Personas:         { label: "Customer Personas",    emoji: "👤", layer: 1 },
  Agent5_ProductDesigner:  { label: "Product Design",       emoji: "🎨", layer: 2 },
  Agent6_MVPRoadmap:       { label: "MVP Roadmap",          emoji: "🗺️", layer: 2 },
  Agent7_BusinessModel:    { label: "Business Model",       emoji: "💼", layer: 2 },
  Agent8_Pricing:          { label: "Pricing Strategy",     emoji: "💰", layer: 2 },
  Agent9_Financials:       { label: "Financial Model",      emoji: "📈", layer: 2 },
  Agent10_RiskAnalyst:     { label: "Risk Analysis",        emoji: "⚠️", layer: 2 },
  Agent11_TechArchitecture:{ label: "Tech Architecture",    emoji: "🏗️", layer: 3 },
  Agent12_DatabaseSchema:  { label: "Database Schema",      emoji: "🗄️", layer: 3 },
  Agent13_Security:        { label: "Security & Compliance",emoji: "🔒", layer: 3 },
  Agent14_PitchDeck:       { label: "Pitch Deck",           emoji: "🎯", layer: 4 },
  Agent15_ExecutiveSummary:{ label: "Executive Summary",    emoji: "📋", layer: 4 },
};

// ── Tab order for output viewer ───────────────────────────────
const OUTPUT_TABS = [
  { key: "executive_summary", label: "Summary", emoji: "📋" },
  { key: "startup_idea",       label: "Idea",    emoji: "💡" },
  { key: "market_research",    label: "Market",  emoji: "📊" },
  { key: "competitor_analysis",label: "Compete", emoji: "🥊" },
  { key: "customer_personas",  label: "Personas",emoji: "👤" },
  { key: "product_design",     label: "Product", emoji: "🎨" },
  { key: "mvp_roadmap",        label: "Roadmap", emoji: "🗺️" },
  { key: "business_model",     label: "Business",emoji: "💼" },
  { key: "pricing_strategy",   label: "Pricing", emoji: "💰" },
  { key: "financial_projections",label:"Finance",emoji: "📈" },
  { key: "risk_register",      label: "Risks",   emoji: "⚠️" },
  { key: "tech_architecture",  label: "Tech",    emoji: "🏗️" },
  { key: "pitch_deck",         label: "Deck",    emoji: "🎯" },
];

// ── Render a JSON output as readable Markdown ─────────────────
function renderOutput(key: string, data: any): string {
  if (!data) return "_Not yet generated..._";

  if (key === "executive_summary") {
    return `## Executive Summary\n\n${data.executive_summary || ""}\n\n**Mission:** ${data.mission_statement || ""}\n\n**Elevator Pitch:** ${data.elevator_pitch || ""}\n\n**Investor Email Subject:** _${data.investor_email_subject || ""}_`;
  }

  if (key === "startup_idea") {
    return `## ${data.startup_name || "Startup"}\n\n**Tagline:** ${data.tagline || ""}\n\n**One-liner:** ${data.one_liner || ""}\n\n**Value Proposition:** ${data.value_proposition || ""}\n\n**Target Customer:** ${data.target_customer || ""}\n\n**Key Differentiator:** ${data.key_differentiator || ""}\n\n**Unfair Advantage:** ${data.unfair_advantage || ""}`;
  }

  if (key === "market_research") {
    const trends = (data.market_trends || []).map((t: string) => `- ${t}`).join("\n");
    return `## Market Analysis\n\n| Metric | Value |\n|--------|-------|\n| TAM | $${data.tam_usd_billions}B |\n| SAM | $${data.sam_usd_billions}B |\n| SOM | $${data.som_usd_millions}M |\n| CAGR | ${data.cagr_percent}% |\n\n### Market Trends\n${trends}\n\n**Why Now:** ${data.market_timing || ""}`;
  }

  if (key === "competitor_analysis") {
    const comps = (data.competitors || []).map((c: any) =>
      `### ${c.name} (${c.funding_stage || "?"})\n- Price: $${c.starting_price_monthly}/mo\n- Weaknesses: ${(c.weaknesses || []).join(", ")}`
    ).join("\n\n");
    const gaps = (data.market_gaps || []).map((g: string) => `- ${g}`).join("\n");
    return `## Competitive Landscape\n\n${comps}\n\n### Our Market Gaps\n${gaps}`;
  }

  if (key === "customer_personas") {
    return (Array.isArray(data) ? data : []).map((p: any) =>
      `### ${p.name || "Persona"} — ${p.job_title || ""}\n\n_"${p.quote || ""}"_\n\n**Pains:** ${(p.pain_points || []).join(" · ")}\n\n**Goals:** ${(p.goals || []).join(" · ")}\n\n**Willing to Pay:** $${p.willingness_to_pay_monthly_usd}/mo`
    ).join("\n\n---\n\n");
  }

  if (key === "product_design") {
    const must = (data.must_have_features || []).map((f: any) => `- **${f.feature}**: ${f.description}`).join("\n");
    const should = (data.should_have_features || []).map((f: any) => `- ${f.feature}`).join("\n");
    return `## Product Design\n\n### Must-Have Features (P0)\n${must}\n\n### Should-Have Features (P1)\n${should}`;
  }

  if (key === "mvp_roadmap") {
    return (data.sprints || []).map((s: any) =>
      `## Sprint ${s.sprint_number} — ${s.theme}\n\n**Goal:** ${s.sprint_goal}\n\n**Deliverable:** ${s.deliverable}\n\n**Stories:** ${(s.user_stories || []).map((u: any) => u.title).join(", ")}`
    ).join("\n\n---\n\n");
  }

  if (key === "business_model") {
    const streams = (data.revenue_streams || []).map((r: any) => `- **${r.stream}** (${r.model}): ${r.description}`).join("\n");
    const gtm = (data.gtm_phases || []).map((g: any) => `- **${g.phase}**: ${g.strategy} → *${g.target}*`).join("\n");
    return `## Business Model\n\n### Revenue Streams\n${streams}\n\n### Go-To-Market\n${gtm}`;
  }

  if (key === "pricing_strategy") {
    const tiers = (data.tiers || []).map((t: any) =>
      `### ${t.tier_name} — $${t.price_monthly_usd}/mo\n_${t.tagline}_\n\n**Target:** ${t.target_persona}\n\n**Limits:** ${t.usage_limits}`
    ).join("\n\n---\n\n");
    return `## Pricing Strategy\n\n${tiers}`;
  }

  if (key === "financial_projections") {
    const highlights = `| Metric | Value |\n|--------|-------|\n| Break-even | Month ${data.breakeven_month} |\n| 12-mo ARR | $${data.arr_month_12_usd?.toLocaleString()} |\n| LTV | $${data.ltv_usd?.toLocaleString()} |\n| CAC | $${data.cac_usd?.toLocaleString()} |\n| LTV:CAC | ${data.ltv_cac_ratio}x |`;
    const table = [
      "| Month | Customers | MRR | Net Profit |",
      "|-------|-----------|-----|------------|",
      ...(data.monthly_projections || []).slice(0, 12).map((m: any) =>
        `| ${m.month} | ${m.total_customers?.toLocaleString()} | $${m.mrr_usd?.toLocaleString()} | $${m.net_profit_usd?.toLocaleString()} |`
      )
    ].join("\n");
    return `## Financial Projections\n\n${highlights}\n\n### Monthly Breakdown\n${table}`;
  }

  if (key === "risk_register") {
    return "## Risk Register\n\n" + (data.risks || []).map((r: any) =>
      `### ${r.risk_id} — ${r.title}\n**Category:** ${r.category} | **Probability:** ${r.probability} | **Impact:** ${r.impact}\n\n${r.description}\n\n**Mitigation:** ${r.mitigation_strategy}`
    ).join("\n\n---\n\n");
  }

  if (key === "tech_architecture") {
    const fe = data.frontend_stack || {};
    const be = data.backend_stack || {};
    const db = data.database || {};
    return `## Tech Architecture\n\n### Frontend\n- ${fe.framework} + ${fe.styling}\n- Hosting: ${fe.hosting}\n\n### Backend\n- ${be.framework} (${be.language})\n- Hosting: ${be.hosting}\n\n### Database\n- ${db.primary}\n- Cache: ${db.cache}\n\n### AI Layer\n- ${data.ai_layer?.primary_llm}\n\n${data.architecture_description || ""}`;
  }

  if (key === "pitch_deck") {
    return (data.slides || []).map((s: any) =>
      `## Slide ${s.slide_number}: ${s.title}\n\n**${s.headline || ""}**\n\n${(s.bullet_points || []).map((b: string) => `- ${b}`).join("\n")}\n\n${s.key_stat ? `📊 **${s.key_stat}**` : ""}\n\n_Speaker Notes: ${s.speaker_notes || ""}_`
    ).join("\n\n---\n\n");
  }

  return `\`\`\`json\n${JSON.stringify(data, null, 2)}\n\`\`\``;
}

export default function RunPage() {
  const params = useParams();
  const router = useRouter();
  const runId = params.id as string;
  const {
    agentStatuses, outputs, isPipelineRunning, isComplete, progressPercent, elapsedSeconds,
    updateAgent, setOutput, setPipelineRunning, setComplete, setElapsedSeconds,
  } = useRunStore();

  const [activeTab, setActiveTab] = useState("executive_summary");
  const [startupName, setStartupName] = useState("Generating...");
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Start timer
  useEffect(() => {
    timerRef.current = setInterval(() => {
      setElapsedSeconds(prev => prev + 1);
    }, 1000);
    return () => clearInterval(timerRef.current);
  }, []);

  // Connect SSE
  useEffect(() => {
    if (!runId) return;
    setPipelineRunning(true);

    const es = createEventSource(runId);
    eventSourceRef.current = es;

    es.addEventListener("agent_start", (e: MessageEvent) => {
      const data = JSON.parse(e.data);
      updateAgent(data.agent, { name: data.agent, status: "running", layer: data.layer });
    });

    es.addEventListener("agent_done", (e: MessageEvent) => {
      const data = JSON.parse(e.data);
      updateAgent(data.agent, { name: data.agent, status: "done", layer: data.layer, latency_ms: data.latency_ms });
      if (data.output) {
        setOutput(data.agent, data.output);
        // Map agent output to the correct context key
        const keyMap: Record<string, string> = {
          Agent0_Refiner: "problem_refined",
          Agent1_IdeaGenerator: "startup_idea",
          Agent2_MarketResearch: "market_research",
          Agent3_Competitors: "competitor_analysis",
          Agent4_Personas: "customer_personas",
          Agent5_ProductDesigner: "product_design",
          Agent6_MVPRoadmap: "mvp_roadmap",
          Agent7_BusinessModel: "business_model",
          Agent8_Pricing: "pricing_strategy",
          Agent9_Financials: "financial_projections",
          Agent10_RiskAnalyst: "risk_register",
          Agent11_TechArchitecture: "tech_architecture",
          Agent12_DatabaseSchema: "database_schema",
          Agent13_Security: "security_compliance",
          Agent14_PitchDeck: "pitch_deck",
          Agent15_ExecutiveSummary: "executive_summary",
        };
        const outputKey = keyMap[data.agent];
        if (outputKey) setOutput(outputKey, data.output);

        // Update startup name when available
        if (data.agent === "Agent1_IdeaGenerator" && data.output?.startup_name) {
          setStartupName(data.output.startup_name);
        }
      }
    });

    es.addEventListener("agent_error", (e: MessageEvent) => {
      const data = JSON.parse(e.data);
      updateAgent(data.agent, { name: data.agent, status: "error" });
    });

    es.addEventListener("pipeline_complete", () => {
      setPipelineRunning(false);
      setComplete(true);
      clearInterval(timerRef.current);
      es.close();
    });

    es.addEventListener("pipeline_error", () => {
      setPipelineRunning(false);
      clearInterval(timerRef.current);
      es.close();
    });

    es.onerror = () => {
      setTimeout(() => {
        if (!isComplete) {
          // Try fetching the result directly
          fetch(`http://localhost:8000/api/run/${runId}/result`)
            .then(r => r.json())
            .then(data => {
              // Populate outputs from fetched result
              Object.entries(data).forEach(([k, v]) => {
                if (v && typeof v === "object") setOutput(k, v);
              });
              setComplete(true);
              setPipelineRunning(false);
            })
            .catch(() => {});
        }
      }, 2000);
    };

    return () => { es.close(); };
  }, [runId]);

  const formatTime = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  const doneCount = Object.values(agentStatuses).filter(a => a.status === "done").length;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "var(--bg-primary)" }}>
      {/* ── Top Bar ─────────────────────────────────────────────── */}
      <header style={{ borderBottom: "1px solid var(--border)", padding: "12px 20px", display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button onClick={() => router.push("/")} className="btn-secondary" style={{ padding: "6px 12px", display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
            <ArrowLeft size={14} /> Home
          </button>
          <button onClick={() => router.push("/history")} className="btn-secondary" style={{ padding: "6px 12px", display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
            <History size={14} /> History
          </button>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Sparkles size={16} style={{ color: "var(--accent)" }} />
            <span style={{ fontWeight: 700 }}>{startupName}</span>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {/* Progress */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 120, background: "var(--bg-card)", height: 6, borderRadius: 3 }}>
              <div style={{ width: `${progressPercent}%`, height: "100%", background: "linear-gradient(90deg, var(--accent), #a78bfa)", borderRadius: 3, transition: "width 0.5s" }} />
            </div>
            <span style={{ fontSize: 13, color: "var(--text-secondary)", minWidth: 60 }}>
              {doneCount}/16 agents
            </span>
          </div>
          <span style={{ fontSize: 13, color: "var(--text-muted)" }}>⏱ {formatTime(elapsedSeconds)}</span>

          {/* Status badge */}
          {isComplete ? (
            <span style={{ background: "rgba(34,197,94,0.15)", color: "var(--success)", padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: 600 }}>
              ✅ Complete
            </span>
          ) : (
            <span style={{ background: "var(--accent-dim)", color: "var(--accent-hover)", padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: 600 }}>
              ⚡ Running
            </span>
          )}

          {/* Export */}
          {isComplete && (
            <div style={{ display: "flex", gap: 8 }}>
              <a href={getExportUrl(runId, "pdf")} target="_blank" className="btn-secondary" style={{ padding: "6px 14px", display: "flex", alignItems: "center", gap: 6, fontSize: 13, textDecoration: "none" }}>
                <Download size={14} /> PDF
              </a>
              <a href={getExportUrl(runId, "markdown")} target="_blank" className="btn-secondary" style={{ padding: "6px 14px", display: "flex", alignItems: "center", gap: 6, fontSize: 13, textDecoration: "none" }}>
                <Download size={14} /> MD
              </a>
            </div>
          )}
        </div>
      </header>

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* ── Sidebar: Agent Progress ─────────────────────────── */}
        <AgentProgressTracker agentList={AGENT_LIST} agentStatuses={agentStatuses} metaByAgent={AGENT_META} />

        {/* ── Main: Output Viewer ────────────────────────────── */}
        <OutputSection
          tabs={OUTPUT_TABS}
          activeTab={activeTab}
          onActiveTabChange={setActiveTab}
          outputs={outputs}
          isComplete={isComplete}
          renderOutput={renderOutput}
        />
      </div>
    </div>
  );
}
