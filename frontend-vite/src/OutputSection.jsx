import { ArtifactContent } from './ArtifactContent.jsx'
import { readEvidence, webUrl } from './lib/artifact-details.js'
import { useArtifact } from './lib/use-artifact.js'
import { saveDownload } from './lib/exports.js'

export function OutputSection({ artifacts, evaluations, client, runId, status, steps, activeId, onSelect, pricingReview }) {
  const order = new Map(steps.map((step, position) => [step.step_id, position]))
  const superseded = new Set(artifacts.map((artifact) => artifact.supersedes_artifact_id).filter(Boolean))
  const available = [...artifacts].sort((a, b) =>
    (order.get(a.step_id) ?? steps.length) - (order.get(b.step_id) ?? steps.length)).map((artifact) => ({
    id: artifact.artifact_id, label: artifact.revision ? `${artifact.title} · Revision ${artifact.revision}` : artifact.title,
    artifact,
  }))
  const unavailable = steps.flatMap((step) => step.artifact_kinds
    .filter((kind) => !artifacts.some((artifact) => artifact.step_id === step.step_id && artifact.kind === kind))
    .map((kind) => ({
      id: `missing:${step.step_id}:${kind}`,
      label: step.artifact_kinds.length > 1 ? `${step.label} · ${kind.replaceAll('_', ' ')}` : step.label,
      step,
    })))
  const choices = [...available, ...unavailable]
  const active = choices.find(({ id }) => id === activeId) ??
    available.find(({ artifact }) => `missing:${artifact.step_id}:${artifact.kind}` === activeId) ?? choices[0]
  return (
    <section className="panel outputs" aria-labelledby="outputs-title">
      <header className="section-heading">
        <h2 id="outputs-title" tabIndex={-1}>Run outputs</h2>
        <span>{artifacts.length} available</span>
      </header>
      {active ? (
        <>
          <div className="output-navigation">
            <label htmlFor="artifact-selector">Browse outputs</label>
            <select className="input-surface" id="artifact-selector" value={active.id}
              onChange={(event) => onSelect(event.target.value)}>
              <ArtifactOptions title="Available" choices={available} />
              <ArtifactOptions title="Pending or unavailable" choices={unavailable} />
            </select>
          </div>
          {active.artifact ? (
            <Artifact key={active.id} reference={active.artifact} client={client} runId={runId}
              historical={superseded.has(active.id)}
              staleInputs={active.artifact.input_artifact_ids?.some((id) => superseded.has(id))}
              draftForecast={active.artifact.step_id === 'financial_projections' && pricingReview}
              rejected={steps.some((step) => step.step_id === active.artifact.step_id && step.error?.code === 'review_rejected')}
              evaluations={evaluations.filter((item) => item.artifact_id === active.id)} />
          ) : <MissingArtifact entry={active} status={status} />}
        </>
      ) : <p className="muted">{emptyMessage[status]}</p>}
    </section>
  )
}

function ArtifactOptions({ title, choices }) {
  if (!choices.length) return null
  return (
    <optgroup label={title}>
      {choices.map(({ id, label, artifact }) => (
        <option key={id} value={id}>
          {label}{artifact && choices.some((item) => item.id !== id && item.label === label) ? ` · ${id}` : ''}
        </option>
      ))}
    </optgroup>
  )
}

function MissingArtifact({ entry, status }) {
  const { step, label } = entry
  const unavailable = ['succeeded', 'partial', 'failed'].includes(status) ||
    ['succeeded', 'partial', 'failed', 'skipped'].includes(step.status) || step.blocked
  return (
    <article>
      <h3>{label}</h3>
      <p className="muted">{unavailable
        ? 'No artifact was published for this output.'
        : 'This output will be available once the agent publishes it.'}</p>
      {step.error && <p className="notice warning">{step.error.message}</p>}
    </article>
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

function Artifact({ reference, client, runId, evaluations, historical, staleInputs, draftForecast, rejected }) {
  const { result, retry } = useArtifact(client, runId, reference)

  return (
    <article>
      <div className="section-heading">
        <h3>{reference.title}</h3>
        <span className={`status status-${reference.quality === 'complete' ? 'succeeded' : 'partial'}`}>{qualities[reference.quality]}</span>
      </div>
      <p className="muted artifact-revision">Artifact revision <code>{reference.artifact_id}</code></p>
      {historical && <p className="notice">A newer revision is available.</p>}
      {staleInputs && <p className="notice warning">This revision used earlier assumptions.</p>}
      {draftForecast && <p className="notice warning">This forecast is a draft pending pricing approval.</p>}
      {rejected && <p className="notice warning">The founder rejected the assumptions used in this output.</p>}
      {reference.quality === 'partial' && <p className="notice warning">This output is available with gaps.</p>}
      {reference.quality === 'fallback' && <p className="notice warning">This is a fallback output.</p>}
      {!result && <p className="muted" role="status">Loading artifact…</p>}
      {result?.error && (
        <div className="notice error"><p role="alert">{result.error}</p>
          <button onClick={retry}>Retry artifact</button>
        </div>
      )}
      {result?.artifact && <>
        {client.supportsExports && <button onClick={() => downloadArtifact(result.artifact)}>Download artifact</button>}
        <ArtifactDetail reference={reference} content={result.artifact.content} evaluations={evaluations} />
      </>}
    </article>
  )
}

function downloadArtifact({ reference, content }) {
  const type = reference.media_type
  const json = type === 'application/json'
  const extension = json ? 'json' : type === 'text/markdown' ? 'md' : 'txt'
  const filename = `${reference.artifact_id.replace(/[^\w.-]/g, '_')}.${extension}`
  saveDownload(new Blob([json ? JSON.stringify(content, null, 2) : content], { type }), filename)
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
  not_applicable: 'Not applicable',
}
const dimensions = {
  task_completion: 'Task completion', relevance: 'Relevance', consistency: 'Consistency',
  grounding: 'Grounding', completeness: 'Completeness',
}
const relationships = { citation: 'Cited source', matched_value: 'Matching value', research_context: 'Research context' }
const score = new Intl.NumberFormat(undefined, { style: 'percent', maximumFractionDigits: 1 })

function EvaluationList({ evaluations, empty, target }) {
  if (!evaluations.length) return <p className="muted">{empty}</p>
  return (
    <ul className="evaluation-list">
      {evaluations.map((evaluation) => (
        <li key={evaluation.evaluation_id}>
          <div className="section-heading">
            <strong>{evaluation.method === 'llm' ? 'Model judgment' : evaluation.method === 'heuristic'
              ? 'Deterministic checks' : evaluation.evaluator}</strong>
            {evaluation.score == null ? <span>Score unavailable</span>
              : <strong className="score">{score.format(evaluation.score)}</strong>}
          </div>
          <p className="muted">{[target?.(evaluation), outcomes[evaluation.outcome], `Version ${evaluation.evaluator_version}`].filter(Boolean).join(' · ')}</p>
          {evaluation.dimensions?.length ? <dl className="reasons">{evaluation.dimensions.map((item) => (
            <div key={item.dimension}>
              <dt>{dimensions[item.dimension]} · {outcomes[item.outcome]}</dt>
              <dd>{item.reason}</dd>
            </div>
          ))}</dl> : evaluation.reasons.length > 0 && <ul className="reasons">{evaluation.reasons.map((reason, index) => (
            <li key={index}>{reason}</li>
          ))}</ul>}
          {evaluation.evidence?.length > 0 && <ul className="reasons">{evaluation.evidence.map((link) => {
            const url = webUrl(link.source_url)
            return <li key={JSON.stringify(link)}>
              {relationships[link.relationship]} · <code>{link.claim_path}</code> · <code>{link.artifact_id}</code>
              {url && <> · <a href={url} target="_blank" rel="noreferrer">View source</a></>}
            </li>
          })}</ul>}
        </li>
      ))}
    </ul>
  )
}
