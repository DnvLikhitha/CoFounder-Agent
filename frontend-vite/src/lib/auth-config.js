export function authConfig({ VITE_SUPABASE_URL: url, VITE_SUPABASE_PUBLISHABLE_KEY: key, VITE_SUPABASE_ANON_KEY: anon }) {
  if (!url && !key && !anon) return null
  let origin
  try {
    origin = new URL(url)
  } catch {
    throw new Error('VITE_SUPABASE_URL must be an HTTPS Supabase project origin or a loopback HTTP origin.')
  }
  const local = origin.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(origin.hostname)
  if ((!local && origin.protocol !== 'https:') || (url !== origin.origin && url !== `${origin.origin}/`)) {
    throw new Error('VITE_SUPABASE_URL must be an HTTPS Supabase project origin or a loopback HTTP origin.')
  }
  if ((!key && !anon) || (key && !/^sb_publishable_[\w-]+$/.test(key)) || (anon && !isAnonKey(anon))) {
    throw new Error('Configure a Supabase publishable key or a legacy anon key for browser sign-in.')
  }
  return { url: origin.origin, key: key || anon }
}

function isAnonKey(key) {
  if (!/^[\w-]+\.[\w-]+\.[\w-]+$/.test(key)) return false
  try {
    const payload = key.split('.')[1].replaceAll('-', '+').replaceAll('_', '/')
    return JSON.parse(atob(payload)).role === 'anon'
  } catch {
    return false
  }
}
