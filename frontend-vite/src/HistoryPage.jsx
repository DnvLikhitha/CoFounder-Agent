import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Status } from './AgentProgressTracker.jsx'

const initial = { runs: [], cursor: null, loading: true, error: '' }
const date = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

export function HistoryPage({ client }) {
  const [state, setState] = useState(initial)
  const [search, setSearch] = useState('')
  const pending = useRef(null)
  const load = useCallback(async (cursor) => {
    if (pending.current) return
    const request = new AbortController()
    pending.current = request
    setState((previous) => ({ ...previous, loading: true, error: '' }))
    try {
      const { runs, next_cursor } = await client.listRuns({ cursor, signal: request.signal })
      if (!request.signal.aborted) {
        setState((previous) => {
          const seen = new Set(previous.runs.map(({ run_id }) => run_id))
          return {
            runs: cursor === null ? runs : [...previous.runs, ...runs.filter(({ run_id }) => !seen.has(run_id))],
            cursor: next_cursor, loading: false, error: '',
          }
        })
      }
    } catch (error) {
      if (!request.signal.aborted) {
        const unavailable = [404, 405].includes(error.status)
        setState((previous) => ({
          ...previous, loading: false, unavailable,
          error: unavailable ? 'This API does not yet provide run history.' : error.message,
        }))
      }
    } finally {
      if (pending.current === request) pending.current = null
    }
  }, [client])

  useEffect(() => {
    void load(null)
    return () => {
      pending.current?.abort()
      pending.current = null
    }
  }, [load])

  const searchText = search.trim().toLowerCase()
  const visible = state.runs.filter(({ input }) => [input.problem, input.domain, input.geography]
    .some((value) => value?.toLowerCase().includes(searchText)))
  return (
    <main className="page narrow">
      <header className="page-heading section-heading">
        <div><h1>Run history</h1><p>Revisit startup plans and their results.</p></div>
        <Link to="/">Start a run</Link>
      </header>
      {state.error && (
        <div className="notice error">
          <p role="alert">{state.error}</p>
          {!state.unavailable && <button onClick={() => load(state.cursor)}>Retry</button>}
        </div>
      )}
      {state.runs.length > 0 && (
        <div className="history-filter">
          <label htmlFor="history-search">Filter loaded runs</label>
          <input className="input-surface" id="history-search" type="search" placeholder="Search by problem, industry, or location"
            value={search} onChange={(event) => setSearch(event.target.value)} />
        </div>
      )}
      <ul className="history-list">
        {visible.map((run) => (
          <li key={run.run_id}>
            <Link className="panel history-item" to={`/run/${encodeURIComponent(run.run_id)}`}>
              <div><strong>{run.input.problem}</strong>
                {(run.input.domain || run.input.geography) &&
                  <span className="history-context">{[run.input.domain, run.input.geography].filter(Boolean).join(' · ')}</span>}
                <time dateTime={run.created_at}>{date.format(new Date(run.created_at))}</time></div>
              <Status status={run.status} />
            </Link>
          </li>
        ))}
      </ul>
      {!state.runs.length && !state.loading && !state.error && <p>No runs yet. <Link to="/">Start a run</Link></p>}
      {state.runs.length > 0 && !visible.length && <p role="status">No loaded runs match your search.</p>}
      {state.loading && <p role="status">Loading runs…</p>}
      {state.cursor !== null && !state.loading && !state.error && <button onClick={() => load(state.cursor)}>Load more</button>}
    </main>
  )
}
