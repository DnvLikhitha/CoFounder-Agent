import { isTerminal, statusLabels } from './lib/run-state.js'

export function Status({ status }) {
  return <span className={`status status-${status}`}>{statusLabels[status] ?? status}</span>
}

export function ProgressOverview({ progress }) {
  const { steps, settled, completed, running, queued, blocked, failed, partial } = progress
  return (
    <section className="panel run-overview" aria-labelledby="progress-title">
      <div className="section-heading">
        <h2 id="progress-title">Run progress</h2>
        <span>{settled} of {steps.length} steps finished</span>
      </div>
      {steps.length > 0 && <progress max={steps.length} value={settled} aria-label="Pipeline progress" />}
      <dl className="progress-counts">
        {[
          ['Running', running.length], ['Queued', queued], ['Completed', completed],
          ['Blocked', blocked.length], ['Failed', failed], ['Partial', partial],
        ].map(([label, count]) => <div key={label}><dt>{label}</dt><dd>{count}</dd></div>)}
      </dl>
      {running.length > 0 && <p><strong>Executing</strong> · {running.map(({ label }) => label).join(', ')}</p>}
      {blocked.length > 0 && <p><strong>Dependency-blocked</strong> · {blocked.map(({ label }) => label).join(', ')}</p>}
    </section>
  )
}

export function AgentProgressTracker({ steps, runStatus, artifacts, onViewArtifact }) {
  const definitions = new Map(steps.map((step) => [step.step_id, step]))
  const phases = []
  for (const step of steps) {
    if (phases.at(-1)?.name !== step.phase) {
      phases.push({ name: step.phase, steps: [] })
    }
    phases.at(-1).steps.push(step)
  }

  return (
    <aside className="panel pipeline" aria-labelledby="pipeline-title">
      <h2 id="pipeline-title">Agent pipeline</h2>
      {!steps.length && <p className="muted">The run manifest has no steps.</p>}
      {phases.map(({ name, steps: items }) => (
        <section key={items[0].step_id} className="phase">
          <h3>{name}</h3>
          <ul>
            {items.map((step) => {
              const outputs = artifacts.filter((item) => item.step_id === step.step_id)
              return (
                <li key={step.step_id}>
                  <div className="step-title">
                    <strong>{step.label}</strong>
                    {step.blocked ? <span className="status status-partial">Blocked</span> : <Status status={step.status} />}
                  </div>
                  {!step.required && <small>Optional</small>}
                  {step.attempt > 1 && <small>Attempt {step.attempt}</small>}
                  {['queued', 'skipped'].includes(step.status) &&
                    <DependencyNote step={step} definitions={definitions} runStatus={runStatus} />}
                  {step.error && <p>{step.error.message}</p>}
                  {outputs.map((item) => (
                    <button className="artifact-link" type="button" key={item.artifact_id}
                      onClick={() => onViewArtifact(item.artifact_id)}>
                      {item.title}{item.revision && ` · Revision ${item.revision}`}
                    </button>
                  ))}
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </aside>
  )
}

function DependencyNote({ step, definitions, runStatus }) {
  const labels = (ids) => ids.map((id) => definitions.get(id)?.label ?? id).join(', ')
  if (step.blockers.length) return <small>Blocked by {labels(step.blockers)}.</small>
  if (step.status === 'skipped') return <small>This step did not run.</small>
  if (isTerminal(runStatus)) return <small>The run ended before this step started.</small>
  if (step.waiting.length) return <small>Waiting for {labels(step.waiting)}.</small>
  return null
}
