import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { fetchAuditLog, fetchAuditFilters, type AuditEntry, type AuditFiltersResponse } from '@/lib/admin-api'

const ALL = '__all__'

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
        {rows.map(([field, diff]) => (
          <div key={field}>
            <span className="font-medium">{renderFieldName(field)}:</span>{' '}
            <span className="text-muted-foreground">{stringifyVal(diff.old)}</span>
            {' → '}
            <span>{stringifyVal(diff.new)}</span>
          </div>
        ))}
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
  const [entityType, setEntityType] = useState(ALL)
  const [action, setAction] = useState(ALL)
  const [entityId, setEntityId] = useState(ALL)
  const [actor, setActor] = useState(ALL)
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')

  // Full filter option set for entity_type/action/actor; entity_id options narrow to
  // the currently-selected entity_type via a refetch (per the backend contract).
  useEffect(() => {
    fetchAuditFilters(entityType === ALL ? undefined : entityType).then(setFilters)
  }, [entityType])

  function load() {
    setEntries(null)
    fetchAuditLog({
      entity_type: entityType === ALL ? '' : entityType,
      action: action === ALL ? '' : action,
      entity_id: entityId === ALL ? '' : entityId,
      actor: actor === ALL ? '' : actor,
      start: start ? new Date(start).toISOString() : '',
      end: end ? new Date(end).toISOString() : '',
      limit: '200',
    }).then((data) => setEntries(data.entries))
  }

  useEffect(load, [entityType, action, entityId, actor]) // eslint-disable-line react-hooks/exhaustive-deps

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
              <label className="text-xs font-medium text-muted-foreground">Entity type</label>
              <Select
                value={entityType}
                onValueChange={(v) => {
                  setEntityType(v)
                  setEntityId(ALL)
                }}
              >
                <SelectTrigger className="w-40">
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
              <label className="text-xs font-medium text-muted-foreground">Entity id</label>
              <Select value={entityId} onValueChange={setEntityId}>
                <SelectTrigger className="w-48">
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
              <label className="text-xs font-medium text-muted-foreground">Action</label>
              <Select value={action} onValueChange={setAction}>
                <SelectTrigger className="w-32">
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
              <label className="text-xs font-medium text-muted-foreground">Actor</label>
              <Select value={actor} onValueChange={setActor}>
                <SelectTrigger className="w-44">
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
          </form>
        </CardContent>
      </Card>

      {!entries ? (
        <Skeleton className="h-96" />
      ) : entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">No audit entries match these filters.</p>
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
                  <TableCell className="whitespace-nowrap">{new Date(entry.occurred_at).toLocaleString()}</TableCell>
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
    </div>
  )
}
