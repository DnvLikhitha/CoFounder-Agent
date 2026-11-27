/** Optional artifact content conventions. v1 allows arbitrary JSON content. */
export function readEvidence(content) {
  const sources = [
    ...items(content?.sources),
    ...items(content?.tool_evidence?.serpapi_sources),
  ].map(sourceReference).filter(Boolean)
  const unique = new Map()
  for (const source of sources) {
    const key = source.url ?? source.label
    if (!unique.has(key)) unique.set(key, source)
  }
  const assumptions = content?.assumptions
  const entries = Array.isArray(assumptions)
    ? assumptions.filter((item) => typeof item === 'string' && item.trim())
      .map((value) => ({ label: null, value }))
    : assumptions && typeof assumptions === 'object'
      ? Object.entries(assumptions).filter(([, value]) => value != null && value !== '')
        .map(([key, value]) => ({ label: key.replaceAll('_', ' '), value }))
      : []
  const note = text(content?.key_assumptions_note)
  if (text(assumptions)) entries.push({ label: null, value: assumptions })
  if (note) entries.push({ label: null, value: note })
  return { sources: [...unique.values()], assumptions: entries }
}

function items(value) {
  return Array.isArray(value) ? value : []
}

function text(value) {
  return typeof value === 'string' ? value.trim() : ''
}

function sourceReference(item) {
  if (typeof item === 'string') {
    const label = item.trim()
    if (!label) return null
    const candidate = label.match(/https?:\/\/[^\s<>"|]+/i)?.[0]?.replace(/[),.;]+$/, '')
    return { label, url: webUrl(candidate) }
  }
  const url = webUrl(item?.url)
  const label = text(item?.title) || url
  return label ? { label, url } : null
}

function webUrl(value) {
  if (!text(value)) return null
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null
  } catch {
    return null
  }
}
