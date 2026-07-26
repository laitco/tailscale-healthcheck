import { useEffect, useMemo, useState, useCallback } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { fetchPollerLog, type PollerLogEntry } from '@/lib/admin-api'

const FETCH_LIMIT = 300

/** Badge styling convention: destructive for *_error, secondary for *_success/poll_completed, outline otherwise. */
function eventBadgeVariant(eventType: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (eventType.endsWith('_error')) return 'destructive'
  if (eventType.endsWith('_success') || eventType === 'poll_completed') return 'secondary'
  return 'outline'
}

function formatDetail(detail: Record<string, unknown> | null): string | null {
  if (!detail) return null
  const entries = Object.entries(detail)
  if (entries.length === 0) return null
  return entries.map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`).join(' ')
}

export default function DebugPage() {
  const [entries, setEntries] = useState<PollerLogEntry[] | null>(null)
  const [eventTypes, setEventTypes] = useState<string[]>([])
  const [selected, setSelected] = useState<Set<string> | null>(null) // null = all selected
  const [meta, setMeta] = useState<{ enabled: boolean; last_polled_at: string | null; poll_interval_seconds: number } | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchPollerLog(FETCH_LIMIT)
      setEntries(data.entries) // already newest-first
      setEventTypes(data.event_types)
      setMeta({ enabled: data.enabled, last_polled_at: data.last_polled_at, poll_interval_seconds: data.poll_interval_seconds })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, 15000)
    return () => clearInterval(interval)
  }, [load])

  function toggleType(t: string) {
    setSelected((prev) => {
      // Starting from "all selected" (null): clicking one type means "show only this one".
      const base = prev ?? new Set(eventTypes)
      const next = new Set(base)
      if (next.has(t)) {
        next.delete(t)
      } else {
        next.add(t)
      }
      return next
    })
  }

  const isTypeShown = useCallback((t: string) => (selected === null ? true : selected.has(t)), [selected])

  const filteredEntries = useMemo(() => {
    if (!entries) return null
    if (selected === null) return entries
    return entries.filter((e) => selected.has(e.event_type))
  }, [entries, selected])

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Poller activity log</CardTitle>
          <CardDescription>
            Recent background poll-cycle events (device/key fetches, errors, timing). Auto-refreshes every 15s.
            {meta && !meta.enabled && ' Capture is currently disabled via the debug_log_enabled setting.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-2">
            {eventTypes.map((t) => (
              <Badge
                key={t}
                variant={isTypeShown(t) ? eventBadgeVariant(t) : 'ghost'}
                className={cn('cursor-pointer select-none', !isTypeShown(t) && 'opacity-40')}
                onClick={() => toggleType(t)}
              >
                {t}
              </Badge>
            ))}
            {selected !== null && (
              <Button variant="ghost" size="sm" className="h-5 px-2 text-[0.65rem]" onClick={() => setSelected(null)}>
                Reset
              </Button>
            )}
            <div className="flex-1" />
            <Button variant="outline" onClick={() => load()} disabled={loading}>
              <RefreshCw className={loading ? 'animate-spin' : ''} />
              Refresh
            </Button>
          </div>
          {meta && (
            <span className="mt-2 block text-xs text-muted-foreground">
              Poll interval: {meta.poll_interval_seconds}s
              {meta.last_polled_at ? ` · Last polled: ${new Date(meta.last_polled_at).toLocaleString()}` : ''}
            </span>
          )}
        </CardContent>
      </Card>

      {!filteredEntries ? (
        <Skeleton className="h-96" />
      ) : filteredEntries.length === 0 ? (
        <p className="text-sm text-muted-foreground">No log entries match the selected event types.</p>
      ) : (
        <div className="space-y-1.5">
          {filteredEntries.map((entry) => {
            const detailStr = formatDetail(entry.detail)
            return (
              <div
                key={entry.id}
                className="flex flex-wrap items-start gap-2 rounded-md px-2 py-1.5 text-xs/relaxed ring-1 ring-foreground/10"
              >
                <span className="whitespace-nowrap font-mono text-muted-foreground">
                  {new Date(entry.occurred_at).toLocaleTimeString()}
                </span>
                <Badge variant={eventBadgeVariant(entry.event_type)}>{entry.event_type}</Badge>
                <span className="flex-1">{entry.message}</span>
                {detailStr && <span className="font-mono text-muted-foreground">{detailStr}</span>}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
