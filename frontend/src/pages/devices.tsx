import { useMemo } from 'react'
import { Download } from 'lucide-react'
import { DeviceTable } from '@/components/device-table'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useHealthContext } from '@/lib/health-context'
import { useUrlState } from '@/lib/use-url-state'
import { Pagination } from '@/components/pagination'
import { toCsv, downloadBlob } from '@/lib/format'
import type { Device } from '@/lib/types'
import { Alert } from '@/components/ui/alert'

const ALL = '__all__'

const PAGE_SIZE = 50

export default function DevicesPage() {
  const { health, loading, error } = useHealthContext()
  // Filters live in the query string so a filtered view is shareable and
  // survives a reload / back-forward navigation.
  const [search, setSearch] = useUrlState('q', '')
  const [status, setStatus] = useUrlState('status', ALL)
  const [os, setOs] = useUrlState('os', ALL)
  const [tag, setTag] = useUrlState('tag', ALL)
  const [offsetParam, setOffsetParam] = useUrlState('offset', '0')
  const offset = Math.max(0, parseInt(offsetParam, 10) || 0)

  const devices = health?.devices ?? []

  const osValues = useMemo(() => Array.from(new Set(devices.map((d) => d.os).filter(Boolean))).sort(), [devices])
  const tagValues = useMemo(
    () => Array.from(new Set(devices.flatMap((d) => d.tags || []))).sort(),
    [devices],
  )

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return devices.filter((d: Device) => {
      if (q) {
        const tagsStr = (d.tags || []).join(' ').toLowerCase()
        const hit =
          (d.hostname || '').toLowerCase().includes(q) ||
          (d.id || '').toLowerCase().includes(q) ||
          (d.device || '').toLowerCase().includes(q) ||
          (d.machineName || '').toLowerCase().includes(q) ||
          tagsStr.includes(q)
        if (!hit) return false
      }
      if (os !== ALL && d.os !== os) return false
      if (tag !== ALL && !(d.tags || []).includes(tag)) return false
      if (status === 'healthy' && !d.healthy) return false
      if (status === 'unhealthy' && d.healthy) return false
      return true
    })
  }, [devices, search, os, tag, status])

  // Clamp rather than reset: a filter change can shrink the result set below
  // the current offset, which would otherwise show an empty page with a
  // "Previous" button as the only way out.
  const pageOffset = offset >= filtered.length ? 0 : offset
  const page = filtered.slice(pageOffset, pageOffset + PAGE_SIZE)

  if (loading && !health) {
    return <Skeleton className="h-96" />
  }

  if (error && !health) {
    return (
      <Alert>
        Failed to load devices: {error}
      </Alert>
    )
  }

  return (
    <div className="space-y-4">
      <section className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="Search hostname, id, machine, tag"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="All status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All status</SelectItem>
            <SelectItem value="healthy">Healthy</SelectItem>
            <SelectItem value="unhealthy">Unhealthy</SelectItem>
          </SelectContent>
        </Select>
        <Select value={os} onValueChange={setOs}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="All OS" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All OS</SelectItem>
            {osValues.map((v) => (
              <SelectItem key={v} value={v}>
                {v}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={tag} onValueChange={setTag}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="All tags" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All tags</SelectItem>
            {tagValues.map((v) => (
              <SelectItem key={v} value={v}>
                {v}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="flex-1" />
        <Button variant="outline" onClick={() => downloadBlob(toCsv(filtered), 'tailscale-health.csv', 'text/csv')}>
          <Download />
          CSV
        </Button>
        <Button
          variant="outline"
          onClick={() => downloadBlob(JSON.stringify(filtered, null, 2), 'tailscale-health.json', 'application/json')}
        >
          <Download />
          JSON
        </Button>
      </section>

      <DeviceTable devices={page} />

      <Pagination
        offset={pageOffset}
        pageSize={PAGE_SIZE}
        total={filtered.length}
        noun="device"
        onOffsetChange={(next) => setOffsetParam(String(next))}
      />
    </div>
  )
}
