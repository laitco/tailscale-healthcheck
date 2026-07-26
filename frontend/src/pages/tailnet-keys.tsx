import { KeysTable } from '@/components/keys-table'
import { Skeleton } from '@/components/ui/skeleton'
import { useHealthContext } from '@/lib/health-context'

export default function TailnetKeysPage() {
  const { keys, loading, error } = useHealthContext()

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

  return <KeysTable keys={keys?.keys ?? []} metrics={keys!.metrics} />
}
