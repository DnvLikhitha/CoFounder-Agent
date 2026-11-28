import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createSubmissionKeys } from './lib/submission.js'

const domains = ['General', 'SaaS', 'HealthTech', 'EdTech', 'FinTech', 'Marketplace', 'AI/ML', 'Consumer', 'B2B', 'Other']

export function InputForm({ client }) {
  const navigate = useNavigate()
  const pending = useRef(null)
  const [keys] = useState(createSubmissionKeys)
  const [problem, setProblem] = useState('')
  const [state, setState] = useState({ loading: false, error: '' })
  useEffect(() => () => pending.current?.abort(), [])

  async function submit(event) {
    event.preventDefault()
    if (pending.current) return
    const form = new FormData(event.currentTarget)
    const trimmed = problem.trim()
    if (trimmed.length < 10 || trimmed.length > 500) {
      setState({ loading: false, error: 'Enter a problem statement of 10 to 500 characters.' })
      return
    }

    const request = new AbortController()
    pending.current = request
    setState({ loading: true, error: '' })
    const input = {
      problem: trimmed,
      domain: form.get('domain') || null,
      geography: form.get('geography').trim() || null,
    }
    try {
      const { run_id } = await client.startRun(input, {
        signal: request.signal, idempotencyKey: keys.get(input),
      })
      if (!request.signal.aborted) {
        keys.reset()
        navigate(`/run/${encodeURIComponent(run_id)}`)
      }
    } catch (error) {
      if (!request.signal.aborted) {
        const uncertain = error.status == null || error.status >= 500
        setState({ loading: false, error: error.message, uncertain })
      }
    } finally {
      pending.current = null
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <fieldset disabled={state.loading}>
        <label htmlFor="problem">What problem are you solving?</label>
        <textarea
          className="input-surface" id="problem" value={problem} rows={5} required maxLength={500}
          aria-describedby="problem-guide problem-length"
          placeholder="For example, students struggle to find internships that match their skills."
          onChange={(event) => setProblem(event.target.value)}
        />
        <p id="problem-guide" className="field-help muted">Include who has the problem and how they handle it today.</p>
        <div className="field-hint" id="problem-length">
          <span>10–500 characters</span><span>{problem.length}/500</span>
        </div>
        <div className="field-row">
          <div>
            <label htmlFor="domain">Industry <span>(optional)</span></label>
            <select className="input-surface" id="domain" name="domain">
              {domains.map((domain) => (
                <option key={domain} value={domain === 'General' ? '' : domain}>{domain}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="geography">Target geography <span>(optional)</span></label>
            <input className="input-surface" id="geography" name="geography" maxLength={100} placeholder="For example, India" />
          </div>
        </div>
        {state.error && <p className="notice error" role="alert">{state.error}</p>}
        {state.uncertain && <p className="muted">Retry the same input to recover the existing submission if it was accepted.</p>}
        <div className="actions submission-actions">
          <button className="primary start-button">{state.loading ? 'Starting…' : state.uncertain ? 'Retry submission' : 'Generate startup plan'}</button>
          {state.uncertain && (
            <button type="button" onClick={() => {
              keys.reset()
              setState({ loading: false, error: '' })
            }}>Start a new submission</button>
          )}
        </div>
      </fieldset>
    </form>
  )
}
