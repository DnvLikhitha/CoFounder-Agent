import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { fullAgentFixtures } from '../src/fixtures/full-agent-runs.js'
import { applyFrame, toFrame } from '../src/lib/run-state.js'

const idp = 'https://browser-test.supabase.co'
const fixture = fullAgentFixtures['full-succeeded']
const runId = fixture.snapshot.run_id
const runPath = `/api/v1/runs/${runId}`
const owner = 'founder@example.test'
const other = 'other@example.test'
const cors = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
}
let server, origin, browser

before(async () => {
  process.env.VITE_SUPABASE_URL = idp
  process.env.VITE_SUPABASE_PUBLISHABLE_KEY = 'sb_publishable_browser-test'
  delete process.env.VITE_SUPABASE_ANON_KEY
  const root = fileURLToPath(new URL('..', import.meta.url))
  server = await createServer({ root, mode: 'live', server: { host: '127.0.0.1', port: 0 } })
  await server.listen()
  origin = `http://127.0.0.1:${server.httpServer.address().port}`
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHROMIUM_CHANNEL })
})

after(async () => {
  await browser?.close()
  await server?.close()
})

function wire(events) {
  return events.map(({ event_id, type, ...rest }) =>
    `id: ${event_id}\nevent: ${type}\ndata: ${JSON.stringify({ event_id, type, ...rest })}\n\n`).join('')
}

function accessToken(email, generation, expiresAt) {
  const encode = (value) => Buffer.from(JSON.stringify(value)).toString('base64url')
  return `${encode({ alg: 'ES256' })}.${encode({ sub: email, generation, exp: expiresAt })}.dGVzdA`
}

async function setup(t) {
  const page = await browser.newPage()
  page.setDefaultTimeout(10000)
  t.after(() => page.context().close())
  const state = { calls: [], streams: [], submissions: [], refreshed: 0, logouts: 0 }
  const accepted = new Map()
  const revisions = new Map(fixture.artifacts.map((artifact) => [artifact.reference.artifact_id, artifact]))
  let snapshot = fixture.snapshot
  const withInput = (run) => ({ ...run, input: snapshot.input })

  function issue(email, generation) {
    const expires_in = state.shortLived && generation === 1 ? 10 : 3600
    const expires_at = Math.floor(Date.now() / 1000) + expires_in
    const access_token = accessToken(email, generation, expires_at)
    accepted.set(access_token, { email, generation })
    return { access_token, refresh_token: `refresh-${email}-${generation}`, token_type: 'bearer', expires_in, expires_at,
      user: { id: email, email, aud: 'authenticated', role: 'authenticated', app_metadata: {}, user_metadata: {} } }
  }

  await page.route(`${idp}/auth/v1/**`, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const headers = { ...cors, 'content-type': 'application/json' }
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (url.pathname.endsWith('/logout')) {
      state.logouts += 1
      return route.fulfill({ status: 204, headers })
    }
    if (url.searchParams.get('grant_type') === 'password') {
      const { email, password } = request.postDataJSON()
      if (![owner, other].includes(email) || password !== 'synthetic-password') {
        return route.fulfill({ status: 400, headers, json: { code: 'invalid_credentials', msg: 'Invalid login' } })
      }
      return route.fulfill({ headers, json: issue(email, 1) })
    }
    if (url.searchParams.get('grant_type') === 'refresh_token') {
      state.refreshed += 1
      const { refresh_token } = request.postDataJSON()
      if (state.expired || refresh_token !== `refresh-${owner}-1`) {
        return route.fulfill({ status: 400, headers, json: { code: 'refresh_token_not_found', msg: 'Expired session' } })
      }
      return route.fulfill({ headers, json: issue(owner, 2) })
    }
    return route.fulfill({ status: 404, headers, json: {} })
  })

  await page.route(/\/api\/v1\/runs(?:[/?]|$)/, async (route) => {
    const request = route.request()
    const { pathname, searchParams } = new URL(request.url())
    const authorization = request.headers().authorization
    const identity = accepted.get(authorization?.slice(7))
    state.calls.push({ pathname, identity, query: [...searchParams.keys()] })
    if (!identity) return route.fulfill({ status: 401 })
    if (pathname === '/api/v1/runs') {
      if (request.method() === 'POST') {
        const input = request.postDataJSON()
        state.submissions.push({ input, key: request.headers()['idempotency-key'] })
        snapshot = { ...fixture.snapshot, input }
        return route.fulfill({ status: 202, json: snapshot })
      }
      if (state.historyStatus) return route.fulfill({ status: state.historyStatus })
      const runs = identity.email === owner && state.submissions.length ? [snapshot] : []
      return route.fulfill({ json: { runs, next_cursor: null } })
    }
    if (identity.email === other) {
      return route.fulfill({ status: 404, json: { error: { message: 'Run not found' } } })
    }
    if (pathname === runPath) return route.fulfill({ json: snapshot })
    if (pathname === `${runPath}/events`) {
      const cursor = Number(searchParams.get('after'))
      state.streams.push({ cursor, generation: identity.generation })
      const headers = { 'content-type': 'text/event-stream' }
      if (cursor === 0) {
        const [first] = fixture.events
        snapshot = applyFrame(snapshot, toFrame(first))
        return route.fulfill({ headers, body: wire([first]) })
      }
      if (identity.generation === 1) return route.fulfill({ status: 401 })
      snapshot = withInput(fixture.final)
      return route.fulfill({ headers, body: wire(fixture.events.slice(cursor)) })
    }
    if (pathname.startsWith(`${runPath}/artifacts/`)) {
      const artifact = revisions.get(pathname.split('/').at(-1))
      return route.fulfill({ json: artifact })
    }
    if (pathname.startsWith(`${runPath}/exports/`)) {
      const format = pathname.split('/').at(-1)
      const files = {
        markdown: ['md', 'text/markdown', '# Verified plan'],
        pdf: ['pdf', 'application/pdf', '%PDF-1.7\n'],
        pptx: ['pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation', 'PK\u0003\u0004fixture'],
      }
      const [extension, type, body] = files[format]
      return route.fulfill({
        body, headers: { 'content-type': type, 'content-disposition': `attachment; filename="test-plan.${extension}"` },
      })
    }
    return route.fulfill({ status: 404 })
  })

  return { page, state }
}

async function signIn(page, email = owner, password = 'synthetic-password') {
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
}

async function download(page, button, filename) {
  const [file] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: button, exact: true }).click()])
  assert.equal(file.suggestedFilename(), filename)
  return readFile(await file.path(), 'utf8')
}

test('sign-in, protected routes, run submission, authenticated SSE renewal, reload and downloads', { timeout: 60000 }, async (t) => {
  const { page, state } = await setup(t)
  await page.goto(`${origin}/history`)
  await page.waitForURL('**/sign-in')
  await page.getByRole('heading', { name: 'Sign in to CoFounder Agent' }).waitFor()
  assert.equal(state.calls.length, 0)
  await signIn(page, owner, 'incorrect')
  await page.getByRole('alert').getByText('Check your email and password and try again.').waitFor()
  await signIn(page)
  await page.waitForURL('**/history')
  await page.getByText('No runs yet.', { exact: false }).waitFor()
  await page.getByRole('link', { name: 'New run' }).click()

  const problem = 'Help commuter students find internships that match their schedules.'
  await page.getByLabel('What problem are you solving?').fill(problem)
  await page.getByRole('button', { name: 'Generate startup plan' }).click()
  await page.waitForURL(`**/run/${runId}`)
  await page.getByText('16 available', { exact: true }).waitFor()
  assert.equal(state.submissions.length, 1)
  assert.equal(state.submissions[0].input.problem, problem)
  assert.match(state.submissions[0].key, /^[0-9a-f-]{36}$/)
  assert.equal(state.refreshed, 1)
  assert.deepEqual(state.streams, [{ cursor: 0, generation: 1 }, { cursor: 1, generation: 1 }, { cursor: 1, generation: 2 }])

  await page.reload()
  await page.getByRole('heading', { name: problem }).waitFor()
  await page.getByRole('button', { name: 'Download artifact' }).waitFor()
  const reference = fixture.artifacts[0].reference
  assert.deepEqual(JSON.parse(await download(page, 'Download artifact', `${reference.artifact_id}.json`)), fixture.artifacts[0].content)
  assert.equal(await download(page, 'Markdown', 'test-plan.md'), '# Verified plan')
  assert.match(await download(page, 'PDF', 'test-plan.pdf'), /^%PDF-/)
  assert.equal(await download(page, 'PowerPoint', 'test-plan.pptx'), 'PK\u0003\u0004fixture')
  const protectedDownloads = state.calls.filter(({ pathname }) => /\/(artifacts|exports)\//.test(pathname))
  assert.ok(protectedDownloads.some(({ pathname }) => pathname.endsWith(`/artifacts/${reference.artifact_id}`)))
  assert.equal(protectedDownloads.filter(({ pathname }) => pathname.includes('/exports/')).length, 3)
  assert.ok(protectedDownloads.every(({ identity }) => identity?.generation === 2))
  assert.ok(state.calls.every(({ identity, query }) => identity && query.every((key) => ['limit', 'after'].includes(key))))

  await page.getByRole('link', { name: 'History', exact: true }).click()
  await page.getByRole('link').filter({ hasText: problem }).waitFor()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await page.waitForURL('**/sign-in')
  assert.equal(state.logouts, 1)
  await page.reload()
  await page.getByRole('heading', { name: 'Sign in to CoFounder Agent' }).waitFor()
  await signIn(page, other)
  await page.getByRole('link', { name: 'History', exact: true }).click()
  await page.getByText('No runs yet.', { exact: false }).waitFor()
  await page.goto(`${origin}/run/${runId}`)
  await page.getByRole('alert').getByText('Run not found').waitFor()
  assert.equal(await page.getByRole('heading', { name: problem }).count(), 0)
})

test('a near-expiry Supabase session renews before the API needs to reject it', { timeout: 60000 }, async (t) => {
  const { page, state } = await setup(t)
  state.shortLived = true
  await page.goto(`${origin}/history`)
  await signIn(page)
  await page.getByText('No runs yet.', { exact: false }).waitFor()
  assert.equal(state.refreshed, 1)
  assert.ok(state.calls.length)
  assert.ok(state.calls.every(({ identity }) => identity?.generation === 2))
})

test('forbidden, rate-limited and unavailable requests retain the session, revoked refresh protects history', { timeout: 60000 }, async (t) => {
  const { page, state } = await setup(t)
  await page.goto(`${origin}/history`)
  state.historyStatus = 403
  await signIn(page)
  await page.getByRole('alert').getByText('You do not have permission to access this resource.').waitFor()
  state.historyStatus = 429
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await page.getByRole('alert').getByText('Too many requests. Wait before trying again.').waitFor()
  state.historyStatus = 503
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await page.getByRole('alert').getByText('The run API is unavailable. Try again shortly.').waitFor()
  assert.equal(state.refreshed, 0)
  assert.equal(await page.getByRole('button', { name: 'Sign out' }).count(), 1)

  state.expired = true
  state.historyStatus = 401
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await page.waitForURL('**/sign-in')
  await page.getByRole('alert').getByText('Your session expired or was rejected. Sign in again to continue.').waitFor()
  await page.reload()
  await page.getByRole('heading', { name: 'Sign in to CoFounder Agent' }).waitFor()
  assert.equal(state.refreshed, 1)
  assert.equal(await page.getByRole('heading', { name: 'Run history' }).count(), 0)
})
