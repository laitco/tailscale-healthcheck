import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { StatusBadge } from '@/components/status-badge'
import type { KeyMetrics, TailnetKey } from '@/lib/types'

export function KeysTable({ keys, metrics }: { keys: TailnetKey[]; metrics: KeyMetrics }) {
  let empty: string | null = null
  if (metrics.keys_error) {
    empty = `Tailnet keys are unavailable: ${metrics.keys_error}. Check that your API token/OAuth client has the Keys scope or capability.`
  } else if (!metrics.tailnet_configured) {
    empty = 'The TAILNET_DOMAIN environment variable is not configured (it is still set to the default example.com). Set it to your tailnet name to enable key monitoring.'
  } else if (!metrics.has_keys) {
    empty = 'No API or auth keys were found for this tailnet.'
  }

  return (
    <div className="overflow-x-auto rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Status</TableHead>
            <TableHead>Description</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Created</TableHead>
            <TableHead>Expires</TableHead>
            <TableHead>Days to Expire</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {empty && (
            <TableRow>
              <TableCell colSpan={6} className="text-muted-foreground">
                {empty}
              </TableCell>
            </TableRow>
          )}
          {!empty &&
            keys.map((k) => (
              <TableRow key={k.id}>
                <TableCell>
                  <StatusBadge ok={k.key_healthy} trueText="Healthy" falseText="Expiring" />
                </TableCell>
                <TableCell>{k.description || k.id}</TableCell>
                <TableCell>{k.keyType}</TableCell>
                <TableCell>{k.created ? k.created.slice(0, 10) : ''}</TableCell>
                <TableCell>{k.expires ? k.expires.slice(0, 10) : 'Never'}</TableCell>
                <TableCell>{k.key_days_to_expire ?? '—'}</TableCell>
              </TableRow>
            ))}
        </TableBody>
      </Table>
    </div>
  )
}
