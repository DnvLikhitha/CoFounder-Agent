"use client";

import Link from "next/link";
import { InputForm } from "@/components/InputForm";
import { History } from "lucide-react";

export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-zinc-50 via-white to-violet-50/30 dark:from-zinc-950 dark:via-zinc-900 dark:to-violet-950/20">
      <header className="border-b border-zinc-200 dark:border-zinc-800">
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
          <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">
            AI Startup Co-Founder
          </h1>
          <Link
            href="/history"
            className="flex items-center gap-2 text-sm font-medium text-zinc-600 dark:text-zinc-400 hover:text-violet-600 dark:hover:text-violet-400 transition-colors"
          >
            <History size={18} />
            Past runs
          </Link>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-16 sm:py-24">
        <div className="text-center mb-12">
          <h2 className="text-3xl sm:text-4xl font-bold text-zinc-900 dark:text-zinc-100 mb-3">
            From problem → fundable startup plan
          </h2>
          <p className="text-lg text-zinc-600 dark:text-zinc-400 max-w-xl mx-auto">
            16 AI agents work together to produce market research, product specs, financials, and a pitch deck — in under 10 minutes.
          </p>
        </div>

        <div className="flex justify-center">
          <InputForm />
        </div>

        <p className="mt-8 text-center text-sm text-zinc-500 dark:text-zinc-500">
          No MBA, no consultant needed. Built with free, open-source tools.
        </p>
      </main>
    </div>
  );
}
