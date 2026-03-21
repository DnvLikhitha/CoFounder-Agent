"use client";

import type { AgentStatus } from "@/lib/store";

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

const statusIcon: Record<string, string> = {
  pending: "○",
  running: "◐",
  done: "✓",
  error: "✗",
};

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
      <div className="flex items-center justify-between mb-3">
        <div className="text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
        Agent Progress
        </div>
        <div className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-300 border border-indigo-500/25">
          16 agents
        </div>
      </div>
      <ul className="list-none p-0 m-0 space-y-1">
        {agentList.map((agent) => {
          const status = agentStatuses[agent] || { name: agent, status: "pending" as const };
          const meta = metaByAgent[agent] || { label: agent, emoji: "•", layer: 0 };
          const color = statusColor[status.status] || statusColor.pending;
          return (
            <li
              key={agent}
              className="group flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs border border-indigo-500/10 bg-indigo-500/[0.06] hover:bg-indigo-500/[0.12] transition-colors"
              style={{ color: status.status === "pending" ? "var(--text-muted)" : "var(--text-primary)" }}
            >
              <span style={{ color, fontWeight: 600, width: 14, textAlign: "center" }}>
                {statusIcon[status.status]}
              </span>
              <span>{meta.emoji}</span>
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
