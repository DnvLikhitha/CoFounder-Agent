import { useEffect, useRef, useState } from 'react'
import { Assumptions } from './OutputSection.jsx'
import { readEvidence } from './lib/artifact-details.js'
import { useArtifact } from './lib/use-artifact.js'

const decisionLabels = {
  approve: 'approval',
  reject: 'rejection',
  revise: 'revision request',
}

export function FounderReview({ review, artifacts, client, runId, onStale, onViewArtifact }) {
  const pending = useRef(null)
  const submission = useRef(null)
  const [state, setState] = useState(() => ({
    status: client.getRevisionPreview?.(runId, review.review_id) ? 'revision-requested' : 'idle',
  }))
  const [revisionComment, setRevisionComment] = useState(null)
  useEffect(() => () => pending.current?.abort(), [])

  async function submit(decision) {
    if (pending.current) return
    const payload = submission.current ?? {
      decision_id: crypto.randomUUID(),
      decision,
      comment: decision === 'revise' ? revisionComment.trim() : null,
    }
    submission.current = payload
    const request = new AbortController()
    pending.current = request
    setState({ status: 'sending' })
    try {
      await client.decideReview(runId, review.review_id, payload, {
        signal: request.signal,
        expectedArtifactIds: review.artifact_ids,
      })
      if (request.signal.aborted) return
      if (decision === 'revise') {
        submission.current = null
        setRevisionComment(null)
        setState({ status: 'revision-requested' })
      } else {
        setState({ status: 'submitted', decision })
      }
    } catch (error) {
      if (request.signal.aborted) return
      if (error.status === 409) {
        onStale()
        return
      }
      const retryable = error.status == null || error.status >= 500 && error.retryable !== false
      if (!retryable) submission.current = null
      setState({ status: retryable ? 'retry' : 'idle', error: error.message, decision })
    } finally {
      pending.current = null
    }
  }

  const revisions = review.artifact_ids.map((id) => ({ id, reference: artifacts.find((item) => item.artifact_id === id) }))
  const canAct = state.status === 'idle' || state.status === 'revision-requested'
  const canRevise = client.supportsRevisionPreview && revisions.some(({ reference }) => reference)
  return (
    <section className="panel review" aria-labelledby="review-heading">
      <h2 id="review-heading">Review required</h2>
      <p>{review.prompt}</p>
      <p className="muted">Checkpoint <code>{review.review_id}</code></p>
      {revisions.length === 0 && <p className="muted">This checkpoint has no linked artifact revision.</p>}
      {revisions.map(({ id, reference }) => reference ? (
        <ReviewArtifact key={id} reference={reference} client={client} runId={runId} onView={onViewArtifact} />
      ) : <p key={id} className="muted">Artifact revision <code>{id}</code> is unavailable.</p>)}
      {state.error && <p className="notice error" role="alert">{state.error}</p>}
      {state.status === 'revision-requested' && (
        <p role="status">Revision request recorded in the fixture. This checkpoint is still awaiting approval.</p>
      )}
      {canAct && revisionComment === null && (
        <div className="actions">
          <button className="primary" onClick={() => submit('approve')}>Approve</button>
          <button onClick={() => submit('reject')}>Reject</button>
          {canRevise && <button onClick={() => setRevisionComment('')}>Request revision</button>}
          {!client.supportsRevisionPreview && <span className="muted">Revision requests are unavailable in v1.</span>}
        </div>
      )}
      {canAct && revisionComment !== null && (
        <form className="revision-form" onSubmit={(event) => { event.preventDefault(); void submit('revise') }}>
          <label htmlFor="revision-comment">What should change?</label>
          <textarea id="revision-comment" className="input-surface" rows={3} maxLength={2000} required
            value={revisionComment} onChange={(event) => setRevisionComment(event.target.value)} />
          <div className="actions">
            <button className="primary" disabled={!revisionComment.trim()}>Submit revision request</button>
            <button type="button" onClick={() => setRevisionComment(null)}>Cancel</button>
          </div>
        </form>
      )}
      {state.status === 'retry' && (
        <button onClick={() => submit(state.decision)}>Retry {decisionLabels[state.decision]}</button>
      )}
      {state.status === 'sending' && <p role="status">Sending decision…</p>}
      {state.status === 'submitted' && <p role="status">
        {state.decision === 'reject' ? 'Rejection submitted. Waiting for the final run status…'
          : 'Approval submitted. Waiting for the run to resume…'}
      </p>}
    </section>
  )
}

function ReviewArtifact({ reference, client, runId, onView }) {
  const { result, retry } = useArtifact(client, runId, reference)
  return (
    <div className="review-artifact">
      <div className="section-heading">
        <h3>{reference.title}</h3>
        <button type="button" onClick={() => onView(reference.artifact_id)}>View artifact</button>
      </div>
      <p className="muted">Artifact revision <code>{reference.artifact_id}</code></p>
      <h4>Assumptions under review</h4>
      {!result && <p role="status">Loading assumptions…</p>}
      {result?.error && <p className="muted">Assumptions could not be loaded. <button onClick={retry}>Retry</button></p>}
      {result?.artifact && <Assumptions entries={readEvidence(result.artifact.content).assumptions} />}
    </div>
  )
}
