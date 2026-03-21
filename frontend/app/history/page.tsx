"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Sparkles, Loader2, AlertCircle } from "lucide-react";
import { getRuns } from "@/lib/api";

interface Run {
  id: string;
  problem_raw: string;
  status: string;
  created_at: string;
  completed_at: string | null;
}

export default function HistoryPage() {
  const router = useRouter();
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getRuns()
      .then((data) => setRuns(data.runs || []))
      .catch(() => setError("Failed to load runs. Is the backend running?"))
      .finally(() => setLoading(false));
  }, []);

  const formatDate = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  const statusBadge = (status: string) => {
    const styles: Record<string, string> = {
      completed: "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400",
      running: "bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-400",
      failed: "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400",
      pending: "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400",
    };
    return (
      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${styles[status] || styles.pending}`}>
        {status}
      </span>
    );
  };

  return (
    <div className="app-shell">
      <header className="border-b border-[var(--border)]/70">
        <div className="max-w-4xl mx-auto px-6 py-5 flex items-center gap-4">
          <button
            onClick={() => router.push("/")}
            className="btn-secondary px-4 py-2 flex items-center gap-2 text-sm font-semibold"
          >
            <ArrowLeft size={18} />
            Home
          </button>
          <h1 className="text-xl font-bold text-[var(--text-primary)]">
            Past runs
          </h1>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-8">
        <div className="glass-panel hero-shimmer p-5 sm:p-7">
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-16 text-[var(--text-secondary)]">
            <Loader2 size={24} className="animate-spin" />
            Loading...
          </div>
        ) : error ? (
          <div className="flex items-center gap-2 py-16 text-[var(--danger)]">
            <AlertCircle size={24} />
            {error}
          </div>
        ) : runs.length === 0 ? (
          <div className="text-center py-16 text-[var(--text-secondary)]">
            <Sparkles size={48} className="mx-auto mb-4 opacity-50" />
            <p>No runs yet. Start your first one from the home page.</p>
            <Link
              href="/"
              className="inline-block mt-4 text-[var(--accent)] font-semibold hover:underline"
            >
              Go to Home →
            </Link>
          </div>
        ) : (
          <ul className="space-y-3">
            {runs.map((run) => (
              <li key={run.id}>
                <Link
                  href={`/run/${run.id}`}
                  className="block p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] hover:border-[var(--accent)]/60 transition-colors"
                >
                  <div className="flex items-start justify-between gap-4">
                    <p className="text-[var(--text-primary)] font-medium line-clamp-2 flex-1 min-w-0">
                      {run.problem_raw}
                    </p>
                    {statusBadge(run.status)}
                  </div>
                  <div className="mt-2 text-xs text-[var(--text-muted)]">
                    {formatDate(run.created_at)}
                    {run.completed_at && ` • Completed ${formatDate(run.completed_at)}`}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
        </div>
      </main>
    </div>
  );
}
