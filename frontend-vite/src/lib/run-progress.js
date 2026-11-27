import { isTerminal } from './run-state.js'

export function orderedSteps(manifest) {
  return [...manifest.steps].sort((a, b) => a.order - b.order ||
    (a.step_id === b.step_id ? 0 : a.step_id < b.step_id ? -1 : 1))
}

export function summarizeProgress(manifest, states) {
  const byId = new Map(states.map((step) => [step.step_id, step]))
  const steps = orderedSteps(manifest).map((definition) => {
    const state = byId.get(definition.step_id)
    const waiting = definition.depends_on.filter((id) => byId.get(id)?.status !== 'succeeded')
    const blockers = waiting.filter((id) => ['failed', 'skipped', 'partial'].includes(byId.get(id)?.status))
    const blocked = state.error?.code === 'dependency_blocked' ||
      (['queued', 'skipped'].includes(state.status) && blockers.length > 0)
    return { ...definition, ...state, waiting, blockers, blocked }
  })
  return {
    steps,
    settled: steps.filter(({ status }) => isTerminal(status) || status === 'skipped').length,
    completed: steps.filter(({ status }) => status === 'succeeded').length,
    running: steps.filter(({ status }) => status === 'running'),
    blocked: steps.filter((step) => step.blocked),
    queued: steps.filter((step) => step.status === 'queued' && !step.blocked).length,
    partial: steps.filter(({ status }) => status === 'partial').length,
    failed: steps.filter(({ status }) => status === 'failed').length,
  }
}
