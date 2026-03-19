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

  return (
    <section
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        minWidth: 0,
        background: "var(--bg-primary)",
      }}
    >
      {/* Tab bar */}
      <div
        style={{
          display: "flex",
          gap: 2,
          padding: "12px 16px 0",
          borderBottom: "1px solid var(--border)",
          overflowX: "auto",
          flexShrink: 0,
        }}
      >
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => onActiveTabChange(tab.key)}
            style={{
              padding: "8px 14px",
              fontSize: 13,
              fontWeight: 500,
              borderRadius: "8px 8px 0 0",
              border: "1px solid transparent",
              borderBottom: "none",
              background: activeTab === tab.key ? "var(--bg-card)" : "transparent",
              color: activeTab === tab.key ? "var(--accent)" : "var(--text-secondary)",
              cursor: "pointer",
              whiteSpace: "nowrap",
              marginBottom: -1,
            }}
          >
            {tab.emoji} {tab.label}
          </button>
        ))}
      </div>

      {/* Content area */}
      <div
        style={{
          flex: 1,
          overflow: "auto",
          padding: 24,
          background: "var(--bg-card)",
          margin: 16,
          marginTop: 8,
          borderRadius: 12,
          border: "1px solid var(--border)",
        }}
      >
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
  html = html.replace(/(<li>.*?<\/li>\n?)+/gs, "<ul>$&</ul>");
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
