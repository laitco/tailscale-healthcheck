import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { MetricCard } from '@/components/metric-card'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { useHealthContext } from '@/lib/health-context'
import { fetchMetricsHistory, fetchSettings, type MetricsHistoryEntry } from '@/lib/admin-api'

export default function OverviewPage() {
  const { health, keys, loading, error, loadedAt } = useHealthContext()
  const [history, setHistory] = useState<MetricsHistoryEntry[]>([])
  const [timezone, setTimezone] = useState<string | undefined>(undefined)

  // Trend sparklines are a bonus on top of the live counts above them - fetch the
  // last 24h of poller history once on mount and again whenever the health data
  // refreshes, so the sparklines stay roughly in step with the numbers.
  useEffect(() => {
    let cancelled = false
    fetchMetricsHistory(24)
      .then((res) => {
        if (!cancelled) setHistory(res.entries)
      })
      .catch(() => {
        // best-effort only; tiles fall back to a plain number if this fails
      })
    return () => {
      cancelled = true
    }
  }, [loadedAt])

  // Fetch the configured timezone once so trend chart axis labels can be rendered
  // in local (tailnet-configured) time rather than the viewer's browser timezone.
  useEffect(() => {
    let cancelled = false
    fetchSettings()
      .then((res) => {
        const tz = res.timezone?.value
        if (!cancelled && typeof tz === 'string' && tz) setTimezone(tz)
      })
      .catch(() => {
        // best-effort only; falls back to browser timezone
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (loading && !health) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-48" />
        ))}
      </div>
    )
  }

  if (error && !health) {
    return (
      <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-destructive">
        Failed to load overview: {error}
      </div>
    )
  }

  const metrics = health!.metrics
  const keyMetrics = keys?.metrics
  const pollMeta = health!.poll_meta

  const trend = (pick: (entry: MetricsHistoryEntry) => number): number[] => history.map(pick)
  const timestamps = history.map((e) => e.occurred_at)

  return (
    <div className="space-y-6">
      {pollMeta?.last_poll_auth_error && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-destructive/50 bg-destructive/10 p-4 text-destructive">
          <div>
            <p className="font-medium">Unable to reach the Tailscale API</p>
            <p className="text-xs text-destructive/90">
              The configured auth token or OAuth credentials appear to be missing, incorrect, or revoked.
              {pollMeta.last_poll_error ? ` (${pollMeta.last_poll_error})` : ''}
            </p>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link to="/admin/settings">Check credentials</Link>
          </Button>
        </div>
      )}
      {!pollMeta?.last_poll_auth_error && pollMeta?.last_poll_ok === false && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-destructive/50 bg-destructive/10 p-4 text-destructive">
          <div>
            <p className="font-medium">Unable to reach the Tailscale API</p>
            <p className="text-xs text-destructive/90">
              Check network connectivity and the configured tailnet domain.
              {pollMeta.last_poll_error ? ` (${pollMeta.last_poll_error})` : ''}
            </p>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link to="/admin/settings">Review settings</Link>
          </Button>
        </div>
      )}

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-3">
        <MetricCard
          title="Overall Health"
          value={metrics.global_healthy ? 'Healthy' : 'Issues'}
          ok={metrics.global_healthy}
          trend={trend((e) => e.counter_healthy_true)}
          trendTimestamps={timestamps}
          trendTimezone={timezone}
        />
        <MetricCard
          title="Devices Online"
          value={`${metrics.counter_healthy_online_true} / ${metrics.counter_healthy_online_true + metrics.counter_healthy_online_false}`}
          ok={metrics.global_online_healthy}
          trend={trend((e) => e.counter_healthy_online_true)}
          trendTimestamps={timestamps}
          trendTimezone={timezone}
        />
        <MetricCard
          title="Devices Key Valid"
          value={`${metrics.counter_key_healthy_true} / ${metrics.counter_key_healthy_true + metrics.counter_key_healthy_false}`}
          ok={metrics.global_key_healthy}
          trend={trend((e) => e.counter_key_healthy_true)}
          trendTimestamps={timestamps}
          trendTimezone={timezone}
        />
        <MetricCard
          title="Devices Up to Date"
          value={`${metrics.counter_update_healthy_true} / ${metrics.counter_update_healthy_true + metrics.counter_update_healthy_false}`}
          ok={metrics.global_update_healthy}
          trend={trend((e) => e.counter_update_healthy_true)}
          trendTimestamps={timestamps}
          trendTimezone={timezone}
        />
        {keyMetrics && (
          <MetricCard
            title="Tailnet Keys"
            value={
              keyMetrics.keys_error
                ? 'Unavailable'
                : !keyMetrics.tailnet_configured
                  ? 'Not Configured'
                  : `${keyMetrics.counter_key_healthy_true} / ${keyMetrics.total_keys}`
            }
            ok={keyMetrics.keys_error || !keyMetrics.tailnet_configured ? undefined : keyMetrics.global_keys_healthy}
            trend={
              keyMetrics.keys_error || !keyMetrics.tailnet_configured
                ? undefined
                : trend((e) => e.keys_counter_healthy_true)
            }
            trendTimestamps={timestamps}
            trendTimezone={timezone}
          />
        )}
      </section>
    </div>
  )
}
