import { MetricCard } from '@/components/metric-card'
import { Skeleton } from '@/components/ui/skeleton'
import { useHealthContext } from '@/lib/health-context'
import { useNow } from '@/lib/use-now'
import { relativeTime } from '@/lib/format'

export default function OverviewPage() {
  const { health, keys, loading, error, loadedAt } = useHealthContext()
  const now = useNow()

  if (loading && !health) {
    return (
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
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

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <MetricCard title="Overall Health" value={metrics.global_healthy ? 'Healthy' : 'Issues'} ok={metrics.global_healthy} />
        <MetricCard
          title="Devices Online"
          value={`${metrics.counter_healthy_online_true} / ${metrics.counter_healthy_online_true + metrics.counter_healthy_online_false}`}
          ok={metrics.global_online_healthy}
        />
        <MetricCard
          title="Devices Key Valid"
          value={`${metrics.counter_key_healthy_true} / ${metrics.counter_key_healthy_true + metrics.counter_key_healthy_false}`}
          ok={metrics.global_key_healthy}
        />
        <MetricCard
          title="Devices Up to Date"
          value={`${metrics.counter_update_healthy_true} / ${metrics.counter_update_healthy_true + metrics.counter_update_healthy_false}`}
          ok={metrics.global_update_healthy}
        />
        <MetricCard
          title="Data Source"
          value={health?.cache_meta?.hit ? `Cache (${health.cache_meta.backend})` : 'Fresh'}
          subtitle={
            <span>
              {health?.cache_meta?.hit && health.cache_meta.ttl_seconds != null && loadedAt && (
                <>TTL ~{Math.max(0, health.cache_meta.ttl_seconds - Math.floor((now - loadedAt) / 1000))}s • </>
              )}
              {loadedAt ? relativeTime(new Date(loadedAt).toISOString()) : ''}
            </span>
          }
        />
      </section>

      {keyMetrics && (
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
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
          />
        </section>
      )}
    </div>
  )
}
