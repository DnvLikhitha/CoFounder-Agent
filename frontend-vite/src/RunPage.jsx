import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AgentProgressTracker, Status } from './AgentProgressTracker.jsx'
import { Evaluations, OutputSection } from './OutputSection.jsx'
import { watchRun } from './lib/watch-run.js'

const initial = { snapshot: null, connection: 'loading', message: '' }

export default function RunRoute({ client }) {
  const { runId } = useParams()
  return <RunPage key={runId} runId={runId} client={client} />
}

function RunPage({ runId, client }) {
  const [view, setView] = useState(initial)
  const [attempt, setAttempt] = useState(0)
  const refresh = () => setAttempt((value) => value + 1)
  useEffect(() => {
    const watcher = watchRun(client, runId, (next) => {
      setView((previous) => ({ ...next, snapshot: next.snapshot ?? previous.snapshot }))
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

  return (
    <main className="page">
      <div className="run-heading">
        <Link className="back-link" to="/history">Run history</Link>
        <h1>{snapshot.input.problem}</h1>
        <div className="run-meta">
          <span aria-live="polite"><Status status={snapshot.status} /></span>
          {[snapshot.input.domain, snapshot.input.geography].filter(Boolean).join(' · ')}
        </div>
      </div>
      <ConnectionNotice connection={connection} message={message} refresh={refresh} />
      {snapshot.status === 'partial' && (
        <p className="notice warning" role="status">
          Available outputs are shown below. {snapshot.error?.message ?? 'Some required work could not be completed.'}
        </p>
      )}
      {snapshot.status === 'failed' && (
        <p className="notice error" role="alert">{snapshot.error?.message ?? 'The run failed.'}</p>
      )}
      {snapshot.pending_review && (
        <Review key={snapshot.pending_review.review_id} review={snapshot.pending_review}
          artifacts={snapshot.artifacts} client={client} runId={runId} refresh={refresh} />
      )}
      <div className="run-grid">
        <OutputSection artifacts={snapshot.artifacts} client={client} runId={runId} status={snapshot.status} />
        <AgentProgressTracker manifest={snapshot.manifest} steps={snapshot.steps} />
      </div>
      <Evaluations evaluations={snapshot.evaluations} artifacts={snapshot.artifacts} manifest={snapshot.manifest} />
      {['succeeded', 'partial'].includes(snapshot.status) && <Exports client={client} runId={runId} />}
    </main>
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

function Review({ review, artifacts, client, runId, refresh }) {
  const pending = useRef(null)
  const previous = useRef(null)
  const [state, setState] = useState({ status: 'idle', error: '' })
  useEffect(() => () => pending.current?.abort(), [])

  async function submit(decision) {
    if (pending.current) return
    const payload = previous.current ?? { decision_id: crypto.randomUUID(), decision, comment: null }
    previous.current = payload
    const request = new AbortController()
    pending.current = request
    setState({ status: 'sending', error: '' })
    try {
      await client.decideReview(runId, review.review_id, payload, { signal: request.signal })
      if (!request.signal.aborted) setState({ status: 'submitted', error: '' })
    } catch (error) {
      if (!request.signal.aborted) {
        setState({ status: error.status === 409 ? 'conflict' : 'retry', error: error.message, decision })
      }
    } finally {
      pending.current = null
    }
  }

  const titles = artifacts.filter((artifact) => review.artifact_ids.includes(artifact.artifact_id))
    .map((artifact) => artifact.title)
  return (
    <section className="panel review">
      <h2>Review required</h2>
      <p>{review.prompt}</p>
      {titles.length > 0 && <p className="muted">For review · {titles.join(', ')}</p>}
      {state.error && <p className="notice error" role="alert">{state.error}</p>}
      <div className="actions">
        {state.status === 'idle' && (
          <><button className="primary" onClick={() => submit('approve')}>Approve</button>
            <button onClick={() => submit('reject')}>Reject</button></>
        )}
        {state.status === 'retry' && (
          <button onClick={() => submit(state.decision)}>Retry {state.decision === 'approve' ? 'approval' : 'rejection'}</button>
        )}
        {state.status === 'conflict' && <button onClick={refresh}>Refresh run</button>}
        {state.status === 'sending' && <p role="status">Sending decision…</p>}
        {state.status === 'submitted' && <p role="status">Decision submitted. Waiting for the run to update…</p>}
      </div>
    </section>
  )
}

function Exports({ client, runId }) {
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
