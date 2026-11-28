import { useEffect, useRef, useState } from 'react'
import { ArtifactContent } from './ArtifactContent.jsx'
import { Assumptions } from './OutputSection.jsx'
import { readEvidence, revisionLabel } from './lib/artifact-details.js'
import { useArtifact } from './lib/use-artifact.js'

const decisionLabels = {
  approve: 'approval',
  reject: 'rejection',
  revise: 'revision request',
}

export function FounderReview({ review, artifacts, client, runId, onStale, onViewArtifact }) {
  const pending = useRef(null)
  const submission = useRef(null)
  const [state, setState] = useState({ status: 'idle' })
  const [revisionComment, setRevisionComment] = useState(null)
  const [pricingDraft, setPricingDraft] = useState(null)
  const pricingReview = review.revision_kind === 'pricing'
  const pricingRef = pricingReview ? artifacts.find((item) => item.artifact_id === review.artifact_ids[0]) : null
  const pricing = useArtifact(client, runId, pricingRef)
  const tiers = Array.isArray(pricing.result?.artifact?.content?.tiers) ? pricing.result.artifact.content.tiers : []
  useEffect(() => () => pending.current?.abort(), [])

  function chooseTier(name) {
    const tier = tiers.find((item) => item.tier_name === name)
    if (tier) setPricingDraft({
      tier_name: tier.tier_name,
      price_monthly_usd: String(tier.price_monthly_usd),
      price_annual_usd: String(tier.price_annual_usd),
    })
  }

  async function submit(decision) {
    if (pending.current) return
    const revisingPrices = decision === 'revise' && pricingReview
    const edit = revisingPrices ? {
      tier_name: pricingDraft.tier_name,
      price_monthly_usd: Number(pricingDraft.price_monthly_usd),
      price_annual_usd: Number(pricingDraft.price_annual_usd),
    } : null
    if (edit && !submission.current) {
      const tier = tiers.find(({ tier_name }) => tier_name === edit.tier_name)
      if (tier && tier.price_monthly_usd === edit.price_monthly_usd && tier.price_annual_usd === edit.price_annual_usd) {
        setState({ status: 'idle', error: 'Change at least one price before saving a revision.' })
        return
      }
    }
    const payload = submission.current ?? {
      decision_id: crypto.randomUUID(),
      decision,
      comment: decision === 'revise' ? revisionComment.trim() || null : null,
      ...(edit ? { pricing_revision: edit } : {}),
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
      setState({ status: 'submitted', decision })
    } catch (error) {
      if (request.signal.aborted) return
      if (error.status === 409) {
        onStale()
        return
      }
      if ([401, 403, 404].includes(error.status)) {
        setState({ status: 'denied', error: error.message })
        return
      }
      const retryable = error.status == null || error.status === 429 || error.status >= 500 && error.retryable !== false
      if (!retryable) submission.current = null
      setState({ status: retryable ? 'retry' : 'idle', error: error.message, decision })
    } finally {
      pending.current = null
    }
  }

  const revisions = review.artifact_ids.map((id) => ({ id, reference: artifacts.find((item) => item.artifact_id === id) }))
  const canAct = state.status === 'idle' &&
    revisions.every(({ reference }) => reference) && (!pricingReview || Boolean(pricing.result?.artifact))
  const canRevise = pricingReview && tiers.length > 0
  return (
    <section className="panel review" aria-labelledby="review-heading">
      <h2 id="review-heading">Review required</h2>
      <p>{review.prompt}</p>
      <p className="muted">{pricingReview ? 'Pricing checkpoint' : 'Founder checkpoint'} <code>{review.review_id}</code></p>
      {revisions.length === 0 && <p className="muted">This checkpoint has no linked artifact revision.</p>}
      {revisions.map(({ id, reference }) => reference ? (
        <ReviewArtifact key={id} reference={reference} client={client} runId={runId} onView={onViewArtifact}
          pricing={id === pricingRef?.artifact_id ? pricing : null} />
      ) : <p key={id} className="muted">Artifact revision <code>{id}</code> is unavailable.</p>)}
      {state.error && <p className="notice error" role="alert">{state.error}</p>}
      {canAct && revisionComment === null && (
        <div className="actions">
          <button className="primary" onClick={() => submit('approve')}>Approve</button>
          <button onClick={() => submit('reject')}>Reject</button>
          {canRevise && <button onClick={() => {
            chooseTier(tiers[0].tier_name)
            setRevisionComment('')
          }}>Revise pricing</button>}
        </div>
      )}
      {canAct && revisionComment !== null && (
        <form className="revision-form" onSubmit={(event) => { event.preventDefault(); void submit('revise') }}>
          {pricingDraft && (
            <>
              <label htmlFor="revision-tier">Pricing tier</label>
              <select id="revision-tier" className="input-surface" value={pricingDraft.tier_name}
                onChange={(event) => chooseTier(event.target.value)}>
                {tiers.map((tier) => <option key={tier.tier_name}>{tier.tier_name}</option>)}
              </select>
              {[['price_monthly_usd', 'Monthly price (USD)'], ['price_annual_usd', 'Annual price (USD)']].map(([key, label]) => (
                <label key={key}>{label}
                  <input className="input-surface" type="number" min="0" step="any" required value={pricingDraft[key]}
                    onChange={(event) => setPricingDraft({ ...pricingDraft, [key]: event.target.value })} />
                </label>
              ))}
            </>
          )}
          <label htmlFor="revision-comment">Reason for the change (optional)</label>
          <textarea id="revision-comment" className="input-surface" rows={3} maxLength={2000}
            value={revisionComment} onChange={(event) => setRevisionComment(event.target.value)} />
          <div className="actions">
            <button className="primary">
              Save revision for approval
            </button>
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
          : state.decision === 'revise' ? 'Revision submitted. Waiting for the new checkpoint…'
            : 'Approval submitted. Waiting for the run to resume…'}
      </p>}
    </section>
  )
}

function ReviewArtifact({ reference, client, runId, onView, pricing }) {
  const details = useArtifact(client, runId, pricing ? null : reference)
  const { result, retry } = pricing ?? details
  return (
    <div className="review-artifact">
      <div className="section-heading">
        <h3>{reference.title}</h3>
        <button type="button" onClick={() => onView(reference.artifact_id)}>View artifact</button>
      </div>
      <p className="muted">{revisionLabel(reference)}{reference.revision && <> · <code>{reference.artifact_id}</code></>}</p>
      <h4>Assumptions under review</h4>
      {!result && <p role="status">Loading assumptions…</p>}
      {result?.error && <p className="muted">Assumptions could not be loaded. <button onClick={retry}>Retry</button></p>}
      {result?.artifact && (pricing
        ? <ArtifactContent reference={reference} content={result.artifact.content} />
        : <Assumptions entries={readEvidence(result.artifact.content).assumptions} />)}
    </div>
  )
}
