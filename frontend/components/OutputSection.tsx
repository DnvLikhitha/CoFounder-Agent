"use client";

interface Tab {
  key: string;
  label: string;
  emoji: string;
}

interface OutputSectionProps {
  tabs: Tab[];
  activeTab: string;
  onActiveTabChange: (key: string) => void;
  outputs: Record<string, any>;
  isComplete: boolean;
  renderOutput: (key: string, data: any) => string;
}

export function OutputSection({
  tabs,
  activeTab,
  onActiveTabChange,
  outputs,
  isComplete,
  renderOutput,
}: OutputSectionProps) {
  const content = renderOutput(activeTab, outputs[activeTab]);
  const isPending = !outputs[activeTab];

  return (
    <section className="glass-panel flex-1 flex flex-col min-w-0 overflow-hidden border border-white/10 bg-slate-900/60 backdrop-blur-2xl shadow-2xl rounded-2xl relative">
      {/* Tab bar */}
      <div className="flex gap-3 px-6 py-5 border-b border-white/10 overflow-x-auto flex-shrink-0 scrollbar-hide bg-black/10 relative z-20">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.key;
          return (
              <button
                key={tab.key}
                onClick={() => onActiveTabChange(tab.key)}
                className={`px-4 py-2.5 text-xs font-bold rounded-full whitespace-nowrap transition-all duration-300 border ${
                  isActive 
                    ? "bg-gradient-to-r from-cyan-500 to-blue-600 text-white border-transparent shadow-[0_0_15px_rgba(34,211,238,0.4)] scale-105" 
                    : "bg-white/5 text-slate-400 border-white/5 hover:border-white/20 hover:text-white"
                }`}
              >
              <span className="opacity-80 mr-1.5">{tab.emoji}</span> {tab.label}
            </button>
          );
        })}
      </div>

      {/* Content area */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-cyan-900/20 via-transparent to-transparent pointer-events-none z-0" />
      <div className="flex-1 overflow-auto p-6 sm:p-10 relative z-10">
        {isPending ? (
          <div className="flex flex-col gap-5 w-full opacity-70">
            <div className="inline-flex self-start items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium bg-[var(--accent-dim)] text-[var(--accent)] border border-[var(--accent)]/20 shadow-sm">
              <span className="inline-block w-2 h-2 rounded-full bg-[var(--accent)] animate-pulse" />
              Generating response...
            </div>
            <div className="space-y-4 pt-4">
              <div className="h-8 bg-[var(--border)] rounded-md w-1/3 hero-shimmer" />
              <div className="space-y-3">
                <div className="h-4 bg-[var(--border)] rounded w-full hero-shimmer" />
                <div className="h-4 bg-[var(--border)] rounded w-11/12 hero-shimmer" />
                <div className="h-4 bg-[var(--border)] rounded w-5/6 hero-shimmer" />
                <div className="h-4 bg-[var(--border)] rounded w-full hero-shimmer" />
                <div className="h-4 bg-[var(--border)] rounded w-3/4 hero-shimmer" />
              </div>
            </div>
          </div>
        ) : (
          <div
            className="markdown-content"
            style={{
              fontSize: 15,
              lineHeight: 1.8,
              color: "var(--text-primary)",
            }}
            dangerouslySetInnerHTML={{ __html: markdownToHtml(content) }}
          />
        )}
      </div>
    </section>
  );
}

/** Simple markdown-to-HTML for our structured output (headings, bold, lists, tables, code, links) */
function markdownToHtml(md: string): string {
  if (!md) return "";
  let html = md
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*([^*])/g, "<em>$1</em>$2");
  // Markdown links: [text](url)
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="output-link">$1</a>');
  // Bare URLs (not already inside an href="..." or anchor tag)
  html = html.replace(/(?<!href="|href='|>)(https?:\/\/[^\s<)"',]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer" class="output-link">$1</a>');
  html = html.replace(/^\- (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>[\s\S]*?<\/li>\n?)+/g, "<ul>$&</ul>");
  // Tables: | a | b | -> <table><tr><td>a</td><td>b</td></tr></table>
  const lines = html.split("\n");
  const out: string[] = [];
  let inTable = false;
  let tableRows: string[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\|.+\|$/.test(line)) {
      const cells = line.split("|").slice(1, -1).map((c) => c.trim());
      const isSep = cells.every((c) => /^[-:]+$/.test(c));
      if (isSep) {
        inTable = true;
        continue; // Skip separator row
      }
      const tag = tableRows.length === 0 ? "th" : "td";
      tableRows.push("<tr>" + cells.map((c) => `<${tag}>${c}</${tag}>`).join("") + "</tr>");
      inTable = true;
    } else {
      if (inTable && tableRows.length > 0) {
        out.push("<table><tbody>" + tableRows.join("") + "</tbody></table>");
        tableRows = [];
        inTable = false;
      }
      out.push(line);
    }
  }
  if (inTable && tableRows.length > 0) {
    out.push("<table><tbody>" + tableRows.join("") + "</tbody></table>");
  }
  html = out.join("\n");
  html = html.replace(/```json\n([\s\S]*?)```/g, "<pre><code>$1</code></pre>");
  html = html.replace(/\n/g, "<br />");
  return html;
}
