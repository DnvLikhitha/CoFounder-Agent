import Ajv2020 from 'ajv/dist/2020.js'
import addFormats from 'ajv-formats'
import openapi from '../../../shared/contracts/openapi.json' with { type: 'json' }
import eventSchema from '../../../shared/contracts/sse.schema.json' with { type: 'json' }

const ajv = new Ajv2020({ strict: false })
addFormats(ajv)
const validateSnapshot = ajv.compile({
  components: openapi.components,
  $ref: '#/components/schemas/RunSnapshot',
})
const validateArtifact = ajv.compile({
  components: openapi.components,
  $ref: '#/components/schemas/Artifact',
})
const validateEvent = ajv.compile(eventSchema)
const terminalStatuses = new Set(['succeeded', 'partial', 'failed'])

export const statusLabels = {
  queued: 'Queued',
  running: 'Running',
  awaiting_review: 'Awaiting review',
  succeeded: 'Succeeded',
  partial: 'Partial results',
  failed: 'Failed',
  skipped: 'Skipped',
}

export class ProtocolError extends Error {}

export function isTerminal(status) {
  return terminalStatuses.has(status)
}

export function checkArtifact(artifact, runId, reference) {
  if (!validateArtifact(artifact) || artifact.run_id !== runId ||
      artifact.reference.artifact_id !== reference.artifact_id ||
      artifact.reference.step_id !== reference.step_id ||
      artifact.reference.kind !== reference.kind ||
      artifact.reference.media_type !== reference.media_type ||
      artifact.reference.quality !== reference.quality ||
      artifact.reference.revision !== reference.revision ||
      artifact.reference.supersedes_artifact_id !== reference.supersedes_artifact_id ||
      JSON.stringify(artifact.reference.input_artifact_ids) !== JSON.stringify(reference.input_artifact_ids) ||
      (reference.media_type !== 'application/json' && typeof artifact.content !== 'string')) {
    throw new ProtocolError('The artifact does not match the requested revision or v1 contract.')
  }
  return artifact
}

export function checkSnapshot(snapshot, runId, previousCursor = 0) {
  if (!validateSnapshot(snapshot) || snapshot.run_id !== runId) {
    throw new ProtocolError('The run snapshot does not match the v1 contract.')
  }
  if (snapshot.last_event_id < previousCursor) {
    throw new ProtocolError('The run snapshot is behind the event stream.')
  }

  const manifestIds = new Set(snapshot.manifest.steps.map(({ step_id }) => step_id))
  const stateIds = new Set(snapshot.steps.map(({ step_id }) => step_id))
  if (manifestIds.size !== snapshot.manifest.steps.length ||
      stateIds.size !== snapshot.steps.length ||
      stateIds.size !== manifestIds.size ||
      snapshot.steps.some(({ step_id }) => !manifestIds.has(step_id))) {
    throw new ProtocolError('The run snapshot has inconsistent step IDs.')
  }

  return snapshot
}

/** Apply a named SSE frame from sse.schema.json to a consistent RunSnapshot. */
export function applyFrame(snapshot, frame) {
  let event
  try {
    event = JSON.parse(frame.data)
  } catch {
    throw new ProtocolError('The stream sent an invalid JSON event.')
  }
  if (!validateEvent(event) || event.run_id !== snapshot.run_id ||
      frame.event !== event.type || frame.id !== String(event.event_id)) {
    throw new ProtocolError('The stream event does not match the v1 contract.')
  }
  if (event.event_id <= snapshot.last_event_id) return snapshot
  if (event.event_id !== snapshot.last_event_id + 1) {
    throw new ProtocolError('An event is missing from the run stream.')
  }
  if (isTerminal(snapshot.status)) {
    throw new ProtocolError('A terminal run received another event.')
  }

  const { data } = event
  let patch
  switch (event.type) {
    case 'run.updated':
      patch = data
      break
    case 'step.updated':
      if (!snapshot.steps.some((step) => step.step_id === data.step_id)) {
        throw new ProtocolError('The stream referenced a step outside the manifest.')
      }
      patch = {
        steps: snapshot.steps.map((step) => step.step_id === data.step_id ? data : step),
      }
      break
    case 'artifact.created':
      patch = { artifacts: appendById(snapshot.artifacts, data, 'artifact_id') }
      break
    case 'evaluation.completed':
      patch = { evaluations: appendById(snapshot.evaluations, data, 'evaluation_id') }
      break
    case 'review.requested':
      patch = { pending_review: data }
      break
    case 'review.decided':
      if (data.run_id !== snapshot.run_id || data.event_id !== event.event_id ||
          snapshot.pending_review?.review_id !== data.review_id) {
        throw new ProtocolError('The review decision does not match the pending review.')
      }
      patch = { pending_review: null }
      break
  }
  return { ...snapshot, ...patch, updated_at: event.occurred_at, last_event_id: event.event_id }
}

function appendById(items, item, key) {
  return items.some((other) => other[key] === item[key]) ? items : [...items, item]
}

export function toFrame(event) {
  return { id: String(event.event_id), event: event.type, data: JSON.stringify(event) }
}
