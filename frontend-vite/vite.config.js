import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

const root = fileURLToPath(new URL('.', import.meta.url))
const contracts = fileURLToPath(new URL('../shared/contracts/', import.meta.url))

export default defineConfig(({ mode }) => {
  const { API_PROXY_TARGET } = loadEnv(mode, root, 'API_PROXY_TARGET')
  return {
    plugins: [react()],
    server: {
      fs: { allow: [root, contracts] },
      proxy: mode !== 'mock' ? {
        '^/api/v1(?:/|$)': {
          target: API_PROXY_TARGET || 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      } : undefined,
    },
  }
})
