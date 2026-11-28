import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { fullAgentFixtures } from '../src/fixtures/full-agent-runs.js'

const fixture = fullAgentFixtures['full-succeeded']
const verifier = fileURLToPath(new URL('../browser/verify-live.js', import.meta.url))
const fixtures = new URL('../src/fixtures/full-agent-runs.js', import.meta.url).href
const mockTransport = `
  const { fullAgentFixtures } = await import(${JSON.stringify(fixtures)})
  const { final, artifacts } = fullAgentFixtures['full-succeeded']
  const { LIVE_SUPABASE_URL, LIVE_API_ORIGIN, VERIFIER_FIXTURE_MANIFEST } = process.env
  const runPath = '/api/v1/runs/' + final.run_id
  const reviewed = VERIFIER_FIXTURE_MANIFEST === 'startup-reviewed-v1'
  const draft = artifacts.find(({ reference }) => reference.kind === 'financial_projections')
  const approved = { ...draft, reference: { ...draft.reference, artifact_id: 'financial_projections-r2', revision: 2,
    supersedes_artifact_id: draft.reference.artifact_id, href: draft.reference.href + '-r2' } }
  globalThis.fetch = async (input, options) => {
    const { origin, pathname } = new URL(input)
    if (origin === LIVE_SUPABASE_URL && pathname === '/auth/v1/token') {
      return Response.json({
        access_token: 'fixture-access-token', refresh_token: 'fixture-refresh-token',
        expires_in: 3600, user: { id: 'fixture-owner' },
      })
    }
    if (new Headers(options.headers).get('Authorization') !== 'Bearer fixture-access-token') {
      return new Response(null, { status: 401 })
    }
    if (origin === LIVE_SUPABASE_URL && pathname === '/auth/v1/logout') {
      return new Response(null, { status: 204 })
    }
    if (origin === LIVE_API_ORIGIN) {
      if (pathname === runPath) {
        return Response.json({ ...final, manifest: { ...final.manifest, version: VERIFIER_FIXTURE_MANIFEST },
          artifacts: reviewed ? [...final.artifacts, approved.reference] : final.artifacts })
      }
      const available = reviewed ? [...artifacts.filter((item) => item !== draft), approved] : artifacts
      const artifact = available.find(({ reference }) => pathname === runPath + '/artifacts/' + reference.artifact_id)
      if (artifact) return Response.json(artifact)
    }
    return new Response(null, { status: 404 })
  }
`

function runVerifier(version) {
  const preload = `data:text/javascript,${encodeURIComponent(mockTransport)}`
  const result = spawnSync(process.execPath, ['--import', preload, verifier], {
    encoding: 'utf8',
    timeout: 15000,
    env: {
      ...process.env,
      LIVE_API_ORIGIN: 'https://api.example.test',
      LIVE_SUPABASE_URL: 'https://auth.example.test',
      LIVE_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_verifier-test',
      LIVE_SUPABASE_ANON_KEY: '',
      LIVE_TEST_EMAIL: 'founder@example.test',
      LIVE_TEST_PASSWORD: 'fixture-password',
      LIVE_RUN_ID: fixture.final.run_id,
      VERIFIER_FIXTURE_MANIFEST: version,
    },
  })
  if (result.error) throw result.error
  return result
}

test('live verifier checks all 16 outputs including the latest approved revision', () => {
  for (const version of ['startup-reviewed-v1', 'startup-langgraph-v1', 'live-startup-v1']) {
    const { status, stdout, stderr } = runVerifier(version)
    assert.equal(status, 0, `${version}: ${stderr}`)
    const passed = [...stdout.matchAll(/^PASS (\w+)\r?$/gm)].map((match) => match[1])
    assert.deepEqual(passed.sort(), fixture.artifacts.map(({ reference }) => reference.kind).sort(), version)
  }
})

test('live verifier rejects unsupported manifests before checking outputs', () => {
  const { status, stdout, stderr } = runVerifier('fake-business-v2')
  assert.equal(status, 1)
  assert.doesNotMatch(stdout, /^PASS /m)
  assert.match(stderr, /unsupported live workflow manifest/)
})
