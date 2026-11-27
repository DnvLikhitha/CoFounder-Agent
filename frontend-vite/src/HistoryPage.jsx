import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Status } from './AgentProgressTracker.jsx'

const initial = { runs: [], cursor: null, loading: true, error: '' }
const date = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

export function HistoryPage({ client }) {
  const [state, setState] = useState(initial)
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
      if (!request.signal.aborted) setState((previous) => ({ ...previous, loading: false, error: error.message }))
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

  return (
    <main className="page narrow">
      <header className="page-heading"><h1>Run history</h1><p>Open a run to see its progress and outputs.</p></header>
      {state.error && (
        <div className="notice error"><p role="alert">{state.error}</p><button onClick={() => load(state.cursor)}>Retry</button></div>
      )}
      <ul className="history-list">
        {state.runs.map((run) => (
          <li key={run.run_id}>
            <Link className="panel history-item" to={`/run/${encodeURIComponent(run.run_id)}`}>
              <div><strong>{run.input.problem}</strong>
                <time dateTime={run.created_at}>{date.format(new Date(run.created_at))}</time></div>
              <Status status={run.status} />
            </Link>
          </li>
        ))}
      </ul>
      {!state.runs.length && !state.loading && !state.error && <p>No runs yet. <Link to="/">Start a run</Link></p>}
      {state.loading && <p role="status">Loading runs…</p>}
      {state.cursor !== null && !state.loading && !state.error && <button onClick={() => load(state.cursor)}>Load more</button>}
    </main>
  )
}
