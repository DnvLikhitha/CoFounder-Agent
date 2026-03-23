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
    <aside className="glass-panel w-full sm:w-[280px] flex-shrink-0 p-4 overflow-y-auto border border-indigo-500/20">
      <div className="flex items-center justify-between mb-4 px-1">
        <div className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider">
          Agent Progress
        </div>
        <div className="text-[10px] font-medium px-2.5 py-1 rounded-full bg-[var(--accent-dim)] text-[var(--accent)] border border-[var(--accent)]/20">
          16 agents
        </div>
      </div>
      <ul className="list-none p-0 m-0 space-y-1">
        {agentList.map((agent) => {
          const status = agentStatuses[agent] || { name: agent, status: "pending" as const };
          const meta = metaByAgent[agent] || { label: agent, emoji: "•", layer: 0 };
          const color = statusColor[status.status] || statusColor.pending;
          const isRunning = status.status === "running";
          
          return (
            <li
              key={agent}
              className={`group relative flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-all duration-300 border-l-[3px] ${
                isRunning 
                  ? "bg-[var(--accent-dim)] border-[var(--accent)] shadow-[0_0_20px_var(--accent-dim)]" 
                  : "border-transparent hover:bg-white/5 dark:hover:bg-black/20"
              }`}
              style={{ color: status.status === "pending" ? "var(--text-muted)" : "var(--text-primary)" }}
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
                  <div className="text-[10px] text-[var(--text-muted)]">
                    {status.latency_ms}ms
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
