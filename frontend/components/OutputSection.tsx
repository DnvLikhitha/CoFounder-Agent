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
    <section className="glass-panel flex-1 flex flex-col min-w-0 overflow-hidden border border-indigo-500/20">
      {/* Tab bar */}
      <div className="flex gap-2 px-4 pt-4 border-b border-indigo-500/25 overflow-x-auto flex-shrink-0 bg-gradient-to-r from-indigo-500/10 via-purple-500/5 to-transparent">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => onActiveTabChange(tab.key)}
            className="px-3 py-2 text-xs font-semibold rounded-t-lg border border-transparent border-b-0 whitespace-nowrap mb-[-1px] transition-all"
            style={{
              background: activeTab === tab.key ? "color-mix(in srgb, var(--bg-card) 92%, #6366f1 8%)" : "transparent",
              color: activeTab === tab.key ? "#c7d2fe" : "var(--text-secondary)",
              borderColor: activeTab === tab.key ? "rgba(99, 102, 241, 0.3)" : "transparent",
            }}
          >
            {tab.emoji} {tab.label}
          </button>
        ))}
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-auto p-4 sm:p-5">
        <div className="h-full rounded-xl border border-indigo-500/20 bg-[var(--bg-card)]/90 p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
        {isPending && (
          <div className="mb-4 inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium bg-indigo-500/15 text-indigo-200 border border-indigo-500/25">
            <span className="inline-block w-2 h-2 rounded-full bg-indigo-300 animate-pulse" />
            Waiting for this agent output...
          </div>
        )}
        <div
          className="markdown-content"
          style={{
            fontSize: 14,
            lineHeight: 1.7,
            color: "var(--text-primary)",
          }}
          dangerouslySetInnerHTML={{ __html: markdownToHtml(content) }}
        />
        </div>
      </div>
    </section>
  );
}

/** Simple markdown-to-HTML for our structured output (headings, bold, lists, tables, code) */
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
