import { ApiError } from './client.js'

export const expiredMessage = 'Your session expired or was rejected. Sign in again to continue.'

export function authErrorMessage(error) {
  if (error.status === 429) return 'Too many authentication requests. Wait before trying again.'
  if (!error.status || error.status >= 500) return 'Sign-in service unavailable. Try again shortly.'
  return 'Check your email and password and try again.'
}

export function createSessionAccess(auth, userId, onExpired) {
  let recovery
  let ending

  function read({ data, error }) {
    if (error && (error.status === 429 || !error.status || error.status >= 500) &&
        error.name !== 'AuthSessionMissingError') {
      throw new ApiError(authErrorMessage(error), { status: error.status === 429 ? 429 : 503 })
    }
    return data?.session
  }

  function tokenFor(session) {
    if (session?.user.id === userId) return session.access_token
    if (!session) onExpired()
    throw new ApiError(expiredMessage, { status: 401 })
  }

  function reject(rejectedToken) {
    ending ??= (async () => {
      const session = read(await auth.getSession())
      if (session && (session.user.id !== userId || session.access_token !== rejectedToken)) return
      try {
        if (session) await auth.signOut({ scope: 'local' })
      } finally {
        onExpired()
      }
    })().finally(() => { ending = null })
    return ending
  }

  return {
    async getToken() {
      return tokenFor(read(await auth.getSession()))
    },
    recover(rejectedToken) {
      recovery ??= (async () => {
        const current = tokenFor(read(await auth.getSession()))
        if (current !== rejectedToken) return current
        const renewed = read(await auth.refreshSession())
        if (!renewed) {
          await reject(rejectedToken)
          throw new ApiError(expiredMessage, { status: 401 })
        }
        return tokenFor(renewed)
      })().finally(() => { recovery = null })
      return recovery
    },
    reject,
  }
}
