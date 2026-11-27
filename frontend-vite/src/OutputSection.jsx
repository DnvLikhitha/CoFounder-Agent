import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { readEvidence } from './lib/artifact-details.js'
import { useArtifact } from './lib/use-artifact.js'

export function OutputSection({ artifacts, evaluations, client, runId, status, activeId, onSelect }) {
  const active = artifacts.find((item) => item.artifact_id === activeId) ?? artifacts[0]
  return (
    <section className="panel outputs" aria-labelledby="outputs-title">
      <h2 id="outputs-title" tabIndex={-1}>Outputs</h2>
      {active ? (
        <>
          <div className="artifact-tabs" role="group" aria-label="Available artifacts">
            {artifacts.map((artifact) => (
              <button type="button" key={artifact.artifact_id} aria-pressed={active === artifact}
                onClick={() => onSelect(artifact.artifact_id)}>
                {artifact.title}
              </button>
            ))}
          </div>
          <Artifact key={active.artifact_id} reference={active} client={client} runId={runId}
            evaluations={evaluations.filter((item) => item.artifact_id === active.artifact_id)} />
        </>
      ) : <p className="muted">{emptyMessage[status]}</p>}
    </section>
  )
}

const emptyMessage = {
  queued: 'Outputs appear here as the run progresses.',
  running: 'Outputs appear here as the run progresses.',
  awaiting_review: 'The run is paused for review.',
  succeeded: 'No artifacts were published.',
  partial: 'No artifacts were published.',
  failed: 'The run ended before publishing an artifact.',
}

const qualities = {
  complete: 'Complete output',
  partial: 'Partial output',
  fallback: 'Fallback output',
}

function Artifact({ reference, client, runId, evaluations }) {
  const { result, retry } = useArtifact(client, runId, reference)

  return (
    <article>
      <div className="section-heading">
        <h3>{reference.title}</h3>
        <span className={`status status-${reference.quality === 'complete' ? 'succeeded' : 'partial'}`}>{qualities[reference.quality]}</span>
      </div>
      <p className="muted artifact-revision">Artifact revision <code>{reference.artifact_id}</code></p>
      {reference.quality === 'partial' && <p className="notice warning">This output is available with gaps.</p>}
      {reference.quality === 'fallback' && <p className="notice warning">This is a fallback output.</p>}
      {!result && <p className="muted" role="status">Loading artifact…</p>}
      {result?.error && (
        <div className="notice error"><p role="alert">{result.error}</p>
          <button onClick={retry}>Retry artifact</button>
        </div>
      )}
      {result?.artifact && <ArtifactDetail reference={reference} content={result.artifact.content} evaluations={evaluations} />}
    </article>
  )
}

function ArtifactDetail({ reference, content, evaluations }) {
  const { assumptions, sources } = readEvidence(content)
  return (
    <div className="artifact-detail">
      <section>
        <h4>Output</h4>
        <ArtifactContent reference={reference} content={content} />
      </section>
      <section>
        <h4>Source references</h4>
        {sources.length === 0 ? <p className="muted">No source references were supplied.</p> : (
          <ul>
            {sources.map(({ label, url }) => (
              <li key={url ?? label}>{url ? <a href={url} target="_blank" rel="noreferrer">{label}</a> : label}</li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h4>Assumptions</h4>
        <Assumptions entries={assumptions} />
      </section>
      <section>
        <h4>Artifact evaluations</h4>
        <EvaluationList evaluations={evaluations} empty="No evaluations were published for this artifact." />
      </section>
    </div>
  )
}

export function Assumptions({ entries }) {
  if (!entries.length) return <p className="muted">No assumptions were supplied.</p>
  return (
    <ul>
      {entries.map(({ label, value }, index) => (
        <li key={index}>
          {label && <strong>{label} · </strong>}
          {typeof value === 'string' ? value : JSON.stringify(value)}
        </li>
      ))}
    </ul>
  )
}

function ArtifactContent({ reference, content }) {
  if (content === null || typeof content === 'string' && !content.trim()) {
    return <p className="muted">This artifact has no content.</p>
  }
  const markdown = reference.media_type === 'text/markdown' ? content : legacyMarkdown(reference.kind, content)
  if (typeof markdown === 'string') {
    return <div className="markdown-content"><Markdown remarkPlugins={[remarkGfm]}>{markdown}</Markdown></div>
  }
  if (typeof content === 'string') return <p className="plain-content">{content}</p>
  return <pre className="artifact-json">{JSON.stringify(content, null, 2)}</pre>
}

// Preserve the legacy formatted highlights when their expected fields are supplied.
function legacyMarkdown(kind, data) {
  if (!data || typeof data !== 'object') return null
  if (kind === 'executive_summary') {
    const summary = data.executive_summary ?? data.summary
    if (typeof summary !== 'string') return null
    return [
      summary,
      ...[['Mission', data.mission_statement], ['Elevator pitch', data.elevator_pitch],
        ['Investor email subject', data.investor_email_subject]]
        .filter(([, value]) => typeof value === 'string' && value)
        .map(([label, value]) => `**${label}** — ${value}`),
    ].join('\n\n')
  }
  if (kind === 'market_research') {
    const metrics = [
      ['TAM', data.tam_usd_billions, 'B'], ['SAM', data.sam_usd_billions, 'B'],
      ['SOM', data.som_usd_millions, 'M'], ['CAGR', data.cagr_percent, '%'],
    ].filter(([, value]) => typeof value === 'number')
    const table = metrics.length > 0 ? ['| Metric | Value |', '| --- | --- |',
      ...metrics.map(([name, value, unit]) => `| ${name} | ${unit === '%' ? '' : '$'}${value}${unit} |`)].join('\n') : ''
    const findings = data.market_trends ?? data.findings
    const list = Array.isArray(findings) && findings.every((item) => typeof item === 'string')
      ? findings.map((item) => `- ${item}`).join('\n') : ''
    const sections = [
      typeof data.audience === 'string' && `**Audience** — ${data.audience}`, table, list,
      typeof data.market_timing === 'string' && `**Why now** — ${data.market_timing}`,
    ].filter(Boolean)
    return sections.length > 0 ? sections.join('\n\n') : null
  }
  return null
}

export function Evaluations({ evaluations, artifacts, manifest }) {
  return (
    <section className="panel evaluations">
      <h2>Evaluations</h2>
      <EvaluationList evaluations={evaluations} empty="No evaluations have been published."
        target={(evaluation) => artifacts.find((item) => item.artifact_id === evaluation.artifact_id)?.title ??
          manifest.steps.find((item) => item.step_id === evaluation.step_id)?.label} />
    </section>
  )
}

const outcomes = {
  passed: 'Passed',
  failed: 'Failed',
  needs_review: 'Needs review',
  not_evaluated: 'Not evaluated',
}
const score = new Intl.NumberFormat(undefined, { style: 'percent', maximumFractionDigits: 1 })

function EvaluationList({ evaluations, empty, target }) {
  if (!evaluations.length) return <p className="muted">{empty}</p>
  return (
    <ul className="evaluation-list">
      {evaluations.map((evaluation) => (
        <li key={evaluation.evaluation_id}>
          <div className="section-heading">
            <strong>{evaluation.evaluator}</strong>
            {evaluation.score == null ? <span>Score unavailable</span>
              : <strong className="score">{score.format(evaluation.score)}</strong>}
          </div>
          <p className="muted">{[target?.(evaluation), outcomes[evaluation.outcome], `Version ${evaluation.evaluator_version}`].filter(Boolean).join(' · ')}</p>
          {evaluation.reasons.length > 0 && <ul className="reasons">{evaluation.reasons.map((reason, index) => (
            <li key={index}>{reason}</li>
          ))}</ul>}
        </li>
      ))}
    </ul>
  )
}
