import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { MetricCard } from '@/components/metric-card'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { useHealthContext, useTimezone } from '@/lib/health-context'
import { fetchMetricsHistory, type MetricsHistoryEntry } from '@/lib/admin-api'
import { Alert } from '@/components/ui/alert'

export default function OverviewPage() {
  const { health, keys, loading, error, loadedAt } = useHealthContext()
  const [history, setHistory] = useState<MetricsHistoryEntry[]>([])
  // Comes straight off /health's poll_meta now - this page used to fetch the
  // entire (admin-only) /admin/api/settings payload just to read one string.
  const timezone = useTimezone()

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
      <Alert>
        Failed to load overview: {error}
      </Alert>
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
        <Alert className="flex flex-wrap items-center justify-between gap-3">
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
        </Alert>
      )}
      {!pollMeta?.last_poll_auth_error && pollMeta?.last_poll_ok === false && (
        <Alert className="flex flex-wrap items-center justify-between gap-3">
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
        </Alert>
      )}

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-3">
        <MetricCard
          title="Overall Health"
          value={metrics.global_healthy ? 'Healthy' : 'Issues'}
          subtitle={`${metrics.counter_healthy_false} issue${metrics.counter_healthy_false === 1 ? '' : 's'} · trend below`}
          ok={metrics.global_healthy}
          // Plot the positive (healthy) count, same convention as every
          // other tile below (up = good) - keeps all trend charts reading
          // the same way at a glance, even though the headline above is
          // framed as "Healthy"/"Issues" rather than a raw count.
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
