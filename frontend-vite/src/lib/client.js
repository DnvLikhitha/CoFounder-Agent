/**
 * Both clients expose startRun(input, options), getRun(runId, options),
 * listRuns(options), getArtifact(runId, artifactId, options),
 * decideReview(runId, reviewId, decision, options), downloadExport(runId, format, options),
 * and streamEvents(runId, options). Request options accept an AbortSignal.
 *
 * streamEvents resolves at EOF and rejects on transport/protocol errors.
 * Its options include after (the applied cursor), onOpen and onFrame.
 * The mock review preview accepts expectedArtifactIds in its request options.
 */
export class ApiError extends Error {
  constructor(message, { status, code, retryable, retryAfterMs } = {}) {
    super(message)
    this.status = status
    this.code = code
    this.retryable = retryable
    this.retryAfterMs = retryAfterMs
  }
}

export function delay(ms, signal) {
  signal?.throwIfAborted()
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', cancel)
      resolve()
    }, ms)

    function cancel() {
      clearTimeout(timer)
      reject(signal.reason)
    }

    signal?.addEventListener('abort', cancel, { once: true })
  })
}
