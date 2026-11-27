import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

const domains = ['General', 'SaaS', 'HealthTech', 'EdTech', 'FinTech', 'Marketplace', 'AI/ML', 'Consumer', 'B2B', 'Other']

export function InputForm({ client, mockMode }) {
  const navigate = useNavigate()
  const pending = useRef(null)
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
    try {
      const { run_id } = await client.startRun({
        problem: trimmed,
        domain: form.get('domain') || null,
        geography: form.get('geography').trim() || null,
      }, { signal: request.signal, scenario: form.get('scenario') ?? undefined })
      if (!request.signal.aborted) navigate(`/run/${encodeURIComponent(run_id)}`)
    } catch (error) {
      if (!request.signal.aborted) setState({ loading: false, error: error.message })
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
          aria-describedby="problem-length"
          placeholder="For example, students struggle to find internships that match their skills."
          onChange={(event) => setProblem(event.target.value)}
        />
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
        {mockMode && (
          <div className="scenario">
            <label htmlFor="scenario">Mock scenario</label>
            <select className="input-surface" name="scenario" id="scenario">
              <option value="succeeded">Success after review</option>
              <option value="partial">Partial results after review</option>
            </select>
          </div>
        )}
        {state.error && <p className="notice error" role="alert">{state.error}</p>}
        <button className="primary start-button">{state.loading ? 'Starting…' : 'Generate startup plan'}</button>
      </fieldset>
    </form>
  )
}
