export const mockMode = import.meta.env.DEV && import.meta.env.MODE === 'mock'
const loadMock = async () => {
  const [{ createMockClient }, { fixtures }] = await Promise.all([
    import('./mock-client.js'),
    import('./mock-fixtures.js'),
  ])
  return createMockClient({ fixtures, storage: window.localStorage, interval: 180 })
}

export const mockClient = mockMode ? await loadMock() : null
