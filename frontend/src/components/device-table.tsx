import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { StatusBadge } from '@/components/status-badge'
import { cn } from '@/lib/utils'
import { formatVersion, relativeTime, semverRank } from '@/lib/format'
import { useNow } from '@/lib/use-now'
import type { Device } from '@/lib/types'

type SortKey = 'healthy' | 'machineName' | 'os' | 'clientVersion' | 'lastSeen' | 'update_healthy' | 'key_healthy' | 'tags'

const columns: { key: SortKey; label: string; className?: string }[] = [
  { key: 'healthy', label: 'Status' },
  { key: 'machineName', label: 'Machine' },
  { key: 'os', label: 'OS' },
  { key: 'clientVersion', label: 'Version' },
  { key: 'lastSeen', label: 'Last Seen' },
  { key: 'update_healthy', label: 'Update' },
  { key: 'key_healthy', label: 'Key' },
  { key: 'tags', label: 'Tags' },
]

function getSortValue(d: Device, key: SortKey): string | number {
  switch (key) {
    case 'healthy':
    case 'update_healthy':
    case 'key_healthy':
      return d[key] ? 1 : 0
    case 'lastSeen':
      return Date.parse(d.lastSeen || '') || 0
    case 'tags':
      return (d.tags || []).join(',')
    case 'clientVersion':
      return semverRank(d.clientVersion)
    default:
      return (d[key] as string | undefined || '').toString().toLowerCase()
  }
}

export function DeviceTable({ devices }: { devices: Device[] }) {
  const [sortKey, setSortKey] = useState<SortKey | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const navigate = useNavigate()
  useNow(60000) // re-render periodically so "Last Seen" relative times stay current

  const sorted = useMemo(() => {
    if (!sortKey) return devices
    const factor = sortDir === 'desc' ? -1 : 1
    return [...devices].sort((a, b) => {
      const av = getSortValue(a, sortKey)
      const bv = getSortValue(b, sortKey)
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * factor
      return String(av).localeCompare(String(bv)) * factor
    })
  }, [devices, sortKey, sortDir])

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  return (
    <div className="overflow-x-auto rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((col) => (
              <TableHead
                key={col.key}
                onClick={() => toggleSort(col.key)}
                className="cursor-pointer select-none whitespace-nowrap"
                aria-sort={sortKey === col.key ? (sortDir === 'desc' ? 'descending' : 'ascending') : 'none'}
              >
                <span className="inline-flex items-center gap-1">
                  {col.label}
                  {sortKey === col.key ? (
                    sortDir === 'asc' ? (
                      <ArrowUp className="size-3.5" />
                    ) : (
                      <ArrowDown className="size-3.5" />
                    )
                  ) : (
                    <ArrowUpDown className="size-3.5 opacity-30" />
                  )}
                </span>
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.length === 0 && (
            <TableRow>
              <TableCell colSpan={columns.length} className="text-center text-muted-foreground">
                No devices match your filters.
              </TableCell>
            </TableRow>
          )}
          {sorted.map((d) => (
            <TableRow
              key={d.id}
              className="cursor-pointer"
              tabIndex={0}
              onClick={() => navigate(`/device/${encodeURIComponent(d.id)}`)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  navigate(`/device/${encodeURIComponent(d.id)}`)
                }
              }}
            >
              <TableCell>
                <StatusBadge ok={d.healthy} trueText="Healthy" falseText="Unhealthy" />
              </TableCell>
              <TableCell className="font-medium">{d.machineName}</TableCell>
              <TableCell>{d.os}</TableCell>
              <TableCell title={d.clientVersion}>{formatVersion(d.clientVersion)}</TableCell>
              <TableCell title={d.lastSeen}>{relativeTime(d.lastSeen)}</TableCell>
              <TableCell>
                <StatusBadge
                  ok={d.update_healthy}
                  trueText={d.updateAvailable ? 'Update OK' : 'No Update'}
                  falseText="Update Needed"
                />
              </TableCell>
              <TableCell>
                <StatusBadge ok={d.key_healthy} trueText={d.keyExpiryDisabled ? 'No Expiry' : 'Valid'} falseText="Expiring" />
              </TableCell>
              <TableCell className={cn('max-w-48 truncate text-muted-foreground')} title={(d.tags || []).join(', ')}>
                {(d.tags || []).join(', ')}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
