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
    <aside
      style={{
        width: 220,
        flexShrink: 0,
        borderRight: "1px solid var(--border)",
        padding: "16px 12px",
        overflowY: "auto",
        background: "var(--bg-card)",
      }}
    >
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", marginBottom: 12, textTransform: "uppercase", letterSpacing: 0.5 }}>
        Agent Progress
      </div>
      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {agentList.map((agent) => {
          const status = agentStatuses[agent] || { name: agent, status: "pending" as const };
          const meta = metaByAgent[agent] || { label: agent, emoji: "•", layer: 0 };
          const color = statusColor[status.status] || statusColor.pending;
          return (
            <li
              key={agent}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "6px 8px",
                borderRadius: 6,
                marginBottom: 2,
                fontSize: 12,
                color: status.status === "pending" ? "var(--text-muted)" : "var(--text-primary)",
              }}
            >
              <span style={{ color, fontWeight: 600, width: 14, textAlign: "center" }}>
                {statusIcon[status.status]}
              </span>
              <span>{meta.emoji}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {meta.label}
                </div>
                {status.latency_ms != null && status.status === "done" && (
                  <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
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
