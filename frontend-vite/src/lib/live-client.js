import { createParser } from 'eventsource-parser'
import { ApiError } from './client.js'
import { readExport } from './exports.js'
import { ProtocolError } from './run-state.js'

const runsPath = '/api/v1/runs'
const runPath = (runId) => `${runsPath}/${encodeURIComponent(runId)}`

const statusMessages = {
  401: 'Your session expired or was rejected. Sign in again to continue.',
  403: 'You do not have permission to access this resource.',
  429: 'Too many requests. Wait before trying again.',
}

function parseRetryAfter(response) {
  const value = response.headers.get('Retry-After')
  if (!value) return undefined
  if (/^\d+$/.test(value)) return Number(value) * 1000
  const time = Date.parse(value)
  return Number.isNaN(time) ? undefined : Math.max(0, time - Date.now())
}

export function createLiveClient(fetcher = globalThis.fetch, session) {
  async function request(path, options) {
    const signal = options?.signal
    async function send(token) {
      signal?.throwIfAborted()
      const headers = { ...options?.headers }
      if (token) headers.Authorization = `Bearer ${token}`
      try {
        return await fetcher(path, { ...options, cache: 'no-store', credentials: 'omit', redirect: 'error', headers })
      } catch {
        signal?.throwIfAborted()
        throw new ApiError('The run API is unavailable. Try again shortly.', { status: 503, retryable: true })
      }
    }

    signal?.throwIfAborted()
    let token = await session?.getToken()
    let response = await send(token)
    if (session && response.status === 401) {
      await response.body?.cancel()
      signal?.throwIfAborted()
      token = await session.recover(token)
      response = await send(token)
      if (response.status === 401 && !signal?.aborted) await session.reject(token)
    }
    if (response.ok) return response
    const body = await response.json().catch(() => null)
    const message = response.status >= 500
      ? 'The run API is unavailable. Try again shortly.'
      : statusMessages[response.status] ?? body?.error?.message ?? `API request failed (HTTP ${response.status}).`
    throw new ApiError(message, {
      status: response.status,
      code: body?.error?.code,
      retryable: response.status >= 500 || response.status === 429 || body?.error?.retryable,
      retryAfterMs: response.status === 429 ? parseRetryAfter(response) : undefined,
    })
  }

  async function json(path, options) {
    const response = await request(path, options)
    try {
      return await response.json()
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error
      throw new ProtocolError('The API did not return a JSON response.')
    }
  }

  function post(path, body, signal, headers) {
    return json(path, {
      method: 'POST', signal,
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify(body),
    })
  }

  return {
    startRun(input, { signal, idempotencyKey } = {}) {
      return post(runsPath, input, signal, idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined)
    },
    getRun(runId, { signal } = {}) {
      return json(runPath(runId), { signal, cache: 'no-store' })
    },
    listRuns({ cursor = null, limit = 25, signal } = {}) {
      const params = new URLSearchParams({ limit: String(limit) })
      if (cursor !== null) params.set('cursor', cursor)
      return json(`${runsPath}?${params}`, { signal })
    },
    getArtifact(runId, artifactId, { signal } = {}) {
      return json(`${runPath(runId)}/artifacts/${encodeURIComponent(artifactId)}`, { signal })
    },
    async decideReview(runId, reviewId, decision, { signal, expectedArtifactIds } = {}) {
      if (decision.decision === 'revise' && (!decision.pricing_revision || !expectedArtifactIds?.length)) {
        throw new ApiError('Select a pricing tier and provide its revised prices.', { status: 422 })
      }
      const payload = expectedArtifactIds?.length ? { ...decision, artifact_ids: expectedArtifactIds } : decision
      return post(`${runPath(runId)}/reviews/${encodeURIComponent(reviewId)}/decisions`, payload, signal)
    },
    async downloadExport(runId, format, { signal } = {}) {
      const response = await request(`${runPath(runId)}/exports/${encodeURIComponent(format)}`, { signal })
      return readExport(response, format)
    },
    async streamEvents(runId, { after, signal, onOpen, onFrame }) {
      const response = await request(`${runPath(runId)}/events?after=${after}`, {
        signal, cache: 'no-store',
        headers: { Accept: 'text/event-stream' },
      })
      if (response.status === 204) return
      if (!response.body || !/^text\/event-stream\b/i.test(response.headers.get('Content-Type') ?? '')) {
        await response.body?.cancel()
        throw new ProtocolError('The run endpoint did not return an event stream.')
      }

      const parser = createParser({
        onEvent(frame) {
          signal.throwIfAborted()
          onFrame(frame)
        },
      })
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
      try {
        onOpen()
        while (!signal.aborted) {
          const { done, value } = await reader.read()
          if (done) break
          parser.feed(value)
        }
      } finally {
        await reader.cancel().catch(() => {})
        reader.releaseLock()
      }
    },
  }
}
