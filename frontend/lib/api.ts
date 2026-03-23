/**
 * lib/api.ts — API client for AI Startup Co-Founder Agent
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function getApiBase(): string {
  return API_BASE;
}

export function createEventSource(runId: string): EventSource {
  return new EventSource(`${API_BASE}/api/run/${runId}/stream`);
}

export function getExportUrl(runId: string, format: "pdf" | "markdown" | "pptx"): string {
  return `${API_BASE}/api/run/${runId}/export/${format}`;
}

export async function startRun(problem: string, domain?: string, geography?: string): Promise<{ run_id: string; status: string }> {
  const res = await fetch(`${API_BASE}/api/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ problem, domain, geography }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to start run");
  }
  return res.json();
}

export async function getRuns(): Promise<{ runs: Array<{ id: string; problem_raw: string; status: string; created_at: string; completed_at: string | null }> }> {
  const res = await fetch(`${API_BASE}/api/runs`);
  if (!res.ok) throw new Error("Failed to fetch runs");
  return res.json();
}
