import type { ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Sparkline } from '@/components/sparkline'
import { cn } from '@/lib/utils'

// Mode-invariant "good" status color from the validated dataviz palette (graphical
// use, not text - clears the 3:1 large/graphical-element contrast target on both a
// light and a dark chart surface, so it does not need a per-theme swap).
const TREND_GOOD_COLOR = '#0ca30c'
const TREND_BAD_COLOR = 'var(--destructive)'
const TREND_NEUTRAL_COLOR = 'var(--muted-foreground)'

export function MetricCard({
  title,
  value,
  ok,
  subtitle,
  trend,
  trendTimestamps,
  trendTimezone,
}: {
  title: string
  value: string
  ok?: boolean
  subtitle?: ReactNode
  trend?: number[]
  trendTimestamps?: string[]
  trendTimezone?: string
}) {
  const trendColor = ok === true ? TREND_GOOD_COLOR : ok === false ? TREND_BAD_COLOR : TREND_NEUTRAL_COLOR

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div
          className={cn(
            'text-3xl font-semibold',
            ok === true && 'text-success',
            ok === false && 'text-destructive',
          )}
        >
          {value}
        </div>
        {subtitle && <div className="mt-1 text-xs text-muted-foreground">{subtitle}</div>}
        {trend && trend.length >= 2 && (
          <div className="mt-4">
            <Sparkline
              data={trend}
              timestamps={trendTimestamps}
              timezone={trendTimezone}
              color={trendColor}
              height={72}
              className="w-full"
            />
          </div>
        )}
      </CardContent>
    </Card>
  )
}
