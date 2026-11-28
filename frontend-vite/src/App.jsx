import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { HistoryPage } from './HistoryPage.jsx'
import { InputForm } from './InputForm.jsx'
import { authConfig } from './lib/auth-config.js'
import { createLiveClient } from './lib/live-client.js'
import { authErrorMessage, createSessionAccess, expiredMessage } from './lib/session.js'

const RunRoute = lazy(() => import('./RunPage.jsx'))
const config = authConfig({
  VITE_SUPABASE_URL: import.meta.env.VITE_SUPABASE_URL,
  VITE_SUPABASE_PUBLISHABLE_KEY: import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY,
  VITE_SUPABASE_ANON_KEY: import.meta.env.VITE_SUPABASE_ANON_KEY,
})
const auth = config && (await import('@supabase/supabase-js')).createClient(config.url, config.key, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
}).auth

export default function App() {
  return (
    <BrowserRouter>
      <a className="skip-link" href="#main" onClick={(event) => {
        event.preventDefault()
        document.getElementById('main')?.focus()
      }}>Skip to content</a>
      {auth ? <LiveWorkspace /> : (
        <>
          <SiteHeader />
          <main id="main" tabIndex={-1} className="page narrow">
            <h1>Sign-in unavailable</h1>
            <p role="alert">The identity provider has not been configured for this environment.</p>
          </main>
        </>
      )}
    </BrowserRouter>
  )
}

function SiteHeader({ client, signOut, signingOut }) {
  return (
    <header className="site-header">
      <div className="site-header-inner">
        <Link className="brand" to="/"><span aria-hidden="true">C</span> CoFounder Agent</Link>
        {client && <nav aria-label="Main navigation">
          <NavLink end to="/">New run</NavLink>
          <NavLink to="/history">History</NavLink>
        </nav>}
        {signOut && <button type="button" disabled={signingOut} onClick={signOut}>Sign out</button>}
      </div>
    </header>
  )
}

function LiveWorkspace() {
  const [session, setSession] = useState({ ready: false, userId: null, expired: false })
  const [signingOut, setSigningOut] = useState(false)
  const [signOutError, setSignOutError] = useState('')
  const explicitSignOut = useRef(false)
  const location = useLocation()
  const navigate = useNavigate()
  const { ready, userId, expired } = session

  useEffect(() => {
    const { data: { subscription } } = auth.onAuthStateChange((event, next) => {
      const userId = next?.user.id ?? null
      const signedOut = event === 'SIGNED_OUT' && !explicitSignOut.current
      setSession((previous) => ({
        ready: true, userId,
        expired: !userId && (previous.expired || (signedOut && Boolean(previous.userId))),
      }))
    })
    return () => subscription.unsubscribe()
  }, [])

  const expire = useCallback(() => {
    setSession((previous) => previous.userId === userId
      ? { ready: true, userId: null, expired: true }
      : previous)
  }, [userId])
  const client = useMemo(() => userId
    ? createLiveClient(undefined, createSessionAccess(auth, userId, expire))
    : null, [userId, expire])

  async function signOut() {
    explicitSignOut.current = true
    setSigningOut(true)
    setSignOutError('')
    try {
      const { error } = await auth.signOut({ scope: 'local' })
      if (error) throw error
      navigate('/sign-in', { replace: true })
    } catch {
      setSignOutError('Sign-out could not be completed. Try again shortly.')
    } finally {
      explicitSignOut.current = false
      setSigningOut(false)
    }
  }

  if (client) {
    if (location.pathname === '/sign-in') {
      const from = location.state?.from
      const next = typeof from === 'string' && /^\/(?![/\\])/.test(from) ? from : '/'
      return <Navigate to={next} replace />
    }
    return <Workspace key={userId} client={client} signOut={signOut} signingOut={signingOut} error={signOutError} />
  }
  if (ready && location.pathname !== '/sign-in') {
    return <Navigate to="/sign-in" replace state={{ from: location.pathname + location.search + location.hash }} />
  }
  return (
    <>
      <SiteHeader />
      <main id="main" tabIndex={-1} className="page narrow">
        {ready ? <SignIn expired={expired} /> : <p role="status">Restoring your session…</p>}
      </main>
    </>
  )
}

function SignIn({ expired }) {
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState('')
  async function signIn(event) {
    event.preventDefault()
    const form = event.currentTarget
    const { email, password } = Object.fromEntries(new FormData(form))
    setPending(true)
    setMessage('')
    try {
      const { error } = await auth.signInWithPassword({ email: email.trim(), password })
      if (error) setMessage(authErrorMessage(error))
    } catch (error) {
      setMessage(authErrorMessage(error))
    } finally {
      form.elements.password.value = ''
      setPending(false)
    }
  }
  return (
    <>
      <header className="page-heading"><h1>Sign in to CoFounder Agent</h1></header>
      <form className="panel" onSubmit={signIn}>
        {(message || expired) && <p className="notice error" role="alert">{message || expiredMessage}</p>}
        <fieldset disabled={pending}>
          <label htmlFor="email">Email</label>
          <input className="input-surface" id="email" name="email" type="email" autoComplete="username" required />
          <label htmlFor="password">Password</label>
          <input className="input-surface" id="password" name="password" type="password" autoComplete="current-password" required />
          <p><button type="submit" className="primary">{pending ? 'Signing in…' : 'Sign in'}</button></p>
        </fieldset>
      </form>
    </>
  )
}

function Workspace({ client, signOut, signingOut, error }) {
  return (
    <>
      <SiteHeader client={client} signOut={signOut} signingOut={signingOut} />
      <div id="main" tabIndex={-1}>
        {error && <p className="notice error" role="alert">{error}</p>}
        <Routes>
          <Route path="/" element={
            <main className="page narrow">
              <header className="page-heading">
                <h1>Build a startup plan</h1>
                <p>Describe the problem and follow the agents as they research and draft your plan.</p>
              </header>
              <InputForm client={client} />
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
    </>
  )
}
