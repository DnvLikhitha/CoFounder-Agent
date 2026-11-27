import { lazy, Suspense } from 'react'
import { BrowserRouter, Link, NavLink, Route, Routes } from 'react-router-dom'
import { HistoryPage } from './HistoryPage.jsx'
import { InputForm } from './InputForm.jsx'
import { client, mockMode } from './lib/index.js'

const RunRoute = lazy(() => import('./RunPage.jsx'))

export default function App() {
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
        </div>
      </header>
      <div id="main" tabIndex={-1}>
        <Routes>
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
        </Routes>
      </div>
    </BrowserRouter>
  )
}
