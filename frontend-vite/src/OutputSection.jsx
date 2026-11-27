import { useEffect, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { statusLabels } from './lib/run-state.js'

export function OutputSection({ artifacts, client, runId, status }) {
  const [activeId, setActiveId] = useState(null)
  const active = artifacts.find((item) => item.artifact_id === activeId) ?? artifacts[0]
  return (
    <section className="panel outputs" aria-labelledby="outputs-title">
      <h2 id="outputs-title">Outputs</h2>
      {active ? (
        <>
          <div className="artifact-tabs" role="group" aria-label="Available artifacts">
            {artifacts.map((artifact) => (
              <button type="button" key={artifact.artifact_id} aria-pressed={active === artifact}
                onClick={() => setActiveId(artifact.artifact_id)}>
                {artifact.title}
              </button>
            ))}
          </div>
          <Artifact key={active.artifact_id} reference={active} client={client} runId={runId} />
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

function Artifact({ reference, client, runId }) {
  const [result, setResult] = useState(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const request = new AbortController()
    client.getArtifact(runId, reference.artifact_id, { signal: request.signal }).then(
      (artifact) => { if (!request.signal.aborted) setResult({ artifact }) },
      (error) => { if (!request.signal.aborted) setResult({ error: error.message }) },
    )
    return () => request.abort()
  }, [client, runId, reference.artifact_id, attempt])

  return (
    <article>
      <div className="section-heading">
        <h3>{reference.title}</h3>
        <span className="artifact-quality">{reference.quality}</span>
      </div>
      {!result && <p className="muted" role="status">Loading artifact…</p>}
      {result?.error && (
        <div className="notice error"><p role="alert">{result.error}</p>
          <button onClick={() => { setResult(null); setAttempt((value) => value + 1) }}>Retry artifact</button>
        </div>
      )}
      {result?.artifact && <ArtifactContent reference={reference} content={result.artifact.content} />}
    </article>
  )
}

function ArtifactContent({ reference, content }) {
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
    const sources = data.tool_evidence?.serpapi_sources
    const sections = [
      typeof data.audience === 'string' && `**Audience** — ${data.audience}`, table, list,
      typeof data.market_timing === 'string' && `**Why now** — ${data.market_timing}`,
      Array.isArray(sources) && sources.length > 0 &&
        ['#### Research sources', ...sources.map((item) => `- ${item}`)].join('\n'),
    ].filter(Boolean)
    return sections.length > 0 ? sections.join('\n\n') : null
  }
  return null
}

export function Evaluations({ evaluations, artifacts, manifest }) {
  if (evaluations.length === 0) return null
  const score = new Intl.NumberFormat(undefined, { style: 'percent', maximumFractionDigits: 1 })
  return (
    <section className="panel evaluations">
      <h2>Evaluations</h2>
      <ul>
        {evaluations.map((evaluation) => {
          const artifact = artifacts.find((item) => item.artifact_id === evaluation.artifact_id)
          const step = manifest.steps.find((item) => item.step_id === evaluation.step_id)
          return (
            <li key={evaluation.evaluation_id}>
              <div className="section-heading">
                <strong>{artifact?.title ?? step?.label ?? evaluation.evaluator}</strong>
                {evaluation.score != null && <strong className="score">{score.format(evaluation.score)}</strong>}
              </div>
              <p className="muted">{evaluation.evaluator} · {evaluation.evaluator_version} · {
                statusLabels[evaluation.outcome] ?? evaluation.outcome.replaceAll('_', ' ')
              }</p>
              {evaluation.reasons.length > 0 && <ul className="reasons">{evaluation.reasons.map((reason, index) => (
                <li key={index}>{reason}</li>
              ))}</ul>}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
