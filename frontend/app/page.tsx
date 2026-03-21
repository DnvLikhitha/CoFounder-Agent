"use client";

import Link from "next/link";
import { InputForm } from "@/components/InputForm";
import { History } from "lucide-react";

export default function Home() {
  return (
    <div className="app-shell">
      <header className="border-b border-[var(--border)]/70">
        <div className="max-w-5xl mx-auto px-6 py-5 flex items-center justify-between">
          <h1 className="text-xl sm:text-2xl font-bold text-[var(--text-primary)]">
            AI Startup Co-Founder
          </h1>
          <Link
            href="/history"
            className="btn-secondary px-4 py-2 flex items-center gap-2 text-sm font-semibold"
          >
            <History size={18} />
            Past runs
          </Link>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-12 sm:py-20">
        <div className="glass-panel hero-shimmer px-7 py-10 sm:px-12 sm:py-14">
          <div className="text-center mb-12">
            <p className="inline-flex px-3 py-1 rounded-full text-xs font-semibold tracking-wide uppercase bg-[var(--accent-dim)] text-[var(--accent)] mb-4">
              AI-first startup planner
            </p>
            <h2 className="text-3xl sm:text-5xl font-bold text-[var(--text-primary)] mb-4">
            From problem → fundable startup plan
            </h2>
            <p className="text-base sm:text-lg text-[var(--text-secondary)] max-w-2xl mx-auto">
              16 specialized AI agents collaborate to generate market analysis, product strategy, financial projections, and a complete investor-ready narrative in minutes.
            </p>
          </div>

          <div className="flex justify-center">
            <InputForm />
          </div>

          <p className="mt-8 text-center text-sm text-[var(--text-muted)]">
            No MBA required. Just describe the problem and get an execution-ready blueprint.
          </p>
        </div>
      </main>
    </div>
  );
}
