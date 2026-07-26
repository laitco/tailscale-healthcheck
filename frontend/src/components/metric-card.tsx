import type { ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

export function MetricCard({
  title,
  value,
  ok,
  subtitle,
}: {
  title: string
  value: string
  ok?: boolean
  subtitle?: ReactNode
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div
          className={cn(
            'text-2xl font-semibold',
            ok === true && 'text-primary',
            ok === false && 'text-destructive',
          )}
        >
          {value}
        </div>
        {subtitle && <div className="mt-1 text-xs text-muted-foreground">{subtitle}</div>}
      </CardContent>
    </Card>
  )
}
