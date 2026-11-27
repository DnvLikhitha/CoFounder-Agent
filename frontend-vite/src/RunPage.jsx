import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AgentProgressTracker, ProgressOverview, Status } from './AgentProgressTracker.jsx'
import { FounderReview } from './FounderReview.jsx'
import { Evaluations, OutputSection } from './OutputSection.jsx'
import { watchRun } from './lib/watch-run.js'
import { summarizeProgress } from './lib/run-progress.js'

const initial = { snapshot: null, connection: 'loading', message: '' }

export default function RunRoute({ client }) {
  const { runId } = useParams()
  return <RunPage key={runId} runId={runId} client={client} />
}

function RunPage({ runId, client }) {
  const [view, setView] = useState(initial)
  const [activeArtifactId, setActiveArtifactId] = useState(null)
  const [reload, setReload] = useState({ attempt: 0, stale: false })
  const { attempt, stale } = reload
  const refresh = () => setReload((value) => ({ ...value, attempt: value.attempt + 1 }))
  const refreshStaleReview = () => setReload((value) => ({ attempt: value.attempt + 1, stale: true }))
  useEffect(() => {
    const watcher = watchRun(client, runId, (next) => {
      setView((previous) => ({
        ...next, attempt, current: next.snapshot !== null, snapshot: next.snapshot ?? previous.snapshot,
      }))
    })
    return watcher.close
  }, [client, runId, attempt])

  const { snapshot, connection, message } = view
  if (!snapshot) {
    return (
      <main className="page narrow">
        <h1>Run details</h1>
        <ConnectionNotice connection={connection} message={message} refresh={refresh} />
        {connection === 'loading' && <p role="status">Loading run…</p>}
        <Link to="/history">Back to run history</Link>
      </main>
    )
  }

  const current = view.attempt === attempt && view.current
  const review = current && snapshot.status === 'awaiting_review' ? snapshot.pending_review : null
  const progress = summarizeProgress(snapshot.manifest, snapshot.steps)
  const exportable = ['succeeded', 'partial'].includes(snapshot.status)
  function viewArtifact(id) {
    setActiveArtifactId(id)
    document.getElementById('outputs-title')?.focus()
  }
  return (
    <main className="page">
      <div className="run-heading">
        <Link className="back-link" to="/history">Run history</Link>
        <h1>{snapshot.input.problem}</h1>
        <div className="run-meta">
          <span aria-live="polite"><Status status={snapshot.status} /></span>
          <span>{[snapshot.input.domain, snapshot.input.geography].filter(Boolean).join(' · ')}</span>
          {connection === 'connected' && <span role="status">Updates connected</span>}
          {connection === 'closed' && <span>Run updates complete</span>}
        </div>
      </div>
      <ConnectionNotice connection={connection} message={message} refresh={refresh} />
      {stale && (
        <ReviewRefreshNotice current={current} review={review} failed={view.attempt === attempt && connection === 'error'} />
      )}
      {snapshot.status === 'partial' && <PartialNotice snapshot={snapshot} />}
      {snapshot.status === 'failed' && (
        <p className="notice error" role="alert">{snapshot.error?.message ?? 'The run failed.'}</p>
      )}
      <ProgressOverview progress={progress} />
      {review && (
        <FounderReview key={JSON.stringify([attempt, review.review_id, review.artifact_ids])} review={review}
          artifacts={snapshot.artifacts} client={client} runId={runId} onStale={refreshStaleReview}
          onViewArtifact={viewArtifact} />
      )}
      <div className="run-grid">
        <div className="results-workspace">
          <OutputSection artifacts={snapshot.artifacts} evaluations={snapshot.evaluations} client={client} runId={runId}
            steps={progress.steps} status={snapshot.status} activeId={activeArtifactId} onSelect={setActiveArtifactId} />
          {exportable && <Exports client={client} runId={runId} partial={snapshot.status === 'partial'} />}
        </div>
        <AgentProgressTracker steps={progress.steps} runStatus={snapshot.status} artifacts={snapshot.artifacts}
          onViewArtifact={viewArtifact} />
      </div>
      <Evaluations evaluations={snapshot.evaluations} artifacts={snapshot.artifacts} manifest={snapshot.manifest} />
    </main>
  )
}

function ReviewRefreshNotice({ current, review, failed }) {
  let message = 'This review changed. Refreshing the current checkpoint…'
  if (current) {
    message = review ? 'This review changed. Check the current checkpoint before submitting again.'
      : 'This review is no longer pending. The latest run status is shown.'
  } else if (failed) {
    message = 'The latest checkpoint could not be loaded.'
  }
  return <p className="notice" role="status">{message}</p>
}

function PartialNotice({ snapshot }) {
  const states = new Map(snapshot.steps.map(({ step_id, status }) => [step_id, status]))
  const incomplete = snapshot.manifest.steps
    .filter(({ step_id, required }) => required && states.get(step_id) !== 'succeeded')
    .map(({ label }) => label)
  const count = snapshot.artifacts.length
  return (
    <p className="notice warning" role="status">
      {count} {count === 1 ? 'artifact is' : 'artifacts are'} available.
      {incomplete.length > 0 && ` Incomplete required steps: ${incomplete.join(', ')}.`}
      {snapshot.error?.message && ` ${snapshot.error.message}`}
    </p>
  )
}

function ConnectionNotice({ connection, message, refresh }) {
  if (connection === 'error') {
    return <div className="notice error"><p role="alert">{message}</p><button onClick={refresh}>Retry connection</button></div>
  }
  if (connection === 'reconnecting' || connection === 'connecting') {
    return <p className="notice" role="status">{message || 'Connecting to the run…'}</p>
  }
  return null
}

function Exports({ client, runId, partial }) {
  const pending = useRef(null)
  const [state, setState] = useState({ format: null, error: '' })
  useEffect(() => () => pending.current?.abort(), [])

  async function download(format) {
    if (pending.current) return
    const request = new AbortController()
    pending.current = request
    setState({ format, error: '' })
    try {
      const { blob, filename } = await client.downloadExport(runId, format, { signal: request.signal })
      if (request.signal.aborted) return
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = filename
      anchor.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      setState({ format: null, error: '' })
    } catch (error) {
      if (!request.signal.aborted) setState({ format: null, error: error.message })
    } finally {
      pending.current = null
    }
  }

  return (
    <section className="panel exports">
      <h2>Export plan</h2>
      {partial && <p className="muted">Exports contain the available results from this partial run.</p>}
      {client.supportsExports ? (
        <div className="actions">
          {Object.entries({ markdown: 'Markdown', pdf: 'PDF', pptx: 'PowerPoint' }).map(([format, label]) => (
            <button key={format} disabled={state.format !== null} onClick={() => download(format)}>
              {state.format === format ? 'Preparing…' : label}
            </button>
          ))}
        </div>
      ) : <p className="muted">Downloads are available with the live API.</p>}
      {state.error && <p className="notice error" role="alert">{state.error}</p>}
    </section>
  )
}
