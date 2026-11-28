import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import revisedArtifacts from '../../shared/contracts/fixtures/revised/artifacts.json' with { type: 'json' }
import revisedStart from '../../shared/contracts/fixtures/revised/snapshot.json' with { type: 'json' }
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

async function setup(t, handleRun) {
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
    if (handleRun) return handleRun(route, identity)
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

async function setupPricingReview(t, decisionFailure) {
  const path = `/api/v1/runs/${revisedStart.run_id}`
  const eventFile = new URL('../../shared/contracts/fixtures/revised/events.jsonl', import.meta.url)
  const events = (await readFile(eventFile, 'utf8')).trim().split(/\r?\n/).map((line) => JSON.parse(line))
  Object.assign(events[4].data, {
    outcome: 'failed', score: null, reasons: ['Pricing validation failed.'],
    dimensions: [{ dimension: 'consistency', outcome: 'failed', reason: 'The draft pricing assumptions conflict.' }],
  })
  Object.assign(events[8].data, { method: 'llm', outcome: 'not_evaluated', score: null, dimensions: [],
    reasons: ['The optional judge did not finish.'] })
  Object.assign(events[23].data, { evidence: [
    { claim_path: '/arr_month_12_usd', artifact_id: 'pricing_strategy-r2', source_url: 'https://example.test/research',
      relationship: 'citation' },
  ] })
  const artifacts = new Map(revisedArtifacts.map((artifact) => [artifact.reference.artifact_id, structuredClone(artifact)]))
  Object.assign(artifacts.get('financial_projections-r2').content, {
    assumptions: { reviewed_price_usd: 50 },
    uncertainty: 'Renewal rates are unmeasured.',
    sources: [{ title: 'Research source', url: 'https://example.test/research' }],
  })
  let snapshot = revisedStart
  const waiting = new Set()
  const decisions = []
  const streamed = []
  function advance(cursor, notify = true) {
    snapshot = events.slice(snapshot.last_event_id, cursor).map(toFrame).reduce(applyFrame, snapshot)
    if (notify) {
      waiting.forEach((resolve) => resolve())
      waiting.clear()
    }
  }
  advance(12)
  const { page } = await setup(t, async (route, identity) => {
    const request = route.request()
    const { pathname, searchParams } = new URL(request.url())
    if (pathname === path) return route.fulfill({ json: snapshot })
    if (pathname === `${path}/events`) {
      const after = Number(searchParams.get('after'))
      if (after >= snapshot.last_event_id) await new Promise((resolve) => waiting.add(resolve))
      const batch = events.slice(after, snapshot.last_event_id)
      streamed.push(...batch.map(({ event_id }) => event_id))
      return route.fulfill({ headers: { 'content-type': 'text/event-stream' }, body: wire(batch) }).catch(() => {})
    }
    if (pathname.startsWith(`${path}/artifacts/`)) return route.fulfill({ json: artifacts.get(pathname.split('/').at(-1)) })
    if (request.method() === 'POST' && pathname.endsWith('/decisions')) {
      const decision = request.postDataJSON()
      decisions.push({ reviewId: pathname.split('/').at(-2), decision, owner: identity.email })
      if (decisionFailure) {
        if (decisionFailure === 409) advance(16, false)
        return route.fulfill({ status: decisionFailure })
      }
      const receipt = events[snapshot.last_event_id].data
      receipt.decision = decision
      advance(decision.decision === 'revise' ? 16 : 20)
      return route.fulfill({ json: receipt })
    }
    return route.fulfill({ status: 404 })
  })
  const initialStream = page.waitForRequest((request) => request.url().includes(`${path}/events?after=12`))
  await page.goto(`${origin}/run/${revisedStart.run_id}`)
  await signIn(page)
  const review = page.getByRole('region', { name: 'Review required' })
  await review.getByRole('button', { name: 'Approve', exact: true }).waitFor()
  await initialStream
  return { page, review, decisions, streamed, finish: () => advance(25) }
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

test('pricing revision, evaluation evidence, and downstream regeneration follow SSE', { timeout: 60000 }, async (t) => {
  const { page, review, decisions, streamed, finish } = await setupPricingReview(t)
  const outputs = page.getByRole('region', { name: 'Run outputs' })
  const picker = page.getByLabel('Browse outputs')
  await outputs.getByText('The draft pricing assumptions conflict.').waitFor()
  await outputs.getByText('Pricing validation failed.').waitFor()
  await picker.selectOption('financial_projections')
  await outputs.getByText('No source references were supplied.').waitFor()
  await outputs.getByText('Not evaluated', { exact: true }).waitFor()
  await outputs.getByText('The optional judge did not finish.').waitFor()
  assert.equal(await outputs.getByText('Score unavailable').count(), 0)
  await outputs.getByText('This forecast is a draft pending pricing approval.').waitFor()

  await review.getByRole('button', { name: 'Revise pricing' }).click()
  await review.getByRole('button', { name: 'Save revision for approval' }).click()
  await review.getByRole('alert').getByText('Change at least one price before saving a revision.').waitFor()
  assert.equal(decisions.length, 0)
  await review.getByLabel('Monthly price (USD)').fill('50')
  await review.getByLabel('Annual price (USD)').fill('500')
  const revisedStream = page.waitForRequest('**/events?after=16')
  await review.getByRole('button', { name: 'Save revision for approval' }).click()
  await review.getByText('pricing-review-2').waitFor()
  await revisedStream
  assert.equal(decisions[0].reviewId, 'pricing-review-1')
  assert.equal(decisions[0].owner, owner)
  assert.deepEqual(decisions[0].decision.artifact_ids, ['pricing_strategy'])
  assert.deepEqual(decisions[0].decision.pricing_revision,
    { tier_name: 'Starter', price_monthly_usd: 50, price_annual_usd: 500 })

  await picker.selectOption('pricing_strategy-r2')
  await page.getByLabel('Compare with').selectOption('pricing_strategy')
  const comparison = page.getByRole('region', { name: 'Revision comparison' })
  await comparison.getByText('$30.00', { exact: true }).waitFor()
  await comparison.getByText('$50.00', { exact: true }).waitFor()

  const resumingStream = page.waitForRequest('**/events?after=20')
  await review.getByRole('button', { name: 'Approve', exact: true }).click()
  await outputs.getByText('Regenerating Financial Projections using updated inputs.').waitFor()
  assert.deepEqual(decisions[1].decision.artifact_ids, ['pricing_strategy-r2'])
  assert.equal(decisions[1].reviewId, 'pricing-review-2')
  await resumingStream
  finish()
  await page.getByText('Run updates complete').waitFor()
  assert.ok([13, 16, 17, 20, 22, 25].every((id) => streamed.includes(id)))

  await picker.selectOption('financial_projections-r2')
  await outputs.getByText('Regenerated using updated inputs.').waitFor()
  await outputs.getByRole('region', { name: 'Uncertainty and limitations' }).getByText('Renewal rates are unmeasured.').waitFor()
  await outputs.getByRole('region', { name: 'Assumptions' }).getByText('reviewed price usd').waitFor()
  assert.equal(await outputs.getByRole('link', { name: 'Research source' }).getAttribute('href'), 'https://example.test/research')
  await outputs.getByRole('button', { name: /View claim/ }).click()
  await outputs.getByRole('region', { name: 'Evidence claim' }).getByText('6000', { exact: true }).waitFor()
  await outputs.getByRole('button', { name: 'Pricing Strategy · Revision 2', exact: true }).last().click()
  assert.equal(await picker.inputValue(), 'pricing_strategy-r2')
})

test('stale decisions reload the replacement checkpoint before another action', { timeout: 60000 }, async (t) => {
  const { page, review, decisions } = await setupPricingReview(t, 409)
  await review.getByRole('button', { name: 'Approve', exact: true }).click()
  await page.getByText('This review changed. Check the current checkpoint before submitting again.').waitFor()
  await review.getByText('pricing-review-2').waitFor()
  await review.getByRole('button', { name: 'Approve', exact: true }).waitFor()
  assert.deepEqual(decisions.map(({ reviewId }) => reviewId), ['pricing-review-1'])
})

test('an unauthorized review decision leaves the checkpoint and removes decision controls', { timeout: 60000 }, async (t) => {
  const { review, decisions } = await setupPricingReview(t, 403)
  await review.getByRole('button', { name: 'Reject', exact: true }).click()
  await review.getByRole('alert').getByText('You do not have permission to access this resource.').waitFor()
  await review.getByText('pricing-review-1').waitFor()
  assert.equal(await review.getByRole('button', { name: 'Approve', exact: true }).count(), 0)
  assert.equal(decisions[0].decision.decision, 'reject')
})

test('sign-in, protected routes, run submission, authenticated SSE renewal, reload and downloads', { timeout: 60000 }, async (t) => {
  const { page, state } = await setup(t)
  await page.goto(`${origin}/history`)
  await page.waitForURL('**/sign-in')
  await page.getByRole('heading', { name: 'Sign in to CoFounder Agent' }).waitFor()
  assert.equal(state.calls.length, 0)
  const defaultPrevented = await page.getByRole('link', { name: 'Skip to content' }).evaluate((link) => {
    const main = link.ownerDocument.getElementById('main')
    main.removeAttribute('id')
    try {
      const click = new link.ownerDocument.defaultView.MouseEvent('click', { bubbles: true, cancelable: true })
      return !link.dispatchEvent(click)
    } finally {
      main.id = 'main'
    }
  })
  assert.ok(defaultPrevented)
  await page.keyboard.press('Tab')
  assert.equal(await page.locator(':focus').getAttribute('class'), 'skip-link')
  await page.keyboard.press('Enter')
  assert.equal(await page.locator(':focus').getAttribute('id'), 'main')
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
