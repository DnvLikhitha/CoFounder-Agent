import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import { fullAgentFixtures } from '../src/fixtures/full-agent-runs.js'
import { createLiveClient } from '../src/lib/live-client.js'
import { createMockClient } from '../src/lib/mock-client.js'
import { summarizeProgress } from '../src/lib/run-progress.js'
import { applyFrame, checkArtifact, checkSnapshot, ProtocolError, toFrame } from '../src/lib/run-state.js'
import { createSubmissionKeys } from '../src/lib/submission.js'
import { watchRun } from '../src/lib/watch-run.js'

const success = fullAgentFixtures['full-succeeded']
const partial = fullAgentFixtures['full-partial']
const fixtureStatus = (fixture, cursor) => fixture.events.slice(0, cursor).map(toFrame).reduce(applyFrame, fixture.snapshot)
const output = (kind) => success.artifacts.find((item) => item.reference.kind === kind)
const markup = (component, props) => renderToStaticMarkup(createElement(component, props))
let vite, ArtifactContent, OutputSection, Evaluations, ProgressOverview, AgentProgressTracker

before(async () => {
  vite = await createServer({ appType: 'custom', server: { middlewareMode: true, ws: false } })
  ArtifactContent = (await vite.ssrLoadModule('/src/ArtifactContent.jsx')).ArtifactContent
  const outputs = await vite.ssrLoadModule('/src/OutputSection.jsx')
  OutputSection = outputs.OutputSection
  Evaluations = outputs.Evaluations
  const tracker = await vite.ssrLoadModule('/src/AgentProgressTracker.jsx')
  ProgressOverview = tracker.ProgressOverview
  AgentProgressTracker = tracker.AgentProgressTracker
})

after(async () => { await vite?.close() })

test('all sixteen artifacts validate and render their actual agent output fields', () => {
  const expected = {
    problem_refined: /Campus career teams cannot reliably route/,
    startup_idea: /Find internships within reach/,
    market_research: /Total addressable market \(TAM\)/,
    competitor_analysis: /Competitor comparison/,
    customer_personas: /Commuter student/,
    product_design: /Commute filters/,
    mvp_roadmap: /Campus search prototype/,
    business_model: /Campus subscriptions/,
    pricing_strategy: /Pricing tiers/,
    financial_projections: /Monthly projections/,
    risk_register: /Stale listings/,
    tech_architecture: /PostgreSQL/,
    database_schema: /CREATE TABLE listings/,
    security_compliance: /Managed sign-in/,
    pitch_deck: /Pitch deck preview/,
    executive_summary: /Make local internship opportunities easier to discover/,
  }
  assert.deepEqual(success.artifacts.map(({ reference }) => reference.kind).sort(), Object.keys(expected).sort())
  for (const artifact of success.artifacts) {
    checkArtifact(artifact, success.final.run_id, artifact.reference)
    assert.match(markup(ArtifactContent, artifact), expected[artifact.reference.kind], artifact.reference.kind)
  }
  const market = markup(ArtifactContent, output('market_research'))
  assert.match(market, /Serviceable available market \(SAM\)/)
  assert.match(market, /Serviceable obtainable market \(SOM\)/)
  assert.doesNotMatch(market, /Compound annual growth rate/)
})

test('evaluation overview displays every step, run-wide, and unassigned result once', () => {
  const steps = success.final.manifest.steps.slice(0, 2)
  const [first] = success.final.evaluations
  const evaluations = [
    { ...first, step_id: steps[0].step_id, reasons: ['Step result'] },
    { ...first, evaluation_id: 'run-evaluation', step_id: null, artifact_id: null, reasons: ['Run-wide result'] },
    { ...first, evaluation_id: 'unassigned-evaluation', step_id: 'retired-step', reasons: ['Unassigned result'] },
  ]
  const html = markup(Evaluations, { evaluations, steps, artifacts: success.final.artifacts })
  assert.match(html, /Step result[\s\S]*Run-wide and unassigned evaluations[\s\S]*Run-level evaluation[\s\S]*Run-wide result[\s\S]*Unassigned result/)
  for (const { reasons: [reason] } of evaluations) assert.equal(html.split(reason).length - 1, 1)
})

test('finance and deck components show supplied values and handle missing fields or slides', () => {
  const finance = markup(ArtifactContent, output('financial_projections'))
  assert.match(finance, /Revenue and net profit by month/)
  assert.match(finance, /-\$2,200\.00/)
  assert.match(finance, /\$0\.00/)
  assert.match(finance, /Not supplied/)
  assert.doesNotMatch(finance, /Month 12 annual recurring revenue/)
  assert.equal(finance.match(/class="chart-bar/g).length, 5)
  const missing = markup(ArtifactContent, { reference: output('financial_projections').reference, content: {
    monthly_projections: [{ month: 1, net_profit_usd: null }],
  } })
  assert.match(missing, /No monthly revenue or profit values/)
  assert.doesNotMatch(missing, /\$0\.00/)
  const deck = markup(ArtifactContent, output('pitch_deck'))
  assert.match(deck, /Slide 1 of 2/)
  assert.match(deck, /Previous slide/)
  assert.match(deck, /Next slide/)
  assert.match(deck, /Introduce the campus pilot/)
  assert.match(markup(ArtifactContent, { reference: output('pitch_deck').reference, content: { slides: [] } }),
    /No pitch deck slides were supplied/)
})

test('unknown artifact kinds safely render nested structured data', () => {
  const html = markup(ArtifactContent, {
    reference: { kind: 'future_report', media_type: 'application/json' },
    content: { future_section: { count: 0, enabled: false, tag: '<script>alert(1)</script>' } },
  })
  assert.match(html, /Future section/)
  assert.match(html, />0</)
  assert.match(html, />No</)
  assert.match(html, /&lt;script&gt;/)
  assert.doesNotMatch(html, /<script>/)
  const future = { ...success.snapshot.manifest.steps[0], step_id: 'future', label: 'Future agent',
    order: 42, artifact_kinds: ['future_report'] }
  const state = { ...success.snapshot.steps[0], step_id: 'future' }
  const progress = summarizeProgress({ steps: [future] }, [state])
  assert.match(markup(ProgressOverview, { progress }), /0 of 1 steps finished/)
  const pipeline = markup(AgentProgressTracker, { steps: progress.steps, artifacts: [], runStatus: 'queued' })
  assert.match(pipeline, /Future agent/)
})

test('dashboard derives concurrent, completed, failed and blocked agents from the manifest', () => {
  let snapshot = success.snapshot
  const concurrent = success.events.some((event) => {
    snapshot = applyFrame(snapshot, toFrame(event))
    return snapshot.steps.filter(({ status }) => status === 'running').length === 3
  })
  assert.equal(concurrent, true)
  const progress = summarizeProgress(snapshot.manifest, [...snapshot.steps].reverse())
  assert.equal(progress.running.length, 3)
  const overview = markup(ProgressOverview, { progress })
  assert.match(overview, /Market Research, Competitor Analysis, Customer Personas/)
  assert.match(overview, /2 of 16 steps finished/)

  const state = checkSnapshot(partial.final, partial.snapshot.run_id)
  const terminal = summarizeProgress(state.manifest, state.steps)
  assert.equal(terminal.settled, 16)
  assert.equal(terminal.failed, 1)
  assert.equal(terminal.partial, 1)
  assert.equal(terminal.completed, 13)
  assert.equal(terminal.blocked[0].step_id, 'financial_projections')
  const pipeline = markup(AgentProgressTracker, { steps: terminal.steps, artifacts: state.artifacts, runStatus: state.status })
  assert.match(pipeline, /Blocked by Pricing Strategy/)
  assert.match(pipeline, /Pricing did not complete/)
  const results = markup(OutputSection, { artifacts: state.artifacts, evaluations: state.evaluations,
    steps: terminal.steps, status: state.status, activeId: 'missing:financial_projections:financial_projections' })
  assert.match(results, /14 available/)
  assert.match(results, /No artifact was published for this output/)
  assert.match(results, /Pricing is required for financial projections/)
})

test('full workflow reconnect uses the refreshed cursor and ignores duplicate replay', async () => {
  let loads = 0
  const attempts = []
  let latest
  const watcher = watchRun({
    async getRun() { return loads++ === 0 ? success.snapshot : fixtureStatus(success, 12) },
    async streamEvents(_runId, { after, onOpen, onFrame, signal }) {
      attempts.push(after)
      onOpen()
      const tape = after === 0 ? success.events.slice(0, 8) : success.events.slice(after - 1)
      for (const event of tape) {
        if (signal.aborted) break
        onFrame(toFrame(event))
      }
    },
  }, success.snapshot.run_id, (view) => { latest = view }, { retryDelay: () => 0 })
  await watcher.done
  assert.deepEqual(attempts, [0, 12])
  assert.equal(latest.connection, 'closed')
  assert.deepEqual(latest.snapshot, success.final)
  assert.equal(new Set(latest.snapshot.artifacts.map(({ artifact_id }) => artifact_id)).size, 16)
})

test('a submission retry keeps its key and a new run gets a new key', async () => {
  let counter = 0
  const keys = createSubmissionKeys(() => `submission-${++counter}`)
  const { input } = success.snapshot
  const first = keys.get(input)
  assert.equal(keys.get({ ...input }), first)
  keys.reset()
  assert.notEqual(keys.get(input), first)
  const second = keys.get(input)
  assert.notEqual(keys.get({ ...input, geography: 'India' }), second)
  const records = new Map()
  const mock = createMockClient({
    fixtures: fullAgentFixtures,
    storage: { getItem: (key) => records.get(key), setItem: (key, value) => records.set(key, value) },
  })
  const options = { scenario: 'full-succeeded', idempotencyKey: first }
  const [accepted, retried] = await Promise.all([mock.startRun(input, options), mock.startRun(input, options)])
  assert.deepEqual(accepted, retried)
  await assert.rejects(mock.startRun({ ...input, geography: 'India' }, options), { status: 409 })
  assert.notEqual((await mock.startRun(input, { ...options, idempotencyKey: second })).run_id, accepted.run_id)
  const client = createLiveClient(async (url, opts) => {
    assert.equal(url, '/api/v1/runs')
    assert.equal(opts.headers['Idempotency-Key'], first)
    assert.deepEqual(JSON.parse(opts.body), input)
    return Response.json(accepted, { status: 202 })
  })
  assert.deepEqual(await client.startRun(input, { idempotencyKey: first }), accepted)
})

test('exports preserve bytes and safe names, and report HTTP or payload failures', async () => {
  const tests = [
    ['pdf', 'application/pdf', ['%PDF-1.7', new Uint8Array([0, 255, 13])],
      "attachment; filename=\"fallback.pdf\"; filename*=UTF-8''Camp%C3%BAs%20Plan.pdf", 'Campús Plan.pdf'],
    ['pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      [new Uint8Array([80, 75, 3, 4, 255, 0])], 'attachment; filename="../deck.pptx"', '_deck.pptx'],
    ['markdown', 'text/markdown; charset=utf-8', ['# Startup plan'], 'attachment; filename="wrong.exe"', 'startup-plan.md'],
  ]
  const run = success.snapshot.run_id
  for (const [format, type, bytes, disposition, filename] of tests) {
    const client = createLiveClient(async (url) => {
      assert.equal(url, `/api/v1/runs/${run}/exports/${format}`)
      return new Response(new Blob(bytes), { headers: { 'Content-Type': type, 'Content-Disposition': disposition } })
    })
    const exported = await client.downloadExport(run, format)
    assert.equal(exported.filename, filename)
    assert.deepEqual(await exported.blob.arrayBuffer(), await new Blob(bytes).arrayBuffer())
  }
  const unavailable = createLiveClient(async () => Response.json({ error: { message: 'Run incomplete' } }, { status: 409 }))
  await assert.rejects(unavailable.downloadExport(run, 'pdf'), { status: 409, message: 'Run incomplete' })
  const invalid = createLiveClient(async () => new Response('Not a PDF', { headers: { 'Content-Type': 'application/pdf' } }))
  await assert.rejects(invalid.downloadExport(run, 'pdf'), ProtocolError)
})
