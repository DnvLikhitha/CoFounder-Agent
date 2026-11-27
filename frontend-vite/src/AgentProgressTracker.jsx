import { isTerminal, statusLabels } from './lib/run-state.js'

export function Status({ status }) {
  return <span className={`status status-${status}`}>{statusLabels[status] ?? status}</span>
}

export function AgentProgressTracker({ manifest, steps }) {
  const states = new Map(steps.map((step) => [step.step_id, step]))
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
            {items.map((step) => (
              <li key={step.step_id}>
                <div className="step-title"><strong>{step.label}</strong><Status status={step.status} /></div>
                {!step.required && <small>Optional</small>}
                {step.attempt > 1 && <small>Attempt {step.attempt}</small>}
                {step.error && <p>{step.error.message}</p>}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </aside>
  )
}
