import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AdminAuthLayout } from '@/components/admin-auth-layout'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchAdminStatus, submitSetup, AdminApiError, type AdminStatus } from '@/lib/admin-api'

export default function AdminSetupPage() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<AdminStatus | null>(null)
  const [tailnetDomain, setTailnetDomain] = useState('')
  const [authMode, setAuthMode] = useState<'token' | 'oauth'>('oauth')
  const [authToken, setAuthToken] = useState('')
  const [oauthClientId, setOauthClientId] = useState('')
  const [oauthClientSecret, setOauthClientSecret] = useState('')
  const [apiBaseUrl, setApiBaseUrl] = useState('')
  const [tailnetLockEnabled, setTailnetLockEnabled] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    fetchAdminStatus()
      .then(setStatus)
      .catch(() =>
        setStatus({ tailnet_configured: false, auth_configured: false, has_users: false, authenticated: false, version: 'unknown' }),
      )
  }, [])

  if (!status) {
    return (
      <AdminAuthLayout title="Setup">
        <Skeleton className="h-40" />
      </AdminAuthLayout>
    )
  }

  const needsTailnetDomain = !status.tailnet_configured
  const needsConnection = needsTailnetDomain || !status.auth_configured
  const needsUser = !status.has_users

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    if (needsUser && password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    const payload: Record<string, string> = {}
    if (needsConnection) {
      payload.tailnet_domain = tailnetDomain
      payload.auth_mode = authMode
      if (authMode === 'token') {
        payload.auth_token = authToken
      } else {
        payload.oauth_client_id = oauthClientId
        payload.oauth_client_secret = oauthClientSecret
      }
      if (apiBaseUrl.trim()) {
        payload.api_base_url = apiBaseUrl.trim()
      }
      payload.tailnet_lock_enabled = tailnetLockEnabled ? 'true' : 'false'
    }
    if (needsUser) {
      payload.username = username
      payload.password = password
    }

    setSubmitting(true)
    try {
      const result = await submitSetup(payload)
      if (result.setup_complete) {
        navigate('/admin/login')
      } else {
        const refreshed = await fetchAdminStatus()
        setStatus(refreshed)
      }
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : 'Setup failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AdminAuthLayout
      title="Welcome"
      description="Let's get this instance connected to your tailnet before you sign in."
    >
      <form className="space-y-4" onSubmit={onSubmit}>
        {error && (
          <div className="rounded-md border border-destructive/50 bg-destructive/10 p-2 text-xs text-destructive">
            {error}
          </div>
        )}

        {needsConnection && (
          <fieldset className="space-y-3">
            <legend className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Tailscale connection
            </legend>
            {needsTailnetDomain ? (
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="tailnet_domain">
                  Tailnet domain
                </label>
                <Input
                  id="tailnet_domain"
                  placeholder="your-tailnet.ts.net"
                  value={tailnetDomain}
                  onChange={(e) => setTailnetDomain(e.target.value)}
                  required
                />
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Tailnet domain is already configured via environment variable - just add credentials below.
              </p>
            )}
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Authentication method</label>
              <Select value={authMode} onValueChange={(v) => setAuthMode(v as 'token' | 'oauth')}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="oauth">OAuth client (recommended)</SelectItem>
                  <SelectItem value="token">API access token</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {authMode === 'token' ? (
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="auth_token">
                  API access token
                </label>
                <Input
                  id="auth_token"
                  type="password"
                  value={authToken}
                  onChange={(e) => setAuthToken(e.target.value)}
                  required
                />
              </div>
            ) : (
              <>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-muted-foreground" htmlFor="oauth_client_id">
                    OAuth client ID
                  </label>
                  <Input
                    id="oauth_client_id"
                    value={oauthClientId}
                    onChange={(e) => setOauthClientId(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-muted-foreground" htmlFor="oauth_client_secret">
                    OAuth client secret
                  </label>
                  <Input
                    id="oauth_client_secret"
                    type="password"
                    value={oauthClientSecret}
                    onChange={(e) => setOauthClientSecret(e.target.value)}
                    required
                  />
                </div>
              </>
            )}
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="api_base_url">
                Public base URL <span className="text-muted-foreground">(optional)</span>
              </label>
              <Input
                id="api_base_url"
                placeholder="https://healthcheck.example.com"
                value={apiBaseUrl}
                onChange={(e) => setApiBaseUrl(e.target.value)}
              />
              <p className="text-[0.7rem] text-muted-foreground">
                Used for example API URLs and the API docs page. Leave blank to use the current page's origin.
              </p>
            </div>
            <label className="flex items-start gap-2 text-xs">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={tailnetLockEnabled}
                onChange={(e) => setTailnetLockEnabled(e.target.checked)}
              />
              <span>
                <span className="font-medium text-foreground">I use Tailnet Lock</span>
                <span className="block text-muted-foreground">
                  When on, a device needing a Tailnet Lock signature counts as unhealthy. Off by default - safe to
                  leave unchecked if you don't use Tailnet Lock, and changeable later in Settings.
                </span>
              </span>
            </label>
          </fieldset>
        )}

        {needsUser && (
          <fieldset className="space-y-3">
            <legend className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Admin account
            </legend>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="username">
                Username
              </label>
              <Input id="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="new-password">
                Password
              </label>
              <Input
                id="new-password"
                type="password"
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="confirm-password">
                Confirm password
              </label>
              <Input
                id="confirm-password"
                type="password"
                minLength={8}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
            </div>
          </fieldset>
        )}

        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? 'Saving…' : 'Continue'}
        </Button>
      </form>
    </AdminAuthLayout>
  )
}
