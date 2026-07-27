import { useMemo } from 'react'
import { Download } from 'lucide-react'
import { KeysTable } from '@/components/keys-table'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useHealthContext } from '@/lib/health-context'
import { useUrlState } from '@/lib/use-url-state'
import { Pagination } from '@/components/pagination'
import { downloadBlob, toCsv } from '@/lib/format'
import type { TailnetKey } from '@/lib/types'
import { Alert } from '@/components/ui/alert'

const ALL = '__all__'

const KEY_CSV_COLUMNS = ['id', 'description', 'keyType', 'created', 'expires', 'key_healthy', 'key_days_to_expire']

const PAGE_SIZE = 50

export default function TailnetKeysPage() {
  const { keys, loading, error } = useHealthContext()
  const [search, setSearch] = useUrlState('q', '')
  const [keyType, setKeyType] = useUrlState('type', ALL)
  const [offsetParam, setOffsetParam] = useUrlState('offset', '0')
  const offset = Math.max(0, parseInt(offsetParam, 10) || 0)

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

  const pageOffset = offset >= filtered.length ? 0 : offset
  const page = filtered.slice(pageOffset, pageOffset + PAGE_SIZE)

  if (loading && !keys) {
    return <Skeleton className="h-96" />
  }

  if (error && !keys) {
    return (
      <Alert>
        Failed to load tailnet keys: {error}
      </Alert>
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
        <Button variant="outline" onClick={() => downloadBlob(toCsv(filtered as unknown as Record<string, unknown>[], KEY_CSV_COLUMNS), 'tailnet-keys.csv', 'text/csv')}>
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

      <KeysTable keys={page} metrics={keys!.metrics} />

      <Pagination
        offset={pageOffset}
        pageSize={PAGE_SIZE}
        total={filtered.length}
        noun="key"
        onOffsetChange={(next) => setOffsetParam(String(next))}
      />
    </div>
  )
}
