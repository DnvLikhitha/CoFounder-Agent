import { lazy, Suspense, useMemo, useState } from 'react'
import { BrowserRouter, Link, NavLink, Route, Routes } from 'react-router-dom'
import { HistoryPage } from './HistoryPage.jsx'
import { InputForm } from './InputForm.jsx'
import { mockClient, mockMode } from './lib/index.js'
import { createLiveClient } from './lib/live-client.js'

const RunRoute = lazy(() => import('./RunPage.jsx'))
const accessTokenKey = 'cofounder-vite.live-access-token'

export default function App() {
  const [accessToken, setAccessToken] = useState(() =>
    mockMode ? null : window.sessionStorage.getItem(accessTokenKey))
  const [sessionError, setSessionError] = useState('')
  const client = useMemo(() => {
    if (mockMode) return mockClient
    if (!accessToken) return null
    return createLiveClient(undefined, {
      accessToken,
      onUnauthorized() {
        if (window.sessionStorage.getItem(accessTokenKey) !== accessToken) return
        window.sessionStorage.removeItem(accessTokenKey)
        setAccessToken(null)
        setSessionError('The API session expired or was rejected. Enter a fresh access token.')
      },
    })
  }, [accessToken])

  function connect(event) {
    event.preventDefault()
    const token = new FormData(event.currentTarget).get('access-token').trim()
    if (!token) return
    window.sessionStorage.setItem(accessTokenKey, token)
    setSessionError('')
    setAccessToken(token)
  }

  function disconnect() {
    window.sessionStorage.removeItem(accessTokenKey)
    setSessionError('')
    setAccessToken(null)
  }

  return (
    <BrowserRouter>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="site-header">
        <div className="site-header-inner">
          <Link className="brand" to="/"><span aria-hidden="true">C</span> CoFounder Agent</Link>
          <nav aria-label="Main navigation">
            <NavLink end to="/">New run</NavLink>
            <NavLink to="/history">History</NavLink>
          </nav>
          <span className="mode">{mockMode ? 'Mock mode' : 'Live API'}</span>
          {!mockMode && client && <button type="button" onClick={disconnect}>Disconnect API</button>}
        </div>
      </header>
      <div id="main" tabIndex={-1}>
        {client ? <Routes>
          <Route path="/" element={
            <main className="page narrow">
              <header className="page-heading">
                <h1>Build a startup plan</h1>
                <p>Describe the problem and follow the agents as they research and draft your plan.</p>
              </header>
              <InputForm client={client} mockMode={mockMode} />
            </main>
          } />
          <Route path="/history" element={<HistoryPage client={client} />} />
          <Route path="/run/:runId" element={
            <Suspense fallback={<main className="page narrow"><p role="status">Loading run…</p></main>}>
              <RunRoute client={client} />
            </Suspense>
          } />
          <Route path="*" element={
            <main className="page narrow"><h1>Page not found</h1><Link to="/">Start a run</Link></main>
          } />
        </Routes> : (
          <main className="page narrow">
            <header className="page-heading">
              <h1>Connect to the run API</h1>
              <p>Enter a short-lived access token issued for this API.</p>
            </header>
            <form className="panel" onSubmit={connect}>
              {sessionError && <p className="notice error" role="alert">{sessionError}</p>}
              <label htmlFor="access-token">API access token</label>
              <input className="input-surface" id="access-token" name="access-token"
                type="password" autoComplete="off" spellCheck={false} required />
              <p><button type="submit" className="primary">Connect</button></p>
            </form>
          </main>
        )}
      </div>
    </BrowserRouter>
  )
}
