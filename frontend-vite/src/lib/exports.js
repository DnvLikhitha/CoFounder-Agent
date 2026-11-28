import { ProtocolError } from './run-state.js'

// Matches RETIRED_DEMO_VERSIONS in backend/run_worker/workflow.py.
export const retiredDemoVersions = new Set(['fake-business-v1', 'fake-business-v2'])

export function startDownload(url, filename) {
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.append(anchor)
  try {
    anchor.click()
  } finally {
    anchor.remove()
  }
}

export function saveDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  try {
    startDownload(url, filename)
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}

const formats = {
  markdown: { extension: 'md', types: ['text/markdown', 'text/plain'] },
  pdf: { extension: 'pdf', types: ['application/pdf'], signature: '%PDF-' },
  pptx: {
    extension: 'pptx', types: ['application/vnd.openxmlformats-officedocument.presentationml.presentation'],
    signature: 'PK\u0003\u0004',
  },
}

export async function readExport(response, format) {
  if (!Object.hasOwn(formats, format)) throw new ProtocolError('The requested export format is unavailable.')
  const { extension, types, signature } = formats[format]
  const type = response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase()
  const blob = await response.blob()
  if ((!types.includes(type) && type !== 'application/octet-stream') || !blob.size ||
      (signature && await blob.slice(0, signature.length).text() !== signature)) {
    throw new ProtocolError('The API did not return a valid export file.')
  }
  return { blob, filename: exportFilename(response.headers.get('Content-Disposition') ?? '', extension) }
}

function exportFilename(disposition, extension) {
  const fallback = `startup-plan.${extension}`
  const encoded = disposition.match(/filename\*\s*=\s*UTF-8'[^']*'([^;]+)/i)?.[1]?.trim()
  const plain = disposition.match(/filename\s*=\s*(?:"([^"]+)"|([^;]+))/i)
  let filename = plain?.[1] || plain?.[2]
  if (encoded) {
    try {
      filename = decodeURIComponent(encoded)
    } catch {
      // Retain the regular filename if the extended value is malformed.
    }
  }
  const safe = filename?.replace(/[<>:"/\\|?*]/g, '_')
    .replace(/\p{Cc}/gu, '_').trim().replace(/^[. ]+|[. ]+$/g, '')
  return safe?.toLowerCase().endsWith(`.${extension}`) ? safe : fallback
}
