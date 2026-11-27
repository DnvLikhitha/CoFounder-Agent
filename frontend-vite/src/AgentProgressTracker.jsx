import { isTerminal, statusLabels } from './lib/run-state.js'

export function Status({ status }) {
  return <span className={`status status-${status}`}>{statusLabels[status] ?? status}</span>
}

export function AgentProgressTracker({ manifest, steps, runStatus }) {
  const states = new Map(steps.map((step) => [step.step_id, step]))
  const definitions = new Map(manifest.steps.map((step) => [step.step_id, step]))
  const phases = []
  const ordered = [...manifest.steps].sort((a, b) => a.order - b.order ||
    (a.step_id === b.step_id ? 0 : a.step_id < b.step_id ? -1 : 1))
  for (const definition of ordered) {
    if (phases.at(-1)?.name !== definition.phase) {
      phases.push({ name: definition.phase, steps: [] })
    }
    phases.at(-1).steps.push({ ...definition, ...states.get(definition.step_id) })
  }
  const finished = steps.filter(({ status }) => isTerminal(status) || status === 'skipped').length

  return (
    <aside className="panel pipeline">
      <header className="section-heading">
        <h2>Agent pipeline</h2>
        <span>{finished} of {ordered.length} finished</span>
      </header>
      {ordered.length > 0 && <progress max={ordered.length} value={finished} aria-label="Pipeline progress" />}
      {phases.map(({ name, steps: items }) => (
        <section key={items[0].step_id} className="phase">
          <h3>{name}</h3>
          <ul>
            {items.map((step) => {
              const dependencies = step.depends_on.filter((id) => states.get(id)?.status !== 'succeeded')
              const blockers = dependencies.filter((id) =>
                ['failed', 'skipped'].includes(states.get(id)?.status) ||
                step.status === 'skipped' && states.get(id)?.status === 'partial')
              const blocked = step.status === 'queued' && blockers.length > 0
              return (
                <li key={step.step_id}>
                  <div className="step-title">
                    <strong>{step.label}</strong>
                    {blocked ? <span className="status status-partial">Blocked</span> : <Status status={step.status} />}
                  </div>
                  {!step.required && <small>Optional</small>}
                  {step.attempt > 1 && <small>Attempt {step.attempt}</small>}
                  {['queued', 'skipped'].includes(step.status) &&
                    <DependencyNote step={step} blockers={blockers} dependencies={dependencies}
                      definitions={definitions} runStatus={runStatus} />}
                  {step.error && <p>{step.error.message}</p>}
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </aside>
  )
}

function DependencyNote({ step, blockers, dependencies, definitions, runStatus }) {
  const labels = (ids) => ids.map((id) => definitions.get(id)?.label ?? id).join(', ')
  if (blockers.length) return <small>Blocked by {labels(blockers)}.</small>
  if (step.status === 'skipped') return <small>This step did not run.</small>
  if (isTerminal(runStatus)) return <small>The run ended before this step started.</small>
  if (dependencies.length) return <small>Waiting for {labels(dependencies)}.</small>
  return null
}
