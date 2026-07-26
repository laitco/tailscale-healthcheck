import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export function SettingsPanel({ settings }: { settings: Record<string, unknown> }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Settings (redacted)</CardTitle>
        <p className="text-xs text-muted-foreground">
          DISPLAY_SETTINGS_IN_OUTPUT is enabled. Sensitive tokens are not shown.
        </p>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Key</TableHead>
                <TableHead>Value</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(settings).map(([k, v]) => (
                <TableRow key={k}>
                  <TableCell className="font-mono text-xs">{k}</TableCell>
                  <TableCell className="font-mono text-xs">{String(v)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}
