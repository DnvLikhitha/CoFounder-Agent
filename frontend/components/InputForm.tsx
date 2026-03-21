"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles, Loader2 } from "lucide-react";
import { startRun } from "@/lib/api";
import { useRunStore } from "@/lib/store";

const DOMAINS = ["General", "SaaS", "HealthTech", "EdTech", "FinTech", "Marketplace", "AI/ML", "Consumer", "B2B", "Other"];

export function InputForm() {
  const router = useRouter();
  const [problem, setProblem] = useState("");
  const [domain, setDomain] = useState("General");
  const [geography, setGeography] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const reset = useRunStore((s) => s.reset);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    const trimmed = problem.trim();
    if (trimmed.length < 10) {
      setError("Problem statement must be at least 10 characters.");
      return;
    }
    if (trimmed.length > 500) {
      setError("Problem statement must be at most 500 characters.");
      return;
    }
    setLoading(true);
    try {
      reset();
      const { run_id } = await startRun(
        trimmed,
        domain === "General" ? undefined : domain,
        geography || undefined
      );
      useRunStore.getState().setRunId(run_id);
      useRunStore.getState().setProblem(trimmed);
      router.push(`/run/${run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-6 max-w-3xl w-full rounded-2xl border border-[var(--border)] bg-[var(--bg-card)]/75 p-5 sm:p-6 shadow-[0_12px_35px_rgba(79,70,229,0.15)]">
      <div>
        <label htmlFor="problem" className="block text-sm font-semibold text-[var(--text-primary)] mb-2">
          What problem are you solving?
        </label>
        <textarea
          id="problem"
          value={problem}
          onChange={(e) => setProblem(e.target.value)}
          placeholder="e.g. Students waste 10+ hours per week finding study partners for group projects, leading to stress and lower grades."
          rows={4}
          maxLength={500}
          className="input-surface resize-none placeholder:text-[var(--text-muted)]"
          disabled={loading}
        />
        <div className="flex justify-between mt-2 text-xs text-[var(--text-muted)]">
          <span>Min 10 chars, max 500</span>
          <span>{problem.length}/500</span>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label htmlFor="domain" className="block text-sm font-semibold text-[var(--text-primary)] mb-2">
            Industry (optional)
          </label>
          <select
            id="domain"
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            className="input-surface"
            disabled={loading}
          >
            {DOMAINS.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="geography" className="block text-sm font-semibold text-[var(--text-primary)] mb-2">
            Target geography (optional)
          </label>
          <input
            id="geography"
            type="text"
            value={geography}
            onChange={(e) => setGeography(e.target.value)}
            placeholder="e.g. US, Europe, India"
            className="input-surface placeholder:text-[var(--text-muted)]"
            disabled={loading}
          />
        </div>
      </div>

      {error && (
        <div className="px-4 py-3 rounded-xl border border-[var(--danger)]/30 bg-[var(--danger)]/10 text-[var(--danger)] text-sm">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={loading}
        className="flex items-center justify-center gap-2 w-full py-4 px-6 rounded-xl bg-[var(--accent)] hover:bg-[var(--accent-hover)] disabled:opacity-70 text-white font-semibold text-lg transition-colors shadow-lg shadow-indigo-500/20"
      >
        {loading ? (
          <>
            <Loader2 size={22} className="animate-spin" />
            Starting...
          </>
        ) : (
          <>
            <Sparkles size={22} />
            Generate Startup Plan
          </>
        )}
      </button>
    </form>
  );
}
