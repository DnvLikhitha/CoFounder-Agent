import succeededSnapshot from '../../../shared/contracts/fixtures/succeeded/snapshot.json'
import succeededFinal from '../../../shared/contracts/fixtures/succeeded/final.json'
import succeededArtifacts from '../../../shared/contracts/fixtures/succeeded/artifacts.json'
import succeededEvents from '../../../shared/contracts/fixtures/succeeded/events.jsonl?raw'
import partialSnapshot from '../../../shared/contracts/fixtures/partial/snapshot.json'
import partialFinal from '../../../shared/contracts/fixtures/partial/final.json'
import partialArtifacts from '../../../shared/contracts/fixtures/partial/artifacts.json'
import partialEvents from '../../../shared/contracts/fixtures/partial/events.jsonl?raw'
import artifactDetails from '../fixtures/artifact-details.json'

export const fixtures = {
  succeeded: {
    snapshot: succeededSnapshot,
    final: succeededFinal,
    artifacts: succeededArtifacts.map((artifact) => {
      const details = artifactDetails[artifact.reference.artifact_id]
      return details ? { ...artifact, content: { ...artifact.content, ...details } } : artifact
    }),
    events: parseJsonLines(succeededEvents),
  },
  partial: {
    snapshot: partialSnapshot,
    final: partialFinal,
    artifacts: partialArtifacts,
    events: parseJsonLines(partialEvents),
  },
}

function parseJsonLines(tape) {
  return tape.trim().split(/\r?\n/).map((line) => JSON.parse(line))
}
