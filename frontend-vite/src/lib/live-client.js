import { createParser } from 'eventsource-parser'
import { ApiError } from './client.js'
import { ProtocolError } from './run-state.js'

const runsPath = '/api/v1/runs'
const runPath = (runId) => `${runsPath}/${encodeURIComponent(runId)}`

export function createLiveClient(fetcher = globalThis.fetch, { accessToken } = {}) {
  async function request(path, options) {
    const headers = { ...options?.headers }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    const response = await fetcher(path, { cache: 'no-store', ...options, headers })
    if (response.ok) return response
    const body = await response.json().catch(() => null)
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

  function post(path, body, signal) {
    return json(path, {
      method: 'POST', signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  }

  return {
    supportsExports: true,
    startRun(input, { signal } = {}) {
      return post(runsPath, input, signal)
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
    async decideReview(runId, reviewId, decision, { signal } = {}) {
      if (decision.decision === 'revise') {
        throw new ApiError('Revision requests are unavailable in v1.', { status: 422 })
      }
      return post(`${runPath(runId)}/reviews/${encodeURIComponent(reviewId)}/decisions`, decision, signal)
    },
    async downloadExport(runId, format, { signal } = {}) {
      const response = await request(`${runPath(runId)}/exports/${encodeURIComponent(format)}`, { signal })
      const disposition = response.headers.get('Content-Disposition') ?? ''
      const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
      const plain = disposition.match(/filename=(?:"([^"]+)"|([^;]+))/i)
      const extension = format === 'markdown' ? 'md' : format
      let filename = plain?.[1] || plain?.[2]?.trim() || `startup-plan.${extension}`
      if (encoded) {
        try {
          filename = decodeURIComponent(encoded)
        } catch {
          // Keep the plain or default filename if the encoded form is invalid.
        }
      }
      return { blob: await response.blob(), filename: filename.replace(/[/\\]/g, '_') }
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
