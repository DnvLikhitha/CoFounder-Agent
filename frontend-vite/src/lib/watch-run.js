import { delay } from './client.js'
import { applyFrame, checkSnapshot, isTerminal, ProtocolError } from './run-state.js'

/**
 * Load a consistent snapshot before opening each stream. Reconnects preserve
 * the last view until a fresh snapshot is available. Closing aborts both
 * in-flight fetches and the backoff timer.
 */
export function watchRun(client, runId, publish, {
  retryDelay = (attempt) => Math.min(500 * 2 ** (attempt - 1), 8000),
  maxRetries = 6,
} = {}) {
  const controller = new AbortController()
  const { signal } = controller
  let snapshot = null
  let failures = 0
  let protocolFailures = 0

  function update(connection, message = '') {
    if (!signal.aborted) publish({ snapshot, connection, message })
  }

  async function run() {
    update('loading')
    while (!signal.aborted) {
      try {
        const previousCursor = snapshot?.last_event_id ?? 0
        const fresh = await client.getRun(runId, { signal })
        if (signal.aborted) return
        snapshot = checkSnapshot(fresh, runId, previousCursor)
        if (snapshot.last_event_id > previousCursor) failures = 0
        if (isTerminal(snapshot.status)) {
          update('closed')
          return
        }
        update('connecting')
        await client.streamEvents(runId, {
          after: snapshot.last_event_id,
          signal,
          onOpen: () => update('connected'),
          onFrame(frame) {
            if (signal.aborted) return
            const next = applyFrame(snapshot, frame)
            if (next === snapshot) return
            snapshot = next
            failures = 0
            protocolFailures = 0
            if (isTerminal(snapshot.status)) {
              update('closed')
              controller.abort()
            } else {
              update('connected')
            }
          },
        })
        if (signal.aborted) return
        throw new Error('The run stream closed.')
      } catch (error) {
        if (signal.aborted) return
        failures += 1
        if (error instanceof ProtocolError) protocolFailures += 1
        const incompatible = protocolFailures >= 3
        const requiresAction = [401, 403, 404, 422].includes(error.status)
        if (requiresAction || incompatible || failures > maxRetries) {
          const message = incompatible
            ? `The API repeatedly sent incompatible run data. ${error.message}`
            : error.status ? error.message : 'The run connection could not be restored.'
          update('error', message)
          return
        }
        let wait = retryDelay(failures)
        let message = 'Connection interrupted. Checking for updates…'
        if (error.status === 429) {
          message = 'Too many requests. Reconnecting…'
          wait = Math.min(Math.max(wait * 2, error.retryAfterMs ?? 0), 2_147_483_647)
        } else if (error.status === 503) {
          message = 'The run API is unavailable. Reconnecting…'
        }
        update('reconnecting', message)
        await delay(wait, signal).catch(() => {})
      }
    }
  }

  return { done: run(), close: () => controller.abort() }
}
