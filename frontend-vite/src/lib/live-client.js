import { createParser } from 'eventsource-parser'
import { ApiError } from './client.js'
import { readExport } from './exports.js'
import { ProtocolError } from './run-state.js'

const runsPath = '/api/v1/runs'
const runPath = (runId) => `${runsPath}/${encodeURIComponent(runId)}`

export function createLiveClient(fetcher = globalThis.fetch, { accessToken, onUnauthorized } = {}) {
  async function request(path, options) {
    const headers = { ...options?.headers }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    const response = await fetcher(path, { cache: 'no-store', ...options, headers })
    if (response.ok) return response
    const body = await response.json().catch(() => null)
    if (response.status === 401 && !options?.signal?.aborted) onUnauthorized?.()
    throw new ApiError(body?.error?.message ?? `API request failed (HTTP ${response.status}).`, {
      status: response.status,
      code: body?.error?.code,
      retryable: body?.error?.retryable,
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
    supportsExports: true,
    supportsPricingRevision: true,
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
