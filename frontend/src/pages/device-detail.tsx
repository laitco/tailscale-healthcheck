import { useEffect, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { StatusBadge } from '@/components/status-badge'
import { Badge } from '@/components/ui/badge'
import { fetchDeviceByIdentifier, ApiError } from '@/lib/api'
import type { Device } from '@/lib/types'
import NotFoundPage from '@/pages/not-found'
import { Alert } from '@/components/ui/alert'
import { formatDateTime } from '@/lib/format'
import { useTimezone } from '@/lib/health-context'

export default function DeviceDetailPage() {
  const { identifier = '' } = useParams()
  const [device, setDevice] = useState<Device | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const timezone = useTimezone()

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setNotFound(false)
    setError(null)
    fetchDeviceByIdentifier(identifier)
      .then((d) => {
        if (!cancelled) setDevice(d)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true)
        } else {
          setError(err instanceof Error ? err.message : 'Failed to load device')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [identifier])

  if (notFound) return <NotFoundPage />

  if (loading) {
    return <Skeleton className="h-64" />
  }

  if (error || !device) {
    return (
      <Alert>
        Failed to load device: {error}
      </Alert>
    )
  }

  return (
    <div className="space-y-4">
      <Link to="/devices" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ChevronLeft className="size-4" />
        Devices
      </Link>
      <Card>
        <CardHeader>
          <CardTitle>{device.machineName}</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2">
          <Field label="Machine" value={device.machineName} />
          <Field label="OS" value={device.os} />
          <Field label="Client Version" value={device.clientVersion || '—'} />
          <Field label="Hostname" value={device.hostname} />
          <Field label="Last Seen" value={formatDateTime(device.lastSeen, timezone)} />
          <Field label="Tags" value={(device.tags || []).join(', ') || '—'} />
          <Field
            label="Update"
            value={<StatusBadge ok={device.update_healthy} trueText="OK" falseText="Needed" />}
          />
          <Field
            label="Key"
            value={
              <span className="inline-flex items-center gap-2">
                <StatusBadge ok={device.key_healthy} trueText="Valid" falseText="Expiring" />
                {device.keyExpiryDisabled && <span className="text-xs text-muted-foreground">(expiry disabled)</span>}
                {device.key_days_to_expire != null && (
                  <span className="text-xs text-muted-foreground">(~{device.key_days_to_expire} days)</span>
                )}
              </span>
            }
          />
          {device.tailnetLockEnabled && (
            <Field
              label="Tailnet Lock"
              value={
                <span className="inline-flex items-center gap-2">
                  <StatusBadge
                    ok={!device.tailnetLockError}
                    trueText="Signed"
                    falseText="Locked out"
                    title={device.tailnetLockError || undefined}
                  />
                  {device.tailnetLockError && <span className="text-xs text-muted-foreground">({device.tailnetLockError})</span>}
                  {device.isLockSigner && (
                    <Badge variant="outline" title="Tagged as a trusted Tailnet Lock signer">
                      Signer
                    </Badge>
                  )}
                </span>
              }
            />
          )}
          <Field
            label="Overall Health"
            value={<StatusBadge ok={device.healthy} trueText="Healthy" falseText="Unhealthy" />}
          />
          {device.keyExpiryTimestamp && (
            <Field label="Key Expiry" value={formatDateTime(device.keyExpiryTimestamp, timezone)} />
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="text-sm">{value}</span>
    </div>
  )
}
