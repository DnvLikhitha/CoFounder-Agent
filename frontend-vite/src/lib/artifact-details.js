/** Optional artifact content conventions. v1 allows arbitrary JSON content. */
export function readEvidence(content) {
  const sources = [
    ...items(content?.sources),
    ...items(content?.data_sources_referenced),
    ...items(content?.tool_evidence?.serpapi_sources),
  ].map(sourceReference).filter(Boolean)
  const unique = new Map()
  for (const source of sources) {
    const key = source.url ?? source.label
    if (!unique.has(key)) unique.set(key, source)
  }
  return {
    sources: [...unique.values()],
    assumptions: [...entries(content?.assumptions), ...entries(content?.key_assumptions_note)],
  }
}

export function readUncertainty(content) {
  const fields = ['uncertainty', 'uncertainties', 'limitations', 'research_limitations', 'data_limitations', 'confidence']
  return fields.flatMap((field) => entries(content?.[field], field.replaceAll('_', ' ')))
}

function entries(value, label = null) {
  if (Array.isArray(value)) return value.filter(supplied).map((item) => ({ label, value: item }))
  if (value && typeof value === 'object') {
    return Object.entries(value).filter(([, item]) => supplied(item))
      .map(([key, item]) => ({ label: key.replaceAll('_', ' '), value: item }))
  }
  return supplied(value) ? [{ label, value }] : []
}

function supplied(value) {
  return value != null && (typeof value !== 'string' || Boolean(value.trim()))
}

export function claimValue(content, pointer) {
  if (pointer === '') return content
  if (!pointer.startsWith('/') || /~(?![01])/.test(pointer)) return undefined
  return pointer.slice(1).split('/').reduce((value, segment) => {
    const key = segment.replaceAll('~1', '/').replaceAll('~0', '~')
    if (Array.isArray(value) && !/^(0|[1-9]\d*)$/.test(key)) return undefined
    return value && typeof value === 'object' && Object.hasOwn(value, key) ? value[key] : undefined
  }, content)
}

export function revisionLabel(reference) {
  return reference.revision ? `Revision ${reference.revision}` : reference.artifact_id
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

export function webUrl(value) {
  if (!text(value)) return null
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null
  } catch {
    return null
  }
}
