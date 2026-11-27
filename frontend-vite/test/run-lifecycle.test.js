import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { createParser } from 'eventsource-parser'
import { createLiveClient } from '../src/lib/live-client.js'
import { createMockClient } from '../src/lib/mock-client.js'
import { applyFrame, checkSnapshot, ProtocolError, toFrame } from '../src/lib/run-state.js'
import { watchRun } from '../src/lib/watch-run.js'

function loadFixtures(scenario) {
  function read(file) {
    return readFileSync(new URL(`../../shared/contracts/fixtures/${scenario}/${file}`, import.meta.url), 'utf8')
  }
  return {
    snapshot: JSON.parse(read('snapshot.json')),
    final: JSON.parse(read('final.json')),
    artifacts: JSON.parse(read('artifacts.json')),
    events: read('events.jsonl').trim().split(/\r?\n/).map((line) => JSON.parse(line)),
    wire: read('events.sse'),
  }
}

const fixtures = { succeeded: loadFixtures('succeeded'), partial: loadFixtures('partial') }
const scenarios = Object.entries(fixtures)

for (const [name, { snapshot, events, final, wire }] of scenarios) {
  test(`${name} replays wire and JSON fixtures to the same final snapshot`, () => {
    const frames = []
    const parser = createParser({ onEvent: (frame) => frames.push(frame) })
    for (let i = 0; i < wire.length; i += 17) parser.feed(wire.slice(i, i + 17))
    const initial = checkSnapshot(snapshot, snapshot.run_id)
    const jsonFrames = events.map(toFrame)
    assert.deepEqual(frames.map(({ id, event, data }) => ({ id, event, data: JSON.parse(data) })),
      jsonFrames.map(({ id, event, data }) => ({ id, event, data: JSON.parse(data) })))
    assert.deepEqual(frames.reduce(applyFrame, initial), final)
  })

  test(`${name} resumes from every snapshot cursor and ignores replays`, () => {
    const frames = events.map(toFrame)
    for (let cursor = 0; cursor <= frames.length; cursor += 1) {
      const beforeReload = frames.slice(0, cursor).reduce(applyFrame, snapshot)
      const refreshed = checkSnapshot(structuredClone(beforeReload), snapshot.run_id, cursor)
      const afterReload = frames.slice(Math.max(0, cursor - 1)).reduce((state, frame) => {
        const applied = applyFrame(state, frame)
        assert.equal(applyFrame(applied, frame), applied)
        return applied
      }, refreshed)
      assert.deepEqual(afterReload, final)
    }
  })
}

test('invalid IDs, event names, versions, run IDs and out-of-order events require recovery', () => {
  const { snapshot, events } = fixtures.succeeded
  const first = toFrame(events[0])
  const invalid = [
    toFrame(events[1]),
    { ...first, id: '2' },
    { ...first, event: 'unknown' },
    { ...first, data: 'invalid json' },
    toFrame({ ...events[0], contract_version: '2.0' }),
    toFrame({ ...events[0], run_id: fixtures.partial.snapshot.run_id }),
    toFrame({ ...events[0], data: { status: 'running' } }),
  ]
  for (const frame of invalid) assert.throws(() => applyFrame(snapshot, frame), ProtocolError)
})

test('live reconnect gets a fresh snapshot and replays over the relative API path', async () => {
  const { snapshot, events, final, wire } = fixtures.partial
  const afterFirst = events.slice(0, 2).map(toFrame).reduce(applyFrame, snapshot)
  const afterGap = events.slice(0, 3).map(toFrame).reduce(applyFrame, snapshot)
  const [first, second, third, ...rest] = wire.trimEnd().split(/\r?\n\r?\n/)
  const calls = []
  let snapshotReads = 0
  let streamReads = 0
  let terminalSignal
  function feed(frames) {
    const data = new TextEncoder().encode(frames.join('\n\n') + '\n\n')
    const stream = new ReadableStream({
      start(controller) {
        for (let i = 0; i < data.length; i += 11) controller.enqueue(data.slice(i, i + 11))
        controller.close()
      },
    })
    return new Response(stream, { headers: { 'Content-Type': 'text/event-stream; charset=utf-8' } })
  }
  const client = createLiveClient(async (url, options) => {
    calls.push(url)
    if (!url.includes('/events?')) return Response.json([snapshot, afterFirst, afterGap][snapshotReads++])
    assert.equal(options.headers.Accept, 'text/event-stream')
    if (streamReads++ === 0) return feed([first])
    if (streamReads === 2) return feed([second, rest[0]])
    terminalSignal = options.signal
    return feed([third, ...rest])
  })
  const updates = []
  const watcher = watchRun(client, snapshot.run_id, (update) => updates.push(update), { retryDelay: () => 0 })
  await watcher.done
  const path = `/api/v1/runs/${snapshot.run_id}`
  assert.deepEqual(calls, [path, `${path}/events?after=0`, path, `${path}/events?after=2`, path, `${path}/events?after=3`])
  assert.equal(updates.filter(({ connection }) => connection === 'reconnecting').length, 2)
  assert.deepEqual(updates.at(-1), { snapshot: final, connection: 'closed', message: '' })
  assert.equal(terminalSignal.aborted, true)
  assert.equal(final.artifacts[0].kind, 'market_research')
  assert.equal(final.evaluations[0].score, 0.8)
  assert.equal(final.steps.find(({ step_id }) => step_id === 'summary').status, 'failed')
})

test('terminal refresh does not open a stream, and a 404 does not retry', async () => {
  const { final } = fixtures.partial
  let reads = 0
  const client = createLiveClient(async (url) => {
    reads += 1
    assert.equal(url.includes('/events'), false)
    if (url.endsWith(final.run_id)) return Response.json(final)
    return Response.json({ error: { message: 'Run not found.' } }, { status: 404 })
  })
  const updates = []
  await watchRun(client, final.run_id, (update) => updates.push(update)).done
  assert.deepEqual(updates.at(-1), { snapshot: final, connection: 'closed', message: '' })
  await watchRun(client, 'unknown', (update) => updates.push(update)).done
  assert.deepEqual(updates.at(-1), { snapshot: null, connection: 'error', message: 'Run not found.' })
  assert.equal(reads, 2)
})

test('closing a run watcher aborts the stream and stops publishing', async () => {
  const { snapshot } = fixtures.succeeded
  let signal
  const client = {
    async getRun() { return snapshot },
    streamEvents(_run, options) {
      signal = options.signal
      options.onOpen()
      return new Promise((resolve) => signal.addEventListener('abort', resolve, { once: true }))
    },
  }
  const updates = []
  const watcher = watchRun(client, snapshot.run_id, (update) => updates.push(update))
  await Promise.resolve()
  assert.equal(updates.at(-1).connection, 'connected')
  watcher.close()
  await watcher.done
  assert.equal(signal.aborted, true)
  assert.equal(updates.length, 3)
})

test('an expired cursor refreshes the snapshot and a failed run closes the stream', async () => {
  const { snapshot, events } = fixtures.succeeded
  const running = applyFrame(snapshot, toFrame(events[0]))
  const failed = {
    ...events[0],
    event_id: 2,
    data: {
      ...events[0].data,
      status: 'failed',
      completed_at: events[0].occurred_at,
      error: { code: 'missing_output', message: 'No usable output was produced.', retryable: false },
    },
  }
  let reads = 0
  const cursors = []
  const client = createLiveClient(async (url) => {
    if (!url.includes('/events?')) return Response.json([snapshot, running][reads++])
    const cursor = new URL(url, 'http://localhost').searchParams.get('after')
    cursors.push(cursor)
    if (cursor === '0') return Response.json({ error: { code: 'event_cursor_expired' } }, { status: 410 })
    const { id, event, data } = toFrame(failed)
    return new Response(`id: ${id}\nevent: ${event}\ndata: ${data}\n\n`, {
      headers: { 'Content-Type': 'text/event-stream' },
    })
  })
  const updates = []
  await watchRun(client, snapshot.run_id, (update) => updates.push(update), { retryDelay: () => 0 }).done
  assert.deepEqual(cursors, ['0', '1'])
  assert.equal(updates.at(-1).connection, 'closed')
  assert.equal(updates.at(-1).snapshot.status, 'failed')
  assert.deepEqual(updates.at(-1).snapshot.artifacts, [])
})

test('repeated contract mismatches surface as incompatibility', async () => {
  const { snapshot } = fixtures.succeeded
  const client = { async getRun() { return { ...snapshot, contract_version: '2.0' } } }
  const updates = []
  await watchRun(client, snapshot.run_id, (update) => updates.push(update), { retryDelay: () => 0 }).done
  assert.equal(updates.at(-1).connection, 'error')
  assert.match(updates.at(-1).message, /incompatible run data/)
})

test('mock runs survive a reload at review and retain partial artifacts after approval', async () => {
  let time = Date.parse('2026-11-27T12:00:00Z')
  const records = new Map()
  const storage = { getItem: (key) => records.get(key), setItem: (key, value) => records.set(key, value) }
  const runId = '00000000-0000-4000-8000-000000000003'
  const config = { fixtures, storage, now: () => time, makeId: () => runId, interval: 100 }
  const mock = createMockClient(config)
  const input = { problem: 'Find internships for university students.', domain: null, geography: null }
  const queued = await mock.startRun(input, { scenario: 'partial' })
  assert.equal(checkSnapshot(queued, runId).status, 'queued')
  time += 750
  const reloaded = createMockClient(config)
  const awaiting = await reloaded.getRun(runId)
  assert.equal(checkSnapshot(awaiting, runId).status, 'awaiting_review')
  assert.equal(awaiting.last_event_id, 7)
  const decision = { decision_id: '10000000-0000-4000-8000-000000000002', decision: 'approve', comment: null }
  const receipt = await reloaded.decideReview(runId, awaiting.pending_review.review_id, decision)
  assert.equal(receipt.event_id, 8)
  assert.deepEqual(await mock.decideReview(runId, awaiting.pending_review.review_id, decision), receipt)
  await assert.rejects(mock.decideReview(runId, awaiting.pending_review.review_id, { ...decision, decision: 'reject' }),
    { status: 409 })
  time += 1000
  const controller = new AbortController()
  let replayed = awaiting
  await mock.streamEvents(runId, {
    after: awaiting.last_event_id,
    signal: controller.signal,
    onOpen() {},
    onFrame(frame) { replayed = applyFrame(replayed, frame) },
  })
  const final = await reloaded.getRun(runId)
  assert.deepEqual(replayed, final)
  assert.equal(final.status, 'partial')
  assert.equal(final.artifacts.length, 1)
  assert.equal(final.evaluations[0].score, 0.8)
  const artifact = await mock.getArtifact(runId, 'research')
  assert.equal(artifact.reference.href, `/api/v1/runs/${runId}/artifacts/research`)
  assert.deepEqual(artifact.content, fixtures.partial.artifacts[0].content)
  await assert.rejects(mock.getArtifact(runId, 'summary'), { status: 404 })
  const firstPage = await mock.listRuns({ limit: 1 })
  assert.equal(firstPage.runs[0].run_id, runId)
  const lastPage = await mock.listRuns({ cursor: firstPage.next_cursor })
  assert.equal(lastPage.runs.length, 2)
  assert.equal(lastPage.next_cursor, null)
})
