import assert from 'node:assert/strict'
import { AuthClient } from '@supabase/auth-js'
import { authConfig } from '../src/lib/auth-config.js'
import { checkArtifact, checkSnapshot } from '../src/lib/run-state.js'

const reviewedVersion = 'startup-reviewed-v1'
const liveManifestVersions = [reviewedVersion, 'startup-langgraph-v1', 'live-startup-v1']
const expected = [
  'problem_refined', 'startup_idea', 'market_research', 'competitor_analysis', 'customer_personas',
  'product_design', 'mvp_roadmap', 'business_model', 'pricing_strategy', 'financial_projections',
  'risk_register', 'tech_architecture', 'database_schema', 'security_compliance', 'pitch_deck', 'executive_summary',
]

async function verify() {
  const env = process.env
  const required = [
    'LIVE_API_ORIGIN', 'LIVE_SUPABASE_URL', 'LIVE_TEST_EMAIL', 'LIVE_TEST_PASSWORD', 'LIVE_RUN_ID',
  ]
  const missing = required.filter((name) => !env[name])
  if (!env.LIVE_SUPABASE_PUBLISHABLE_KEY && !env.LIVE_SUPABASE_ANON_KEY) {
    missing.push('LIVE_SUPABASE_PUBLISHABLE_KEY or LIVE_SUPABASE_ANON_KEY')
  }
  if (missing.length) throw new Error(`Missing live verification settings: ${missing.join(', ')}.`)

  let api
  try {
    api = new URL(env.LIVE_API_ORIGIN)
  } catch {
    api = null
  }
  if (api?.protocol !== 'https:' ||
      (env.LIVE_API_ORIGIN !== api.origin && env.LIVE_API_ORIGIN !== `${api.origin}/`)) {
    throw new Error('LIVE_API_ORIGIN must be an HTTPS origin.')
  }
  const runId = env.LIVE_RUN_ID
  if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(runId)) {
    throw new Error('LIVE_RUN_ID must be a UUID.')
  }
  const { url, key } = authConfig({
    VITE_SUPABASE_URL: env.LIVE_SUPABASE_URL,
    VITE_SUPABASE_PUBLISHABLE_KEY: env.LIVE_SUPABASE_PUBLISHABLE_KEY,
    VITE_SUPABASE_ANON_KEY: env.LIVE_SUPABASE_ANON_KEY,
  })
  const auth = new AuthClient({
    url: `${url}/auth/v1`,
    headers: { apikey: key, Authorization: `Bearer ${key}` },
    persistSession: false,
    autoRefreshToken: false,
    detectSessionInUrl: false,
  })
  const { data, error } = await auth.signInWithPassword({ email: env.LIVE_TEST_EMAIL, password: env.LIVE_TEST_PASSWORD })
  if (error || !data.session) throw new Error(`Supabase sign-in failed${error?.status ? ` (HTTP ${error.status})` : ''}.`)

  const root = `${api.origin}/api/v1/runs/${runId}`
  async function get(path = '') {
    const response = await fetch(root + path, {
      headers: { Authorization: `Bearer ${data.session.access_token}` },
      redirect: 'error', signal: AbortSignal.timeout(15000),
    })
    if (!response.ok) throw new Error(`Run API returned HTTP ${response.status}.`)
    return response.json()
  }

  try {
    const snapshot = checkSnapshot(await get(), runId)
    assert.ok(liveManifestVersions.includes(snapshot.manifest.version), 'Run uses an unsupported live workflow manifest.')
    assert.equal(snapshot.manifest.steps.length, expected.length, 'Unexpected agent count.')
    const failures = []
    for (const stepId of expected) {
      try {
        const step = snapshot.steps.find(({ step_id }) => step_id === stepId)
        assert.equal(step?.status, 'succeeded', 'Agent did not succeed.')
        const references = snapshot.artifacts.filter(({ step_id }) => step_id === stepId)
        if (snapshot.manifest.version !== reviewedVersion) {
          assert.equal(references.length, 1, 'Expected one published artifact.')
        }
        const reference = references.at(-1)
        assert.ok(reference, 'Expected a published artifact.')
        assert.equal(reference.kind, stepId, 'Unexpected artifact kind.')
        assert.equal(reference.quality, 'complete', 'The artifact is incomplete.')
        const { content } = checkArtifact(await get(`/artifacts/${encodeURIComponent(reference.artifact_id)}`), runId, reference)
        assert.ok(content && typeof content === 'object' && Object.keys(content).length, 'The artifact has no structured output.')
        console.log(`PASS ${stepId}`)
      } catch (error) {
        failures.push(stepId)
        console.error(`FAIL ${stepId} (${error.message})`)
      }
    }
    if (failures.length || snapshot.status !== 'succeeded') {
      throw new Error(`Validated ${expected.length - failures.length}/${expected.length} agent outputs. Run status: ${snapshot.status}.`)
    }
    console.log(`Verified all ${expected.length} agent artifacts through the live API.`)
  } finally {
    const { error } = await auth.signOut({ scope: 'local' })
    if (error) console.error('Supabase could not revoke the verification session.')
  }
}

verify().catch((error) => {
  console.error(error.message)
  process.exitCode = 1
})
