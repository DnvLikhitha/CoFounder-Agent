"use client";

import type { AgentStatus } from "@/lib/store";
import { Loader2 } from "lucide-react";

interface AgentMeta {
  label: string;
  emoji: string;
  layer: number;
}

interface AgentProgressTrackerProps {
  agentList: string[];
  agentStatuses: Record<string, AgentStatus>;
  metaByAgent: Record<string, AgentMeta>;
}

const statusColor: Record<string, string> = {
  pending: "var(--text-muted)",
  running: "var(--accent)",
  done: "var(--success)",
  error: "#ef4444",
};

export function AgentProgressTracker({
  agentList,
  agentStatuses,
  metaByAgent,
}: AgentProgressTrackerProps) {
  return (
    <aside className="glass-panel w-full h-full flex flex-col p-5 overflow-y-auto border border-white/10 bg-slate-900/60 backdrop-blur-3xl shadow-2xl rounded-2xl relative">
      <div className="absolute top-0 inset-x-0 h-40 bg-gradient-to-b from-cyan-500/10 to-transparent pointer-events-none rounded-t-2xl" />
      <div className="flex items-center justify-between mb-6 px-1 relative z-10">
        <div className="text-xs font-black text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-blue-500 uppercase tracking-widest drop-shadow-sm">
          Agent Pipeline
        </div>
        <div className="text-[10px] font-bold px-3 py-1.5 rounded-full bg-cyan-950/60 text-cyan-300 border border-cyan-500/30 shadow-[0_0_12px_rgba(34,211,238,0.25)]">
          16 agents
        </div>
      </div>
      <div className="space-y-6">
        {Object.entries(
          agentList.reduce((acc, agent) => {
            const layer = metaByAgent[agent]?.layer || 0;
            if (!acc[layer]) acc[layer] = [];
            acc[layer].push(agent);
            return acc;
          }, {} as Record<number, string[]>)
        ).map(([layerStr, agentsInLayer]) => {
          const layerNum = parseInt(layerStr, 10);
          const layerTitles: Record<number, string> = {
            0: "Phase 1: Refinement",
            1: "Phase 2: Ideation & Market",
            2: "Phase 3: Strategy & Product",
            3: "Phase 4: Architecture",
            4: "Phase 5: Pitch & Summary",
          };
          return (
            <div key={layerNum} className="space-y-3 relative z-10">
              <h3 className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest px-2 opacity-90 drop-shadow-[0_0_8px_rgba(34,211,238,0.6)]">
                {layerTitles[layerNum] || `Phase ${layerNum + 1}`}
              </h3>
              <ul className="list-none p-0 m-0 space-y-1.5">
                {agentsInLayer.map((agent) => {
                  const status = agentStatuses[agent] || { name: agent, status: "pending" as const };
                  const meta = metaByAgent[agent] || { label: agent, emoji: "•", layer: 0 };
                  const color = statusColor[status.status] || statusColor.pending;
                  const isRunning = status.status === "running";
                  
                  return (
                    <li
                      key={agent}
                      className={`group relative flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-all duration-300 border ${
                        isRunning 
                          ? "bg-cyan-950/40 border-cyan-400/50 shadow-[0_0_20px_rgba(34,211,238,0.3)] scale-[1.02] z-10" 
                          : "border-transparent text-[var(--text-secondary)] hover:bg-white/5 hover:border-white/10 hover:text-[var(--text-primary)]"
                      }`}
                      style={{ color: status.status === "pending" ? "var(--text-muted)" : (isRunning ? "#fff" : "var(--text-secondary)") }}
                    >
                      <span style={{ color, display: "flex", justifyContent: "center", width: 14 }}>
                        {status.status === "pending" && "○"}
                        {status.status === "running" && <Loader2 size={12} className="animate-spin" />}
                        {status.status === "done" && "✓"}
                        {status.status === "error" && "✗"}
                      </span>
                      <span className={isRunning ? "scale-110 transition-transform" : ""}>{meta.emoji}</span>
                      <div className="flex-1 min-w-0">
                        <div className="font-medium overflow-hidden text-ellipsis whitespace-nowrap">
                          {meta.label}
                        </div>
                        {status.latency_ms != null && status.status === "done" && (
                          <div className="text-[10px] text-[var(--text-muted)] mt-0.5">
                            {status.latency_ms}ms
                          </div>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
