import { useMemo, useState } from 'react'
import { Download } from 'lucide-react'
import { KeysTable } from '@/components/keys-table'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useHealthContext } from '@/lib/health-context'
import { downloadBlob } from '@/lib/format'
import type { TailnetKey } from '@/lib/types'

const ALL = '__all__'

function keysToCsv(items: TailnetKey[]): string {
  if (!items.length) return ''
  const cols = ['id', 'description', 'keyType', 'created', 'expires', 'key_healthy', 'key_days_to_expire']
  const esc = (v: unknown) => '"' + String(v ?? '').replaceAll('"', '""') + '"'
  const lines = [cols.join(',')]
  for (const it of items) {
    lines.push(cols.map((c) => esc(it[c])).join(','))
  }
  return lines.join('\n')
}

export default function TailnetKeysPage() {
  const { keys, loading, error } = useHealthContext()
  const [search, setSearch] = useState('')
  const [keyType, setKeyType] = useState(ALL)

  const allKeys = keys?.keys ?? []

  const keyTypeValues = useMemo(
    () => Array.from(new Set(allKeys.map((k) => k.keyType).filter(Boolean))).sort(),
    [allKeys],
  )

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return allKeys.filter((k: TailnetKey) => {
      if (q) {
        const hit = (k.description || '').toLowerCase().includes(q) || (k.id || '').toLowerCase().includes(q)
        if (!hit) return false
      }
      if (keyType !== ALL && k.keyType !== keyType) return false
      return true
    })
  }, [allKeys, search, keyType])

  if (loading && !keys) {
    return <Skeleton className="h-96" />
  }

  if (error && !keys) {
    return (
      <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-destructive">
        Failed to load tailnet keys: {error}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <section className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="Search description, id"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        <Select value={keyType} onValueChange={setKeyType}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="All types" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All types</SelectItem>
            {keyTypeValues.map((v) => (
              <SelectItem key={v} value={v}>
                {v}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="flex-1" />
        <Button variant="outline" onClick={() => downloadBlob(keysToCsv(filtered), 'tailnet-keys.csv', 'text/csv')}>
          <Download />
          CSV
        </Button>
        <Button
          variant="outline"
          onClick={() => downloadBlob(JSON.stringify(filtered, null, 2), 'tailnet-keys.json', 'application/json')}
        >
          <Download />
          JSON
        </Button>
      </section>

      <KeysTable keys={filtered} metrics={keys!.metrics} />
    </div>
  )
}
