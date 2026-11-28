import { useEffect, useRef, useState } from 'react'
import { ArtifactContent } from './ArtifactContent.jsx'
import { claimValue, readEvidence, readUncertainty, revisionLabel, webUrl } from './lib/artifact-details.js'
import { useArtifact } from './lib/use-artifact.js'
import { saveDownload } from './lib/exports.js'

export function OutputSection({ artifacts, evaluations, client, runId, status, steps, activeId, claimPath,
  onSelect, onViewArtifact = onSelect, pricingReview }) {
  const order = new Map(steps.map((step, position) => [step.step_id, position]))
  const references = new Map(artifacts.map((artifact) => [artifact.artifact_id, artifact]))
  const superseded = new Set(artifacts.map((artifact) => artifact.supersedes_artifact_id).filter(Boolean))
  const stale = (artifact) => artifact.input_artifact_ids?.some((id) => superseded.has(id))
  const regenerating = status === 'running' ? steps.filter((step) => ['queued', 'running'].includes(step.status) &&
    artifacts.some((artifact) => artifact.step_id === step.step_id && !superseded.has(artifact.artifact_id) && stale(artifact))) : []
  const available = [...artifacts].sort((a, b) => (order.get(a.step_id) ?? steps.length) - (order.get(b.step_id) ?? steps.length) ||
    (b.revision ?? 0) - (a.revision ?? 0)).map((artifact) => ({
    id: artifact.artifact_id, label: artifact.revision ? `${artifact.title} · ${revisionLabel(artifact)}` : artifact.title,
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
  const selected = active?.artifact
  const prior = references.get(selected?.supersedes_artifact_id)
  const regenerated = prior && stale(prior) && !stale(selected) && selected.input_artifact_ids?.length > 0
  return (
    <section className="panel outputs" aria-labelledby="outputs-title">
      <header className="section-heading">
        <h2 id="outputs-title" tabIndex={-1}>Run outputs</h2>
        <span>{artifacts.length} available</span>
      </header>
      {regenerating.length > 0 && <p className="notice" role="status">
        Regenerating {regenerating.map(({ label }) => label).join(', ')} using updated inputs.
      </p>}
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
          {selected ? (
            <Artifact key={active.id} reference={selected} client={client} runId={runId}
              historical={superseded.has(active.id)}
              staleInputs={stale(selected)} regenerated={regenerated}
              draftForecast={selected.step_id === 'financial_projections' && pricingReview}
              rejected={steps.some((step) => step.step_id === selected.step_id && step.error?.code === 'review_rejected')}
              revisions={available.map(({ artifact }) => artifact).filter((artifact) =>
                artifact.step_id === selected.step_id && artifact.kind === selected.kind)}
              references={references} onSelect={onViewArtifact} claimPath={active.id === activeId ? claimPath : null}
              evaluations={evaluations.filter((item) => item.artifact_id === active.id)} />
          ) : <MissingArtifact entry={active} status={status} references={references} onSelect={onViewArtifact}
            evaluations={evaluations.filter((item) => item.step_id === active.step.step_id && !item.artifact_id)} />}
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

function MissingArtifact({ entry, status, evaluations, references, onSelect }) {
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
      {evaluations.length > 0 && <EvaluationList evaluations={evaluations} references={references} onSelect={onSelect} />}
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

function Artifact({ reference, client, runId, evaluations, historical, staleInputs, regenerated, draftForecast,
  rejected, revisions, references, onSelect, claimPath }) {
  const { result, retry } = useArtifact(client, runId, reference)
  const [comparisonId, setComparisonId] = useState('')
  const comparison = revisions.find(({ artifact_id }) => artifact_id === comparisonId)

  return (
    <article>
      <div className="section-heading">
        <h3>{reference.title}</h3>
        <span className={`status status-${reference.quality === 'complete' ? 'succeeded' : 'partial'}`}>{qualities[reference.quality]}</span>
      </div>
      <p className="muted artifact-revision">{revisionLabel(reference)}{reference.revision && <> · <code>{reference.artifact_id}</code></>}</p>
      {historical && <p className="notice">A newer revision is available.</p>}
      {staleInputs && <p className="notice warning">This revision used earlier assumptions.</p>}
      {regenerated && <p className="notice" role="status">Regenerated using updated inputs.</p>}
      {draftForecast && <p className="notice warning">This forecast is a draft pending pricing approval.</p>}
      {rejected && <p className="notice warning">The founder rejected the assumptions used in this output.</p>}
      {reference.quality === 'partial' && <p className="notice warning">This output is available with gaps.</p>}
      {reference.quality === 'fallback' && <p className="notice warning">This is a fallback output.</p>}
      {revisions.length > 1 && (
        <section className="artifact-revisions" aria-labelledby="revision-history">
          <h4 id="revision-history">Revision history</h4>
          <ul className="actions">
            {revisions.map((item) => <li key={item.artifact_id}>
              <button type="button" aria-pressed={item === reference} onClick={() => onSelect(item.artifact_id)}>
                {revisionLabel(item)}
              </button>
            </li>)}
          </ul>
          <label htmlFor="revision-comparison">Compare with</label>
          <select id="revision-comparison" className="input-surface" value={comparisonId}
            onChange={(event) => setComparisonId(event.target.value)}>
            <option value="">Choose a revision</option>
            {revisions.filter((item) => item !== reference).map((item) => (
              <option value={item.artifact_id} key={item.artifact_id}>{revisionLabel(item)}</option>
            ))}
          </select>
        </section>
      )}
      {!result && <p className="muted" role="status">Loading artifact…</p>}
      {result?.error && (
        <div className="notice error"><p role="alert">{result.error}</p>
          <button onClick={retry}>Retry artifact</button>
        </div>
      )}
      {result?.artifact && <>
        {client.supportsExports && <button onClick={() => downloadArtifact(result.artifact)}>Download artifact</button>}
        {comparison && <RevisionComparison key={comparison.artifact_id} current={result.artifact}
          other={comparison} client={client} runId={runId} />}
        <ArtifactDetail reference={reference} content={result.artifact.content} evaluations={evaluations}
          references={references} onSelect={onSelect} claimPath={claimPath} />
      </>}
    </article>
  )
}

function RevisionComparison({ current, other, client, runId }) {
  const { result, retry } = useArtifact(client, runId, other)
  return <section className="artifact-detail" aria-labelledby="comparison-heading">
    <h4 id="comparison-heading">Revision comparison</h4>
    {!result && <p role="status">Loading {revisionLabel(other)}…</p>}
    {result?.error && <div className="notice error"><p role="alert">{result.error}</p>
      <button onClick={retry}>Retry comparison</button></div>}
    {result?.artifact && <div className="revision-comparison">
      {[result.artifact, current].sort((a, b) => (a.reference.revision ?? 0) - (b.reference.revision ?? 0))
        .map(({ reference, content }) => <div key={reference.artifact_id}>
          <h5>{revisionLabel(reference)}</h5>
          <ArtifactContent reference={reference} content={content} />
        </div>)}
    </div>}
  </section>
}

function downloadArtifact({ reference, content }) {
  const type = reference.media_type
  const json = type === 'application/json'
  const extension = json ? 'json' : type === 'text/markdown' ? 'md' : 'txt'
  const filename = `${reference.artifact_id.replace(/[^\w.-]/g, '_')}.${extension}`
  saveDownload(new Blob([json ? JSON.stringify(content, null, 2) : content], { type }), filename)
}

function ArtifactDetail({ reference, content, evaluations, references, onSelect, claimPath }) {
  const { assumptions, sources } = readEvidence(content)
  const uncertainty = readUncertainty(content)
  return (
    <div className="artifact-detail">
      {claimPath != null && <EvidenceClaim content={content} pointer={claimPath} />}
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
      <section aria-labelledby="artifact-assumptions">
        <h4 id="artifact-assumptions">Assumptions</h4>
        <Assumptions entries={assumptions} />
      </section>
      <section aria-labelledby="artifact-uncertainty">
        <h4 id="artifact-uncertainty">Uncertainty and limitations</h4>
        {uncertainty.length ? <Assumptions entries={uncertainty} /> : <p className="muted">No uncertainty notes were supplied.</p>}
      </section>
      {reference.input_artifact_ids?.length > 0 && <section>
        <h4>Input revisions</h4>
        <ul>{reference.input_artifact_ids.map((id) => <li key={id}>
          <ArtifactJump artifactId={id} references={references} onSelect={onSelect} />
        </li>)}</ul>
      </section>}
      <section>
        <h4>Artifact evaluations</h4>
        <EvaluationList evaluations={evaluations} references={references} onSelect={onSelect} />
      </section>
    </div>
  )
}

function EvidenceClaim({ content, pointer }) {
  const region = useRef(null)
  useEffect(() => { region.current?.focus() }, [pointer])
  const value = claimValue(content, pointer)
  return <section className="notice" id="evidence-claim" tabIndex={-1} ref={region} aria-label="Evidence claim">
    <h4>Evidence claim</h4>
    <code>{pointer || '/'}</code>
    {value === undefined ? <p>This field is unavailable in this revision.</p> : (
      <pre className="evidence-value">{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre>
    )}
  </section>
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

export function Evaluations({ evaluations, artifacts, steps, onViewArtifact }) {
  const references = new Map(artifacts.map((artifact) => [artifact.artifact_id, artifact]))
  const byStep = new Map(steps.map(({ step_id }) => [step_id, []]))
  const unassigned = []
  for (const evaluation of evaluations) {
    const group = byStep.get(evaluation.step_id) ?? unassigned
    group.push(evaluation)
  }
  return (
    <section className="panel evaluations">
      <h2>Evaluations</h2>
      {steps.map((step) => <section key={step.step_id} className="agent-evaluation">
        <h3>{step.label}</h3>
        <EvaluationList evaluations={byStep.get(step.step_id)}
          references={references} onSelect={onViewArtifact} showTarget />
      </section>)}
      {unassigned.length > 0 && <section className="agent-evaluation">
        <h3>Run-wide and unassigned evaluations</h3>
        <EvaluationList evaluations={unassigned} references={references} onSelect={onViewArtifact} showTarget />
      </section>}
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

function EvaluationList({ evaluations, references, onSelect, showTarget }) {
  if (!evaluations.length) return <p className="muted">Not evaluated. No evaluation was published.</p>
  return (
    <ul className="evaluation-list">
      {evaluations.map((evaluation) => (
        <li key={evaluation.evaluation_id}>
          <div className="section-heading">
            <strong>{evaluation.method === 'llm' ? 'Model judgment' : evaluation.method === 'heuristic'
              ? 'Deterministic checks' : evaluation.evaluator}</strong>
            {evaluation.outcome !== 'not_evaluated' && evaluation.outcome !== 'not_applicable' && (
              evaluation.score == null ? <span>Score unavailable</span> : <strong className="score">{score.format(evaluation.score)}</strong>
            )}
          </div>
          <p><strong>{outcomes[evaluation.outcome]}</strong> <span className="muted">· Version {evaluation.evaluator_version}</span></p>
          {showTarget && <p>{evaluation.artifact_id
            ? <ArtifactJump artifactId={evaluation.artifact_id} references={references} onSelect={onSelect} />
            : <span className="muted">{evaluation.step_id == null ? 'Run-level evaluation' : 'Agent-level evaluation'}</span>}</p>}
          {evaluation.dimensions?.length ? <dl className="reasons">{evaluation.dimensions.map((item) => (
            <div key={item.dimension}>
              <dt>{dimensions[item.dimension]} · {outcomes[item.outcome]}</dt>
              <dd>{item.reason}</dd>
            </div>
          ))}</dl> : null}
          {evaluation.reasons.length > 0 && <ul className="reasons">{evaluation.reasons.map((reason, index) => (
            <li key={index}>{reason}</li>
          ))}</ul>}
          {evaluation.evidence?.length > 0 && <ul className="reasons">{evaluation.evidence.map((item) => (
            <EvidenceLink key={JSON.stringify(item)} item={item} evaluatedId={evaluation.artifact_id}
              references={references} onSelect={onSelect} />
          ))}</ul>}
        </li>
      ))}
    </ul>
  )
}

function EvidenceLink({ item, evaluatedId, references, onSelect }) {
  const url = webUrl(item.source_url)
  const context = item.relationship === 'research_context'
  return <li>
    {relationships[item.relationship]}
    {!context && <> · {references.has(evaluatedId) && onSelect ? (
      <button className="artifact-link" type="button" onClick={() => onSelect(evaluatedId, item.claim_path)}>
        View claim <code>{item.claim_path}</code>
      </button>
    ) : <code>{item.claim_path}</code>}</>}
    {' · '}<ArtifactJump artifactId={item.artifact_id} references={references} onSelect={onSelect} />
    {url && <> · <a href={url} target="_blank" rel="noreferrer">View source</a></>}
  </li>
}

function ArtifactJump({ artifactId, references, onSelect }) {
  const reference = references.get(artifactId)
  if (!reference || !onSelect) return <code>{artifactId}</code>
  return <button className="artifact-link" type="button" onClick={() => onSelect(artifactId)}>
    {reference.title}{reference.revision && ` · ${revisionLabel(reference)}`}
  </button>
}
