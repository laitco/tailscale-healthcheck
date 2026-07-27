import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { Alert } from '@/components/ui/alert'
import {
  fetchAuditLog,
  fetchAuditFilters,
  errorMessage,
  type AuditEntry,
  type AuditFiltersResponse,
} from '@/lib/admin-api'
import { relativeTime, formatDateTime } from '@/lib/format'
import { useTimezone } from '@/lib/health-context'
import { useUrlState } from '@/lib/use-url-state'
import { useDebounced } from '@/lib/use-debounced'
import { Pagination } from '@/components/pagination'

const ALL = '__all__'

const PAGE_SIZE = 100

const TIME_PRESETS = [
  { value: '24h', label: 'Last 24 hours', hours: 24 },
  { value: '7d', label: 'Last 7 days', hours: 24 * 7 },
  { value: '30d', label: 'Last 30 days', hours: 24 * 30 },
  { value: 'all', label: 'All time', hours: null },
  { value: 'custom', label: 'Custom range…', hours: undefined },
] as const

function renderFieldName(field: string): string {
  const spaced = field.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

function stringifyVal(v: unknown): string {
  if (v === null || v === undefined) return String(v)
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/** True if every value in `changes` looks like a per-field {old, new} diff entry. */
function isFieldDiff(changes: unknown): changes is Record<string, { old?: unknown; new?: unknown }> {
  if (!changes || typeof changes !== 'object' || Array.isArray(changes)) return false
  const entries = Object.entries(changes as Record<string, unknown>)
  if (entries.length === 0) return false
  return entries.every(([, v]) => v && typeof v === 'object' && !Array.isArray(v) && ('old' in v || 'new' in v))
}

/** True if `changes` itself is a single {old, new, source?} value (e.g. setting changes). */
function isSingleValueDiff(changes: unknown): changes is { old?: unknown; new?: unknown; source?: string } {
  if (!changes || typeof changes !== 'object' || Array.isArray(changes)) return false
  const obj = changes as Record<string, unknown>
  return ('old' in obj || 'new' in obj) && !isFieldDiff(changes)
}

const SNAPSHOT_FIELDS: Record<string, string[]> = {
  device: ['name', 'hostname', 'os', 'tags'],
  tailnet_key: ['description', 'key_type', 'expires'],
}

function ChangesSummary({ entry }: { entry: AuditEntry }) {
  const { entity_type, action, changes } = entry

  if (entity_type === 'user' && changes && typeof changes === 'object' && !Array.isArray(changes) && 'username' in (changes as Record<string, unknown>)) {
    const username = (changes as Record<string, unknown>).username
    return (
      <span>
        User <code className="font-mono">{stringifyVal(username)}</code> {action}
      </span>
    )
  }

  if (isFieldDiff(changes)) {
    const rows = Object.entries(changes)
    return (
      <div className="space-y-0.5">
        {rows.map(([field, diff]) => {
          if (field === 'tailnet_lock_error') {
            const nowNeedsSigning = Boolean(diff.new)
            return (
              <div key={field}>
                <span className="font-medium">Tailnet lock:</span>{' '}
                {nowNeedsSigning ? (
                  <span>
                    Needs signing <span className="text-muted-foreground">({stringifyVal(diff.new)})</span>
                  </span>
                ) : (
                  <span>Signed</span>
                )}
              </div>
            )
          }
          return (
            <div key={field}>
              <span className="font-medium">{renderFieldName(field)}:</span>{' '}
              <span className="text-muted-foreground">{stringifyVal(diff.old)}</span>
              {' → '}
              <span>{stringifyVal(diff.new)}</span>
            </div>
          )
        })}
      </div>
    )
  }

  if (isSingleValueDiff(changes)) {
    const hasOld = changes.old !== undefined && changes.old !== null
    return (
      <div>
        {hasOld && (
          <>
            <span className="text-muted-foreground">{stringifyVal(changes.old)}</span>
            {' → '}
          </>
        )}
        {!hasOld && <span className="text-muted-foreground">{'→ '}</span>}
        <span className="font-medium">{stringifyVal(changes.new)}</span>
        {changes.source && <span className="ml-1.5 text-[0.65rem] text-muted-foreground">({changes.source})</span>}
      </div>
    )
  }

  if (changes && typeof changes === 'object' && !Array.isArray(changes)) {
    const c = changes as Record<string, unknown>
    const fields = SNAPSHOT_FIELDS[entity_type] ?? Object.keys(c).slice(0, 4)
    const parts = fields.filter((f) => f in c).map((f) => `${renderFieldName(f)}: ${stringifyVal(c[f])}`)
    const label = action === 'created' ? 'Created' : action === 'removed' ? 'Removed' : renderFieldName(action)
    return (
      <span>
        {label}
        {parts.length > 0 ? `: ${parts.join(', ')}` : ''}
      </span>
    )
  }

  return <span className="text-muted-foreground">{stringifyVal(changes)}</span>
}

function ChangesCell({ entry }: { entry: AuditEntry }) {
  const [showRaw, setShowRaw] = useState(false)
  return (
    <div className="max-w-md space-y-1 text-xs">
      <ChangesSummary entry={entry} />
      <div>
        <button
          type="button"
          className="text-[0.65rem] text-muted-foreground underline decoration-dotted hover:text-foreground"
          onClick={() => setShowRaw((v) => !v)}
        >
          {showRaw ? 'Hide raw' : 'Raw'}
        </button>
      </div>
      {showRaw && (
        <pre className="max-w-md overflow-x-auto rounded-md border bg-muted/30 p-2 font-mono text-[0.65rem]">
          {JSON.stringify(entry.changes, null, 2)}
        </pre>
      )}
    </div>
  )
}

export default function AdminAuditPage() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null)
  const [filters, setFilters] = useState<AuditFiltersResponse | null>(null)
  // Filters live in the query string, so a dug-out view ("everything where os
  // changed, mentioning ReverseProxy") is a shareable link and survives reload.
  const [entityType, setEntityType] = useUrlState('entity_type', ALL)
  const [action, setAction] = useUrlState('action', ALL)
  const [entityId, setEntityId] = useUrlState('entity_id', ALL)
  const [actor, setActor] = useUrlState('actor', ALL)
  const [changedField, setChangedField] = useUrlState('changed_field', ALL)
  const [changesQuery, setChangesQuery] = useUrlState('changes', '')
  // Defaults to "Last 24 hours" so a restart or long-lived deployment doesn't
  // dump an undifferentiated wall of history where old entries (e.g. the
  // one-time setup wizard's "created" rows) read as if they just happened.
  const [timePreset, setTimePreset] = useUrlState('when', '24h')
  const [start, setStart] = useUrlState('from', '')
  const [end, setEnd] = useUrlState('to', '')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const debouncedChanges = useDebounced(changesQuery.trim())
  const timezone = useTimezone()

  // Full filter option set for entity_type/action/actor; entity_id options narrow to
  // the currently-selected entity_type via a refetch (per the backend contract).
  useEffect(() => {
    fetchAuditFilters(entityType === ALL ? undefined : entityType)
      .then(setFilters)
      // Filter options are a convenience; failing to load them must not take
      // the page down - the log itself still renders unfiltered.
      .catch(() => setFilters(null))
  }, [entityType])

  function load() {
    setEntries(null)
    setLoadError(null)
    const preset = TIME_PRESETS.find((p) => p.value === timePreset)
    const presetStart = preset?.hours ? new Date(Date.now() - preset.hours * 3600_000).toISOString() : ''
    const effectiveStart = timePreset === 'custom' ? (start ? new Date(start).toISOString() : '') : presetStart
    const effectiveEnd = timePreset === 'custom' ? (end ? new Date(end).toISOString() : '') : ''
    fetchAuditLog({
      entity_type: entityType === ALL ? '' : entityType,
      action: action === ALL ? '' : action,
      entity_id: entityId === ALL ? '' : entityId,
      actor: actor === ALL ? '' : actor,
      start: effectiveStart,
      end: effectiveEnd,
      changed_field: changedField === ALL ? '' : changedField,
      changes_contains: debouncedChanges,
      limit: String(PAGE_SIZE),
      offset: String(offset),
    })
      .then((data) => {
        setEntries(data.entries)
        setTotal(data.total)
      })
      // entries===null is also the loading state, so without this an error
      // was indistinguishable from "still loading" and the skeleton stayed up.
      .catch((err) => {
        setEntries([])
        setLoadError(errorMessage(err, 'Failed to load the audit log'))
      })
  }

  useEffect(load, [entityType, action, entityId, actor, changedField, debouncedChanges, timePreset, start, end, offset]) // eslint-disable-line react-hooks/exhaustive-deps

  // Any filter change invalidates the current page - staying on offset 400
  // after narrowing to 12 results would show an empty table.
  useEffect(() => {
    setOffset(0)
  }, [entityType, action, entityId, actor, changedField, debouncedChanges, timePreset, start, end])

  const entityIdOptions = useMemo(() => {
    const ids = filters?.entity_ids ?? []
    const filtered = entityType === ALL ? ids : ids.filter((e) => e.entity_type === entityType)
    // De-dupe entity_id values (same id can theoretically repeat across entity types).
    const seen = new Set<string>()
    return filtered.filter((e) => {
      const key = `${e.entity_type}:${e.entity_id}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [filters, entityType])

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              load()
            }}
          >
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="audit-entity-type">
                Entity type
              </label>
              <Select
                value={entityType}
                onValueChange={(v) => {
                  setEntityType(v)
                  setEntityId(ALL)
                }}
              >
                <SelectTrigger id="audit-entity-type" className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All</SelectItem>
                  {(filters?.entity_types ?? []).map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="audit-entity-id">
                Entity id
              </label>
              <Select value={entityId} onValueChange={setEntityId}>
                <SelectTrigger id="audit-entity-id" className="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All</SelectItem>
                  {entityIdOptions.map((e) => (
                    <SelectItem key={`${e.entity_type}:${e.entity_id}`} value={e.entity_id}>
                      {e.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="audit-action">
                Action
              </label>
              <Select value={action} onValueChange={setAction}>
                <SelectTrigger id="audit-action" className="w-32">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All</SelectItem>
                  {(filters?.actions ?? []).map((a) => (
                    <SelectItem key={a} value={a}>
                      {a}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="audit-actor">
                Actor
              </label>
              <Select value={actor} onValueChange={setActor}>
                <SelectTrigger id="audit-actor" className="w-44">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All</SelectItem>
                  {(filters?.actors ?? []).map((a) => (
                    <SelectItem key={a} value={a}>
                      {a === 'poller' ? 'Poller (automatic)' : a}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {/* Field select and free-text search are one joined control: they
                both filter the same column, and as separate flex children the
                search box got orphaned onto its own line wherever the row
                happened to wrap. Joined, they wrap as a unit and read as one
                filter - "changes to <field> containing <text>". */}
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="audit-changes-search">
                Changes
              </label>
              <div className="flex items-stretch">
                <Select value={changedField} onValueChange={setChangedField}>
                  {/* relative + focus z-10 so the focus ring paints over the
                      neighbour it shares a collapsed border with. */}
                  <SelectTrigger
                    id="audit-changed-field"
                    aria-label="Changed field"
                    className="relative w-36 rounded-r-none focus-visible:z-10"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>Any field</SelectItem>
                    {(filters?.changed_fields ?? []).map((f) => (
                      <SelectItem key={f} value={f}>
                        {renderFieldName(f)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input
                  id="audit-changes-search"
                  className="relative -ml-px w-52 rounded-l-none focus-visible:z-10"
                  placeholder="containing…"
                  value={changesQuery}
                  onChange={(e) => setChangesQuery(e.target.value)}
                />
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="audit-time-range">
                Time range
              </label>
              <Select value={timePreset} onValueChange={setTimePreset}>
                <SelectTrigger id="audit-time-range" className="w-44">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TIME_PRESETS.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {timePreset === 'custom' && (
              <>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-muted-foreground" htmlFor="audit-start">
                    From
                  </label>
                  <Input
                    id="audit-start"
                    type="datetime-local"
                    className="w-48"
                    value={start}
                    onChange={(e) => setStart(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-muted-foreground" htmlFor="audit-end">
                    To
                  </label>
                  <Input
                    id="audit-end"
                    type="datetime-local"
                    className="w-48"
                    value={end}
                    onChange={(e) => setEnd(e.target.value)}
                  />
                </div>
                <Button type="submit" variant="outline">
                  Apply
                </Button>
              </>
            )}
          </form>
        </CardContent>
      </Card>

      {loadError ? (
        <Alert>{loadError}</Alert>
      ) : !entries ? (
        <Skeleton className="h-96" />
      ) : entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No audit entries match these filters
          {timePreset !== 'all' && (
            <>
              {' '}
              in this time range — try{' '}
              <button type="button" className="underline decoration-dotted hover:text-foreground" onClick={() => setTimePreset('all')}>
                All time
              </button>
              .
            </>
          )}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg ring-1 ring-foreground/10">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Entity</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Changes</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell className="whitespace-nowrap">
                    {formatDateTime(entry.occurred_at, timezone)}
                    <span className="ml-1.5 text-[0.65rem] text-muted-foreground">({relativeTime(entry.occurred_at)})</span>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{entry.entity_type}</Badge>
                  </TableCell>
                  <TableCell>
                    <div className="max-w-[16rem] truncate font-medium" title={entry.entity_name}>
                      {entry.entity_name}
                    </div>
                    {entry.entity_name !== entry.entity_id && (
                      <div
                        className="max-w-[16rem] truncate font-mono text-[0.65rem] text-muted-foreground"
                        title={entry.entity_id}
                      >
                        {entry.entity_id}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>{entry.action}</TableCell>
                  <TableCell>{entry.actor || <span className="text-muted-foreground">poller</span>}</TableCell>
                  <TableCell>
                    <ChangesCell entry={entry} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {entries !== null && !loadError && (
        <Pagination
          offset={offset}
          pageSize={PAGE_SIZE}
          total={total}
          noun="audit entry"
          nounPlural="audit entries"
          onOffsetChange={setOffset}
        />
      )}
    </div>
  )
}
