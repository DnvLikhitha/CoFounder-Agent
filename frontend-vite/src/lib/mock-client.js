import { ApiError, delay } from './client.js'
import { applyFrame, isTerminal, toFrame } from './run-state.js'

const storageKey = 'cofounder-vite.mock-runs.v1'
const reviewEvent = 'review.decided'

/** Serve the shared snapshots and event tapes through the same interface as HTTP. */
export function createMockClient({
  fixtures, storage, now = Date.now, makeId = () => crypto.randomUUID(), interval = 550,
}) {
  function readRuns() {
    return JSON.parse(storage.getItem(storageKey) ?? '{}')
  }

  function findRun(runId) {
    const record = readRuns()[runId]
    if (record && Object.hasOwn(fixtures, record.scenario)) return record
    const fixture = Object.entries(fixtures).find(([, item]) => item.snapshot.run_id === runId)
    if (!fixture) throw new ApiError('Run not found.', { status: 404 })
    return { scenario: fixture[0], seeded: true }
  }

  function saveRun(runId, record) {
    storage.setItem(storageKey, JSON.stringify({ ...readRuns(), [runId]: record }))
  }

  function materialize(runId, record) {
    const fixture = fixtures[record.scenario]
    if (record.seeded) return { snapshot: fixture.snapshot, events: fixture.events }

    const created = new Date(record.startedAt).toISOString()
    const snapshot = {
      ...fixture.snapshot,
      run_id: runId,
      input: record.input,
      created_at: created,
      updated_at: created,
    }
    const reviewIndex = fixture.events.findIndex(({ type }) => type === reviewEvent)
    const decision = record.review?.decision
    const elapsed = Math.max(0, now() - record.startedAt)
    const beforeReview = Math.min(reviewIndex, Math.floor(elapsed / interval))
    const resumed = decision ? 2 + Math.floor(Math.max(0, now() - record.review.at) / interval) : 0

    let events = fixture.events
    if (decision?.decision === 'reject') {
      const review = fixture.events.find(({ type }) => type === 'review.requested').data
      const error = { code: 'review_rejected', message: 'The research review was rejected.', retryable: false }
      const queued = snapshot.steps.filter((step) => step.step_id !== review.step_id)
      events = [
        ...events.slice(0, reviewIndex + 1),
        ...queued.map((step) => ({ type: 'step.updated', data: { ...step, status: 'skipped' } })),
        { type: 'run.updated', data: { status: 'partial', error, completed_at: created } },
      ]
    }

    // A snapshot exposes review requests together with the run pause.
    const requestIndex = fixture.events.findIndex(({ type }) => type === 'review.requested')
    const visibleBeforeReview = beforeReview === requestIndex + 1 ? requestIndex : beforeReview
    const visible = !decision ? visibleBeforeReview
      : decision.decision === 'reject' ? events.length : reviewIndex + resumed
    const stepStarts = new Map()
    return {
      snapshot,
      events: events.slice(0, visible).map((event, index) => {
        const eventId = index + 1
        const timestamp = index < reviewIndex
          ? record.startedAt + eventId * interval
          : record.review.at + (decision.decision === 'reject' ? 0 : Math.max(0, index - reviewIndex - 1) * interval)
        const occurredAt = new Date(timestamp).toISOString()
        const data = { ...event.data }
        for (const key of ['created_at', 'updated_at', 'completed_at', 'decided_at']) {
          if (data[key] != null) data[key] = occurredAt
        }
        if (event.type === 'step.updated' && data.started_at != null) {
          const key = `${data.step_id}:${data.attempt}`
          if (!stepStarts.has(key)) stepStarts.set(key, occurredAt)
          data.started_at = stepStarts.get(key)
        }
        if (event.type === 'run.updated') data.updated_at = occurredAt
        if (event.type === 'artifact.created') data.href = artifactPath(runId, data.artifact_id)
        if (event.type === reviewEvent) Object.assign(data, { run_id: runId, decision, event_id: eventId })
        return {
          contract_version: snapshot.contract_version,
          run_id: runId,
          event_id: eventId,
          occurred_at: occurredAt,
          type: event.type,
          data,
        }
      }),
    }
  }

  function getSnapshot(runId, record = findRun(runId)) {
    if (record.seeded) return fixtures[record.scenario].final
    const { snapshot, events } = materialize(runId, record)
    return events.reduce((current, event) => applyFrame(current, toFrame(event)), snapshot)
  }

  return {
    supportsExports: false,
    supportsRevisionPreview: true,
    getRevisionPreview(runId, reviewId) {
      const { revisionRequest } = findRun(runId)
      return revisionRequest?.review_id === reviewId ? revisionRequest : null
    },
    async startRun(input, { scenario = 'succeeded', signal } = {}) {
      signal?.throwIfAborted()
      if (!Object.hasOwn(fixtures, scenario)) throw new ApiError('Unknown mock scenario.', { status: 422 })
      const runId = makeId()
      const record = { scenario, input, startedAt: now() }
      saveRun(runId, record)
      return getSnapshot(runId, record)
    },
    async getRun(runId, { signal } = {}) {
      signal?.throwIfAborted()
      return getSnapshot(runId)
    },
    async listRuns({ cursor = null, limit = 25, signal } = {}) {
      signal?.throwIfAborted()
      const ids = [...new Set([
        ...Object.keys(readRuns()),
        ...Object.values(fixtures).map(({ snapshot }) => snapshot.run_id),
      ])]
      const runs = ids.map((runId) => {
        const { input, created_at, updated_at, completed_at, status, error } = getSnapshot(runId)
        return { run_id: runId, input, created_at, updated_at, completed_at, status, error }
      }).sort((a, b) => b.created_at.localeCompare(a.created_at) || b.run_id.localeCompare(a.run_id))
      const start = cursor === null ? 0 : runs.findIndex((run) => run.run_id === cursor) + 1
      if (cursor !== null && start === 0) throw new ApiError('Invalid history cursor.', { status: 422 })
      const page = runs.slice(start, start + limit)
      return { runs: page, next_cursor: start + limit < runs.length ? page.at(-1).run_id : null }
    },
    async getArtifact(runId, artifactId, { signal } = {}) {
      signal?.throwIfAborted()
      const record = findRun(runId)
      const reference = getSnapshot(runId, record).artifacts.find(({ artifact_id }) => artifact_id === artifactId)
      const fixture = fixtures[record.scenario].artifacts.find(({ reference }) => reference.artifact_id === artifactId)
      if (!reference || !fixture) throw new ApiError('Artifact not found.', { status: 404 })
      return { run_id: runId, reference, content: fixture.content }
    },
    async decideReview(runId, reviewId, decision, { signal, expectedArtifactIds } = {}) {
      signal?.throwIfAborted()
      const record = findRun(runId)
      if (record.review) {
        const previous = record.review
        if (previous.reviewId === reviewId &&
            previous.decision.decision_id === decision.decision_id &&
            previous.decision.decision === decision.decision &&
            previous.decision.comment === decision.comment) return previous.receipt
        throw new ApiError('This review already has a decision.', { status: 409 })
      }
      const snapshot = getSnapshot(runId, record)
      const review = snapshot.pending_review
      if (review?.review_id !== reviewId) {
        throw new ApiError('This review is no longer pending.', { status: 409 })
      }
      if (expectedArtifactIds &&
          JSON.stringify([...expectedArtifactIds].sort()) !== JSON.stringify([...review.artifact_ids].sort())) {
        throw new ApiError('The artifact revisions for this checkpoint changed.', { status: 409 })
      }
      if (decision.decision === 'revise') {
        if (!expectedArtifactIds?.length || !decision.comment?.trim()) {
          throw new ApiError('A revision request needs an artifact revision and feedback.', { status: 422 })
        }
        // Preview the request only. v1 has no revision decision, receipt, or SSE event.
        const receipt = {
          review_id: reviewId, artifact_ids: expectedArtifactIds,
          decision_id: decision.decision_id, comment: decision.comment,
        }
        const previous = record.revisionRequest
        if (previous?.decision_id === decision.decision_id && previous.comment !== decision.comment) {
          throw new ApiError('This decision ID was already used with different feedback.', { status: 409 })
        }
        saveRun(runId, { ...record, revisionRequest: receipt })
        return receipt
      }
      const at = now()
      const receipt = {
        run_id: runId, review_id: reviewId, decision,
        decided_at: new Date(at).toISOString(), event_id: snapshot.last_event_id + 1,
      }
      saveRun(runId, { ...record, review: { reviewId, decision, at, receipt } })
      return receipt
    },
    async downloadExport() {
      throw new ApiError('Download files are unavailable in mock mode.')
    },
    async streamEvents(runId, { after, signal, onOpen, onFrame }) {
      let cursor = after
      signal?.throwIfAborted()
      const record = findRun(runId)
      if (after > getSnapshot(runId, record).last_event_id) {
        throw new ApiError('Event cursor is ahead of this run.', { status: 409 })
      }
      onOpen()
      while (!signal?.aborted) {
        const current = findRun(runId)
        const { events } = materialize(runId, current)
        for (const event of events.slice(cursor)) {
          signal?.throwIfAborted()
          onFrame(toFrame(event))
          cursor = event.event_id
        }
        const last = events.at(-1)
        if (last?.type === 'run.updated' && isTerminal(last.data.status)) return
        await delay(interval / 2, signal)
      }
    },
  }
}

function artifactPath(runId, artifactId) {
  return `/api/v1/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`
}
