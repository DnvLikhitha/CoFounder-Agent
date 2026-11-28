import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import { authConfig } from './src/lib/auth-config.js'

const root = fileURLToPath(new URL('.', import.meta.url))
const contracts = fileURLToPath(new URL('../shared/contracts/', import.meta.url))

export default defineConfig(({ command, mode }) => {
  if (command === 'build' && mode === 'mock') {
    throw new Error('Mock mode is available only through the development server.')
  }
  if (mode !== 'mock') authConfig(loadEnv(mode, root, 'VITE_SUPABASE_'))
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
