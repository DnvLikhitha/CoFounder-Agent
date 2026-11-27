import { useEffect, useState } from 'react'
import { checkArtifact } from './run-state.js'

export function useArtifact(client, runId, reference) {
  const [result, setResult] = useState(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const request = new AbortController()
    async function load() {
      try {
        const artifact = await client.getArtifact(runId, reference.artifact_id, { signal: request.signal })
        if (!request.signal.aborted) setResult({ artifact: checkArtifact(artifact, runId, reference) })
      } catch (error) {
        if (!request.signal.aborted) setResult({ error: error.message })
      }
    }
    void load()
    return () => request.abort()
  }, [client, runId, reference, attempt])

  return {
    result,
    retry() {
      setResult(null)
      setAttempt((value) => value + 1)
    },
  }
}
