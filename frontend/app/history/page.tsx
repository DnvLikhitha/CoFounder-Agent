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
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <header className="border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center gap-4">
          <button
            onClick={() => router.push("/")}
            className="flex items-center gap-2 text-sm font-medium text-zinc-600 dark:text-zinc-400 hover:text-violet-600 dark:hover:text-violet-400 transition-colors"
          >
            <ArrowLeft size={18} />
            Home
          </button>
          <h1 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">
            Past runs
          </h1>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8">
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-16 text-zinc-500">
            <Loader2 size={24} className="animate-spin" />
            Loading...
          </div>
        ) : error ? (
          <div className="flex items-center gap-2 py-16 text-red-600 dark:text-red-400">
            <AlertCircle size={24} />
            {error}
          </div>
        ) : runs.length === 0 ? (
          <div className="text-center py-16 text-zinc-500">
            <Sparkles size={48} className="mx-auto mb-4 opacity-50" />
            <p>No runs yet. Start your first one from the home page.</p>
            <Link
              href="/"
              className="inline-block mt-4 text-violet-600 dark:text-violet-400 font-medium hover:underline"
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
                  className="block p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 hover:border-violet-300 dark:hover:border-violet-700 transition-colors"
                >
                  <div className="flex items-start justify-between gap-4">
                    <p className="text-zinc-900 dark:text-zinc-100 font-medium line-clamp-2 flex-1 min-w-0">
                      {run.problem_raw}
                    </p>
                    {statusBadge(run.status)}
                  </div>
                  <div className="mt-2 text-xs text-zinc-500 dark:text-zinc-500">
                    {formatDate(run.created_at)}
                    {run.completed_at && ` • Completed ${formatDate(run.completed_at)}`}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
