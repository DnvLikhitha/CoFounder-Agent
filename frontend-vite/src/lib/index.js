import { createLiveClient } from './live-client.js'

export const mockMode = import.meta.env.MODE !== 'live'
const loadMock = async () => {
  const [{ createMockClient }, { fixtures }] = await Promise.all([
    import('./mock-client.js'),
    import('./mock-fixtures.js'),
  ])
  return createMockClient({ fixtures, storage: window.localStorage })
}

export const client = mockMode ? await loadMock() : createLiveClient()
