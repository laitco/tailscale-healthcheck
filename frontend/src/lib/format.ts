export function relativeTime(iso?: string | null): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (!then || Number.isNaN(then)) return ''
  const diff = Math.max(0, Math.floor((Date.now() - then) / 1000))
  if (diff < 60) return 'just now'
  const m = Math.floor(diff / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  return `${d}d ago`
}

interface Semver {
  major: number
  minor: number
  patch: number
  build: number
}

export function parseSemver(ver?: string | null): Semver | null {
  if (!ver) return null
  const m = ver.match(/(\d+)\.(\d+)\.(\d+)/)
  if (!m) return null
  const buildMatch = ver.match(/^\d+\.\d+\.\d+-(\d+)/)
  return {
    major: parseInt(m[1], 10),
    minor: parseInt(m[2], 10),
    patch: parseInt(m[3], 10),
    build: buildMatch ? parseInt(buildMatch[1], 10) || 0 : 0,
  }
}

export function semverRank(ver?: string | null): number {
  const parsed = parseSemver(ver)
  if (!parsed) return 0
  return parsed.major * 1e9 + parsed.minor * 1e6 + parsed.patch * 1e3 + parsed.build
}

export function formatVersion(ver?: string | null): string {
  if (!ver) return ''
  const m = ver.match(/(\d+)\.(\d+)\.(\d+)(?:-(\d+))?/)
  if (!m) {
    const digitsOnly = (ver.match(/\d+(?:\.\d+)+/) || [''])[0]
    return digitsOnly
  }
  return `${m[1]}.${m[2]}.${m[3]}${m[4] ? '-' + m[4] : ''}`
}

const DEVICE_CSV_COLUMNS = [
  'machineName',
  'os',
  'clientVersion',
  'lastSeen',
  'updateAvailable',
  'update_healthy',
  'keyExpiryDisabled',
  'key_healthy',
  'key_days_to_expire',
  'healthy',
  'tags',
]

/**
 * Serialize rows to CSV. Array-valued cells (e.g. tags) are joined with "|"
 * so they survive a single cell.
 *
 * Takes explicit `cols` so the keys page can share this instead of keeping its
 * own copy - there used to be two near-identical serializers with duplicate
 * quote-escaping logic.
 */
export function toCsv(items: Record<string, unknown>[], cols: string[] = DEVICE_CSV_COLUMNS): string {
  if (!items.length) return ''
  const esc = (v: unknown) => '"' + String(v ?? '').replaceAll('"', '""') + '"'
  const lines = [cols.join(',')]
  for (const it of items) {
    lines.push(cols.map((c) => esc(Array.isArray(it[c]) ? (it[c] as unknown[]).join('|') : it[c])).join(','))
  }
  return lines.join('\n')
}

export function downloadBlob(content: string, filename: string, type: string) {
  const blob = new Blob([content], { type })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}

/**
 * Format an ISO timestamp in the tailnet's configured timezone (from
 * /health's poll_meta), not the viewer's browser timezone.
 *
 * Timestamps across the admin pages used bare toLocaleString(), so an admin in
 * a different timezone from the one configured for the app read every audit
 * entry, poller log line and login time shifted by their local offset.
 */
export function formatDateTime(iso?: string | null, timezone?: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  try {
    return date.toLocaleString(undefined, timezone ? { timeZone: timezone } : undefined)
  } catch {
    // An unknown/invalid IANA zone must not blank out the timestamp entirely.
    return date.toLocaleString()
  }
}

/** Time-only variant of formatDateTime(), for dense logs where the date is implied. */
export function formatTime(iso?: string | null, timezone?: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  try {
    return date.toLocaleTimeString(undefined, timezone ? { timeZone: timezone } : undefined)
  } catch {
    return date.toLocaleTimeString()
  }
}
