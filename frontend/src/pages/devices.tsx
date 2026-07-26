import { useMemo, useState } from 'react'
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
import { toCsv, downloadBlob } from '@/lib/format'
import type { Device } from '@/lib/types'

const ALL = '__all__'

export default function DevicesPage() {
  const { health, loading, error } = useHealthContext()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState(ALL)
  const [os, setOs] = useState(ALL)
  const [tag, setTag] = useState(ALL)

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

  if (loading && !health) {
    return <Skeleton className="h-96" />
  }

  if (error && !health) {
    return (
      <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-destructive">
        Failed to load devices: {error}
      </div>
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

      <DeviceTable devices={filtered} />
    </div>
  )
}
