import contents from './full-agent-artifacts.json' with { type: 'json' }
import { applyFrame, toFrame } from '../lib/run-state.js'

// This manifest belongs to the fixtures. The run UI consumes the API manifest.
const waves = [
  ['Intake', [['problem_refined', 'Problem Refiner']]],
  ['Discovery', [['startup_idea', 'Idea Generator', 'problem_refined']]],
  ['Discovery', [
    ['market_research', 'Market Research', 'startup_idea'],
    ['competitor_analysis', 'Competitor Analysis', 'startup_idea'],
    ['customer_personas', 'Customer Personas', 'startup_idea'],
  ]],
  ['Planning', [
    ['product_design', 'Product Designer', 'customer_personas'],
    ['business_model', 'Business Model', 'market_research'],
  ]],
  ['Planning', [
    ['mvp_roadmap', 'MVP Roadmap', 'product_design'],
    ['pricing_strategy', 'Pricing Strategy', 'business_model'],
    ['risk_register', 'Risk Analyst', 'business_model'],
  ]],
  ['Execution', [
    ['financial_projections', 'Financial Projections', 'business_model', 'pricing_strategy'],
    ['tech_architecture', 'Technical Architecture', 'product_design'],
  ]],
  ['Execution', [
    ['database_schema', 'Database Schema', 'tech_architecture'],
    ['security_compliance', 'Security and Compliance', 'tech_architecture'],
  ]],
  ['Delivery', [
    ['pitch_deck', 'Pitch Deck', 'product_design', 'business_model'],
    ['executive_summary', 'Executive Summary', 'market_research', 'business_model'],
  ]],
]

const manifest = {
  version: 'full-agent-fixture-v1',
  steps: waves.flatMap(([phase, entries]) => entries.map(([step_id, label, ...depends_on]) => ({
    step_id, label, phase, depends_on, required: true, artifact_kinds: [step_id],
  }))).map((step, order) => ({ ...step, order })),
}
const timestamp = '2026-01-01T12:00:00Z'
const queued = ({ step_id }) => ({
  step_id, status: 'queued', attempt: 0, started_at: null, completed_at: null, error: null,
})
const fixtureError = (code, message) => ({ code, message, retryable: false })

function makeRun(runId, partial) {
  const snapshot = {
    contract_version: '1.0', run_id: runId, status: 'queued', input: {
      problem: 'Help commuter students find local internships that fit their schedules.',
      domain: 'Education', geography: null,
    },
    created_at: timestamp, updated_at: timestamp, completed_at: null, error: null,
    last_event_id: 0, manifest, steps: manifest.steps.map(queued),
    artifacts: [], evaluations: [], pending_review: null,
  }
  const events = []
  const artifacts = []
  const emit = (type, data) => events.push({
    contract_version: '1.0', run_id: runId, event_id: events.length + 1, occurred_at: timestamp, type, data,
  })
  const update = (status, error = null) => emit('run.updated', {
    status, updated_at: timestamp, completed_at: ['succeeded', 'partial'].includes(status) ? timestamp : null, error,
  })
  const pricingFailure = partial ? fixtureError('provider_timeout', 'Pricing did not complete before its deadline.') : null

  update('running')
  for (const [, entries] of waves) {
    const states = entries.map(([step_id]) => ({ ...queued({ step_id }), status: 'running', attempt: 1, started_at: timestamp }))
    for (const step of states) {
      if (partial && step.step_id === 'financial_projections') continue
      emit('step.updated', step)
    }
    for (const step of states) {
      const id = step.step_id
      if (partial && id === 'financial_projections') {
        emit('step.updated', { ...queued(step), status: 'skipped', completed_at: timestamp,
          error: fixtureError('dependency_blocked', 'Pricing is required for financial projections.') })
        continue
      }
      if (pricingFailure && id === 'pricing_strategy') {
        emit('step.updated', { ...step, status: 'failed', completed_at: timestamp, error: pricingFailure })
        continue
      }
      const quality = partial && id === 'executive_summary' ? 'partial' : 'complete'
      const reference = {
        artifact_id: id, step_id: id, kind: id, title: entries.find(([stepId]) => stepId === id)[1],
        media_type: 'application/json', quality, created_at: timestamp, href: `/api/v1/runs/${runId}/artifacts/${id}`,
      }
      const content = quality === 'partial'
        ? { ...contents[id], executive_summary: 'The campus internship concept is available. Pricing and projections are incomplete.' }
        : contents[id]
      artifacts.push({ run_id: runId, reference, content })
      emit('artifact.created', reference)
      emit('step.updated', { ...step, status: quality === 'partial' ? 'partial' : 'succeeded', completed_at: timestamp })
      if (id === 'market_research') emit('evaluation.completed', {
        evaluation_id: 'market-evidence', step_id: id, artifact_id: id, evaluator: 'Evidence review',
        evaluator_version: '1', outcome: 'needs_review', score: null,
        reasons: ['Confirm the campus selection assumption.'], created_at: timestamp,
      })
    }
    if (entries.some(([id]) => id === 'customer_personas')) {
      emit('review.requested', {
        review_id: 'market-checkpoint', step_id: 'market_research', artifact_ids: ['market_research'],
        prompt: 'Do these market assumptions fit your initial campus audience?', created_at: timestamp,
      })
      update('awaiting_review')
      emit('review.decided', {
        run_id: runId, review_id: 'market-checkpoint',
        decision: { decision_id: '00000000-0000-4000-8000-000000000605', decision: 'approve', comment: null },
        decided_at: timestamp, event_id: events.length + 1,
      })
      update('running')
    }
  }
  update(partial ? 'partial' : 'succeeded', pricingFailure)
  return { snapshot, events, artifacts, final: events.map(toFrame).reduce(applyFrame, snapshot) }
}

export const fullAgentFixtures = {
  'full-succeeded': makeRun('00000000-0000-4000-8000-000000000601', false),
  'full-partial': makeRun('00000000-0000-4000-8000-000000000602', true),
}
