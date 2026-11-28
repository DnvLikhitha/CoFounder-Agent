// Ownership is scoped to a single submission. A successful or intentionally
// discarded draft gets a new key, even if its input is identical.
export function createSubmissionKeys(makeKey = () => crypto.randomUUID()) {
  let previous
  return {
    get(input) {
      const payload = JSON.stringify([input.problem, input.domain, input.geography])
      if (previous?.payload !== payload) previous = { payload, key: makeKey() }
      return previous.key
    },
    reset() {
      previous = undefined
    },
  }
}
