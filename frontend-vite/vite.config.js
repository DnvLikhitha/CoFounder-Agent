import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import { authConfig } from './src/lib/auth-config.js'

const root = fileURLToPath(new URL('.', import.meta.url))
const contracts = fileURLToPath(new URL('../shared/contracts/', import.meta.url))

export default defineConfig(({ command, mode, isPreview }) => {
  if (command === 'build' && mode === 'mock') {
    throw new Error('Mock mode is available only through the development server.')
  }
  if (mode !== 'mock') authConfig(loadEnv(mode, root, 'VITE_SUPABASE_'))
  const { API_PROXY_TARGET, DEV_HTTPS_CERT, DEV_HTTPS_KEY } = loadEnv(mode, root, ['API_PROXY_TARGET', 'DEV_HTTPS_'])
  let https
  if (command === 'serve' && mode === 'live' && !isPreview && (DEV_HTTPS_CERT || DEV_HTTPS_KEY)) {
    if (!DEV_HTTPS_CERT || !DEV_HTTPS_KEY) throw new Error('Set both DEV_HTTPS_CERT and DEV_HTTPS_KEY to enable local HTTPS.')
    https = { cert: readFileSync(DEV_HTTPS_CERT), key: readFileSync(DEV_HTTPS_KEY) }
  }
  return {
    plugins: [react()],
    server: {
      https,
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
