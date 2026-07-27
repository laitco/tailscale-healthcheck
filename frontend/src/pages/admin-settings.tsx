import { useEffect, useMemo, useState } from 'react'
import { Eye, EyeOff, Info, Lock, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { TagInput } from '@/components/ui/tag-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { fetchSettings, updateSettings, pollNow, generateToken, testNotification, AdminApiError } from '@/lib/admin-api'
import { useHealthContext } from '@/lib/health-context'
import type { SettingField, SettingsResponse } from '@/lib/types'

type FieldDef = { name: string; label: string; unit?: string; help?: string; generatable?: boolean }

const GROUP_ORDER = [
  'connection', 'thresholds', 'filters', 'notifications', 'general', 'logging', 'rate_limit', 'retry', 'poll',
] as const

const GROUP_LABELS: Record<string, string> = {
  connection: 'Connection',
  thresholds: 'Health Thresholds',
  filters: 'Filters',
  notifications: 'Notifications',
  general: 'General',
  logging: 'Logging',
  rate_limit: 'Rate Limiting',
  retry: 'Retry / Backoff',
  poll: 'Polling & Audit',
}

const GROUP_DESCRIPTIONS: Record<string, string> = {
  connection: "Fields sourced from an environment variable always take precedence and can't be edited here.",
  thresholds: 'Control when devices and the overall tailnet are considered healthy.',
  filters: 'Comma-separated glob patterns (e.g. tag:prod, *.example.com). Press Enter or comma to add an entry.',
  notifications: 'Alert via an already-running Apprise API instance (apprise-api) - channel setup (Slack, email, ...) lives on that instance, not here.',
  general: 'Miscellaneous behavior settings.',
  logging: 'Application log verbosity.',
  rate_limit: 'Protect the API from excessive request volume.',
  retry: 'Backoff behavior for retried Tailscale API requests.',
  poll: 'How often data is refreshed in the background, and how long audit history is kept.',
}

const FIELDS_BY_GROUP: Record<string, FieldDef[]> = {
  connection: [
    { name: 'tailnet_domain', label: 'Tailnet domain', help: 'Your tailnet, e.g. example.ts.net or a custom domain. Devices/keys are fetched from this tailnet only.' },
    { name: 'auth_token', label: 'API access token', help: 'Static Tailscale API token, used instead of OAuth. Mutually exclusive with the OAuth client fields below.' },
    { name: 'oauth_client_id', label: 'OAuth client ID', help: 'Recommended over a static API token - auto-renews. Needs the devices:core scope, plus Keys/Auth Keys read access for /keys.' },
    { name: 'oauth_client_secret', label: 'OAuth client secret', help: 'Paired with the OAuth client ID above.' },
    { name: 'health_endpoint_token', label: 'Health endpoint token (X-Health-Token)', help: 'Optional shared secret to lock down the otherwise-public /health endpoint. Leave blank to keep /health open (default).', generatable: true },
    { name: 'api_base_url', label: 'Public base URL', help: "Used for example curl commands and \"Try it\" calls on the API docs page. Leave blank to use the current page's origin." },
    {
      name: 'tailnet_lock_enabled',
      label: 'I use Tailnet Lock',
      help: 'When on, a device needing a Tailnet Lock signature counts as unhealthy, and the Lock status is shown on the devices table and device detail page. Off by default.',
    },
    {
      name: 'lock_signer_tags',
      label: 'Tailnet Lock signer tags',
      help: "Devices with a matching tag are labeled \"Signer\" on the devices table/device detail page. There's no way to learn which devices are trusted signers from the Tailscale API itself, so this is admin-provided.",
    },
  ],
  thresholds: [
    { name: 'online_threshold_minutes', label: 'Online threshold', unit: 'minutes', help: 'A device is considered offline once its last-seen time is older than this.' },
    { name: 'key_threshold_minutes', label: 'Key threshold', unit: 'minutes', help: "A device's node key is considered expiring once it's due to expire within this many minutes." },
    { name: 'key_expiry_warning_days', label: 'Key expiry warning', unit: 'days', help: 'A tailnet API/auth key (shown on /keys) is considered unhealthy once its expiry is at or below this many days out.' },
    {
      name: 'global_healthy_threshold',
      label: 'Global healthy threshold',
      unit: 'devices (count, not %)',
      help: 'Max number of unhealthy devices tolerated before global_healthy flips to false.',
    },
    {
      name: 'global_online_healthy_threshold',
      label: 'Global online-healthy threshold',
      unit: 'devices (count, not %)',
      help: 'Max number of offline devices tolerated before global_online_healthy flips to false.',
    },
    {
      name: 'global_key_healthy_threshold',
      label: 'Global key-healthy threshold',
      unit: 'devices (count, not %)',
      help: 'Max number of devices with an expiring key tolerated before global_key_healthy flips to false.',
    },
    {
      name: 'global_update_healthy_threshold',
      label: 'Global update-healthy threshold',
      unit: 'devices (count, not %)',
      help: 'Max number of devices with an update available tolerated before global_update_healthy flips to false.',
    },
    {
      name: 'update_healthy_is_included_in_health',
      label: 'Include update health in overall health',
      help: 'When on, a device with an available update counts toward the overall healthy/unhealthy status, not just its own update_healthy field.',
    },
    {
      name: 'global_lock_healthy_threshold',
      label: 'Global lock-healthy threshold',
      unit: 'devices (count, not %)',
      help: 'Max number of devices needing a Tailnet Lock signature tolerated before global_lock_healthy flips to false. Only relevant when "I use Tailnet Lock" is on (Connection settings).',
    },
  ],
  filters: [
    { name: 'include_os', label: 'Include OS', help: 'Only count devices whose OS matches one of these patterns (e.g. linux, macOS). Wins over Exclude OS if both are set.' },
    { name: 'exclude_os', label: 'Exclude OS', help: 'Exclude devices whose OS matches one of these patterns. Ignored if Include OS is set.' },
    { name: 'include_identifier', label: 'Include identifier', help: 'Only count devices whose hostname/ID/name/machine name matches one of these patterns. Wins over Exclude identifier.' },
    { name: 'exclude_identifier', label: 'Exclude identifier', help: 'Exclude devices whose hostname/ID/name/machine name matches one of these patterns. Ignored if Include identifier is set.' },
    { name: 'include_tags', label: 'Include tags', help: 'Only count devices with at least one matching tag. Wins over Exclude tags.' },
    { name: 'exclude_tags', label: 'Exclude tags', help: 'Exclude devices with a matching tag. Ignored if Include tags is set.' },
    { name: 'include_identifier_update_healthy', label: 'Include identifier (update health)', help: 'Devices matching this identifier pattern are always treated as update_healthy, regardless of updateAvailable.' },
    { name: 'exclude_identifier_update_healthy', label: 'Exclude identifier (update health)', help: 'Same as Include identifier (update health), but by exclusion pattern instead.' },
    { name: 'include_tag_update_healthy', label: 'Include tag (update health)', help: 'Devices with a matching tag are always treated as update_healthy, regardless of updateAvailable.' },
    { name: 'exclude_tag_update_healthy', label: 'Exclude tag (update health)', help: 'Same as Include tag (update health), but by exclusion pattern instead.' },
    { name: 'include_key_type', label: 'Include key type', help: 'Only count tailnet keys whose type (api/auth) matches. Wins over Exclude key type.' },
    { name: 'exclude_key_type', label: 'Exclude key type', help: 'Exclude tailnet keys whose type matches. Ignored if Include key type is set.' },
    { name: 'include_key_description', label: 'Include key description', help: "Only count tailnet keys whose description matches. Wins over Exclude key description." },
    { name: 'exclude_key_description', label: 'Exclude key description', help: "Exclude tailnet keys whose description matches. Ignored if Include key description is set." },
  ],
  notifications: [
    { name: 'apprise_api_url', label: 'Apprise API URL', help: 'Base URL of your running apprise-api instance, e.g. http://apprise:8000. Leave blank to keep alerting off.' },
    {
      name: 'apprise_notification_urls',
      label: 'Notification URLs',
      help: 'One or more Apprise service URLs (comma-separated), e.g. tgram://bottoken/ChatID, mailto://user:pass@host, slack://... - sent straight through to the stateless Apprise API endpoint each time, no server-side config needed.',
    },
    {
      name: 'apprise_bearer_token',
      label: 'Apprise API bearer token',
      help: "Optional - only needed if your Apprise API instance itself requires bearer-token auth. Sent as an Authorization header, unrelated to the notification URLs above.",
    },
    { name: 'notification_events', label: 'Notify on', help: 'Only checked events actually send a notification. Off (unchecked) by default for all of them.' },
    {
      name: 'notify_include_tags',
      label: 'Notify: include tags',
      help: "Scopes which devices' transitions notify (device_unhealthy/device_healthy_again/device_needs_signing/device_signed only - global/poll events aren't device-scoped). Wins over Notify: exclude tags.",
    },
    { name: 'notify_exclude_tags', label: 'Notify: exclude tags', help: 'Same as Notify: include tags, but by exclusion pattern instead. Ignored if include is set.' },
  ],
  general: [
    { name: 'timezone', label: 'Timezone', help: "IANA timezone (e.g. Europe/Berlin) used for lastSeen and key-expiry timestamps shown throughout the app." },
    { name: 'http_timeout', label: 'HTTP timeout', unit: 'seconds', help: 'Timeout for outbound requests to the Tailscale API.' },
  ],
  logging: [
    { name: 'log_level', label: 'Log level', help: 'Application log verbosity. Takes effect after a process restart only.' },
    { name: 'debug_log_enabled', label: 'Capture poller activity log (shown on the Debug page)', help: 'When off, poll cycles still log normally, but nothing is persisted to the poller_log table backing the /debug page.' },
  ],
  rate_limit: [
    { name: 'rate_limit_enabled', label: 'Enable rate limiting', help: 'Master switch for the per-IP/global request rate limiter. Takes effect after a process restart only.' },
    { name: 'rate_limit_per_ip', label: 'Per-IP limit', help: 'Requests per minute allowed from a single client IP. 0 disables this specific limit.' },
    { name: 'rate_limit_global', label: 'Global limit', help: 'Requests per minute allowed across all clients/endpoints combined. Empty/0 disables this specific limit.' },
    { name: 'rate_limit_storage_url', label: 'Rate limit storage URL', help: 'Backend for shared enforcement across worker processes: file:// (default, single host), redis://host:6379/0, or empty for in-memory per-process.' },
    { name: 'rate_limit_headers_enabled', label: 'Send rate limit headers', help: 'Include standard X-RateLimit-* response headers when the limiter is active.' },
  ],
  retry: [
    { name: 'max_retries', label: 'Max retries', help: 'How many times a failed Tailscale API request is retried before giving up.' },
    { name: 'backoff_base_seconds', label: 'Backoff base', unit: 'seconds', help: 'Starting delay before the first retry; doubles each subsequent attempt up to the max below.' },
    { name: 'backoff_max_seconds', label: 'Backoff max', unit: 'seconds', help: 'Upper bound on the exponential backoff delay between retries.' },
    { name: 'backoff_jitter_seconds', label: 'Backoff jitter', unit: 'seconds', help: 'Random extra delay (0..value) added to each backoff to avoid retry storms.' },
  ],
  poll: [
    { name: 'poll_interval_seconds', label: 'Poll interval', unit: 'seconds', help: 'How often the background poller refreshes devices/tailnet keys from the Tailscale API into the database.' },
    { name: 'audit_retention_days', label: 'Audit log retention', unit: 'days', help: 'How long audit_log entries (device/key/setting/user changes) are kept before being purged.' },
    { name: 'poller_log_retention_days', label: 'Poller activity log retention', unit: 'days', help: 'How long the operational poll-cycle log (shown on /debug) is kept - separate from audit log retention above.' },
  ],
}

const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

type DraftValue = string | number | boolean

function SettingLabel({
  label,
  htmlFor,
  meta,
  help,
}: {
  label: string
  htmlFor: string
  meta: SettingField
  help?: string
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {meta.source === 'env' && (
        <Lock
          className="size-3 shrink-0 text-muted-foreground"
          aria-label={`Configured via environment variable ${meta.env_var}`}
        >
          <title>{`Configured via environment variable ${meta.env_var}`}</title>
        </Lock>
      )}
      {help && (
        <Info className="size-3 shrink-0 text-muted-foreground" aria-label={help}>
          <title>{help}</title>
        </Info>
      )}
      <label className="text-xs font-medium text-muted-foreground" htmlFor={htmlFor}>
        {label}
      </label>
      {meta.restart_required && (
        <Badge variant="outline" className="text-muted-foreground">
          Applies after restart
        </Badge>
      )}
    </div>
  )
}

function SecretInput({
  id,
  meta,
  value,
  disabled,
  onChange,
  onGenerate,
}: {
  id: string
  meta: SettingField
  value: string | undefined
  disabled: boolean
  onChange: (v: string) => void
  onGenerate?: () => void
}) {
  const [revealed, setRevealed] = useState(false)
  return (
    <div className="flex items-center gap-1.5">
      <div className="relative flex-1">
        <Input
          id={id}
          type={revealed ? 'text' : 'password'}
          placeholder={meta.configured ? '********' : 'Not set'}
          disabled={disabled}
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value)}
          className="pr-7"
        />
        <button
          type="button"
          aria-label={revealed ? 'Hide value' : 'Show value'}
          onClick={() => setRevealed((r) => !r)}
          disabled={disabled}
          className="absolute inset-y-0 right-1.5 flex items-center text-muted-foreground hover:text-foreground disabled:pointer-events-none"
        >
          {revealed ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
        </button>
      </div>
      {onGenerate && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => {
            onGenerate()
            setRevealed(true)
          }}
        >
          Generate
        </Button>
      )}
    </div>
  )
}

const FILTER_FIELD_NAMES = new Set([
  ...FIELDS_BY_GROUP.filters.map((f) => f.name),
  'lock_signer_tags', 'notify_include_tags', 'notify_exclude_tags',
])

const NOTIFICATION_EVENT_OPTIONS: { value: string; label: string }[] = [
  { value: 'device_unhealthy', label: 'Device becomes unhealthy' },
  { value: 'device_healthy_again', label: 'Device becomes healthy again' },
  { value: 'key_expiring', label: 'Tailnet key expiring soon' },
  { value: 'device_needs_signing', label: 'Device needs a Tailnet Lock signature' },
  { value: 'device_signed', label: 'Device signed under Tailnet Lock' },
  { value: 'global_unhealthy', label: 'Overall tailnet becomes unhealthy' },
  { value: 'global_healthy_restored', label: 'Overall tailnet becomes healthy again' },
  { value: 'poll_auth_error', label: "Tailscale API credentials aren't working" },
]

export default function AdminSettingsPage() {
  const { refresh } = useHealthContext()
  const [settings, setSettings] = useState<SettingsResponse | null>(null)
  const [draft, setDraft] = useState<Record<string, DraftValue>>({})
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [polling, setPolling] = useState(false)
  const [testingNotification, setTestingNotification] = useState(false)
  const [testResult, setTestResult] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)

  function load() {
    fetchSettings().then((data) => setSettings(data))
  }

  useEffect(load, [])

  const groups = useMemo(() => {
    if (!settings) return []
    return GROUP_ORDER.filter((g) => FIELDS_BY_GROUP[g]?.some((f) => settings[f.name]))
  }, [settings])

  if (!settings) {
    return <Skeleton className="h-96" />
  }

  function setDraftValue(name: string, value: DraftValue) {
    setDraft((d) => ({ ...d, [name]: value }))
  }

  async function onSave(e: React.FormEvent) {
    e.preventDefault()
    setMessage(null)
    if (Object.keys(draft).length === 0) {
      setMessage({ kind: 'success', text: 'Nothing to save.' })
      return
    }
    setSaving(true)
    try {
      const result = await updateSettings(draft)
      setDraft({})
      load()
      await refresh()
      const restartNote = result.restart_required_for?.length
        ? ` Restart required for: ${result.restart_required_for.join(', ')}.`
        : ''
      setMessage({ kind: 'success', text: `Settings saved.${restartNote}` })
    } catch (err) {
      setMessage({ kind: 'error', text: err instanceof AdminApiError ? err.message : 'Failed to save settings' })
    } finally {
      setSaving(false)
    }
  }

  async function onPollNow() {
    setPolling(true)
    try {
      await pollNow()
      load()
    } finally {
      setPolling(false)
    }
  }

  async function onTestNotification() {
    setTestingNotification(true)
    setTestResult(null)
    try {
      // Only send fields actually edited this session (in `draft`) - a
      // secret field's displayed value is masked ("********"), so falling
      // back to the saved value must happen server-side, not by resending
      // whatever's currently rendered here.
      const overrides: Record<string, string> = {}
      for (const field of ['apprise_api_url', 'apprise_notification_urls', 'apprise_bearer_token']) {
        if (field in draft) overrides[field] = String(draft[field])
      }
      await testNotification(overrides)
      setTestResult({ kind: 'success', text: 'Test notification sent - check your configured destination.' })
    } catch (err) {
      setTestResult({ kind: 'error', text: err instanceof AdminApiError ? err.message : 'Failed to send test notification' })
    } finally {
      setTestingNotification(false)
    }
  }

  function renderField(def: FieldDef) {
    const meta = settings![def.name]
    if (!meta) return null
    const disabled = meta.source === 'env'
    const id = def.name
    const draftValue = draft[def.name]

    let control: React.ReactNode
    if (meta.secret) {
      control = (
        <SecretInput
          id={id}
          meta={meta}
          value={typeof draftValue === 'string' ? draftValue : undefined}
          disabled={disabled}
          onChange={(v) => setDraftValue(def.name, v)}
          onGenerate={
            def.generatable
              ? () => {
                  generateToken()
                    .then(({ token }) => setDraftValue(def.name, token))
                    .catch(() => setMessage({ kind: 'error', text: 'Failed to generate token' }))
                }
              : undefined
          }
        />
      )
    } else if (def.name === 'log_level') {
      const current = (typeof draftValue === 'string' ? draftValue : (meta.value as string)) || 'INFO'
      control = (
        <Select value={current} onValueChange={(v) => setDraftValue(def.name, v)} disabled={disabled}>
          <SelectTrigger id={id} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {LOG_LEVELS.map((lvl) => (
              <SelectItem key={lvl} value={lvl}>
                {lvl}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )
    } else if (def.name === 'notification_events') {
      const current = (typeof draftValue === 'string' ? draftValue : String(meta.value ?? ''))
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      const toggle = (event: string) => {
        const next = current.includes(event) ? current.filter((e) => e !== event) : [...current, event]
        setDraftValue(def.name, next.join(','))
      }
      control = (
        <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
          {NOTIFICATION_EVENT_OPTIONS.map((opt) => (
            <label key={opt.value} className="flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={current.includes(opt.value)}
                onChange={() => toggle(opt.value)}
                disabled={disabled}
              />
              {opt.label}
            </label>
          ))}
        </div>
      )
    } else if (meta.type === 'bool') {
      const checked = typeof draftValue === 'boolean' ? draftValue : Boolean(meta.value)
      control = (
        <div className="flex h-7 items-center gap-2">
          <Switch id={id} checked={checked} onCheckedChange={(v) => setDraftValue(def.name, v)} disabled={disabled} />
        </div>
      )
    } else if (FILTER_FIELD_NAMES.has(def.name)) {
      const current = typeof draftValue === 'string' ? draftValue : String(meta.value ?? '')
      control = (
        <TagInput
          value={current}
          onChange={(v) => setDraftValue(def.name, v)}
          placeholder="Add a pattern…"
          disabled={disabled}
        />
      )
    } else if (meta.type === 'int' || meta.type === 'float') {
      const current = typeof draftValue !== 'undefined' ? String(draftValue) : String(meta.value ?? '')
      control = (
        <Input
          id={id}
          type="number"
          min={0}
          step={meta.type === 'int' ? 1 : 0.1}
          disabled={disabled}
          value={current}
          onChange={(e) => setDraftValue(def.name, meta.type === 'int' ? Number(e.target.value) : parseFloat(e.target.value))}
        />
      )
    } else {
      const current = typeof draftValue === 'string' ? draftValue : String(meta.value ?? '')
      control = (
        <Input
          id={id}
          disabled={disabled}
          value={current}
          onChange={(e) => setDraftValue(def.name, e.target.value)}
        />
      )
    }

    return (
      <div className="space-y-1" key={def.name}>
        <SettingLabel label={def.label} htmlFor={id} meta={meta} help={def.help} />
        {control}
        {def.unit && <p className="text-[0.7rem] text-muted-foreground">Unit: {def.unit}</p>}
      </div>
    )
  }

  const dirtyCount = Object.keys(draft).length

  return (
    <div className="space-y-4">
      <form onSubmit={onSave} className="space-y-4">
        <div className="sticky top-0 z-10 -mx-4 -mt-4 flex flex-wrap items-center justify-between gap-3 border-b bg-background/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:-mt-6 sm:px-6">
          <div>
            <h2 className="text-sm font-semibold">Settings</h2>
            <p className="text-xs text-muted-foreground">
              {dirtyCount > 0
                ? `${dirtyCount} unsaved change${dirtyCount === 1 ? '' : 's'}`
                : 'All changes saved'}
            </p>
          </div>
          <Button type="submit" disabled={saving || dirtyCount === 0}>
            {saving ? 'Saving…' : dirtyCount > 0 ? `Save ${dirtyCount} change${dirtyCount === 1 ? '' : 's'}` : 'Save changes'}
          </Button>
        </div>

        {message && (
          <div
            className={
              message.kind === 'error'
                ? 'rounded-md border border-destructive/50 bg-destructive/10 p-2 text-xs text-destructive'
                : 'rounded-md border border-primary/30 bg-primary/10 p-2 text-xs text-primary'
            }
          >
            {message.text}
          </div>
        )}

        {settings._meta.last_poll_auth_error && (
          <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-destructive">
            <p className="font-medium">Unable to reach the Tailscale API</p>
            <p className="text-xs text-destructive/90">
              The configured auth token or OAuth credentials appear to be missing, incorrect, or revoked. Check the
              fields in the Connection group below.
              {settings._meta.last_poll_error ? ` (${settings._meta.last_poll_error})` : ''}
            </p>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {groups.map((group) => (
            <Card key={group}>
              <CardHeader>
                <CardTitle>{GROUP_LABELS[group]}</CardTitle>
                {GROUP_DESCRIPTIONS[group] && <CardDescription>{GROUP_DESCRIPTIONS[group]}</CardDescription>}
              </CardHeader>
              <CardContent className="grid gap-3">
                {FIELDS_BY_GROUP[group].map((def) => renderField(def))}
                {group === 'notifications' && (
                  <div className="space-y-2 border-t pt-3">
                    <Button type="button" variant="outline" size="sm" onClick={onTestNotification} disabled={testingNotification}>
                      <RefreshCw className={testingNotification ? 'animate-spin' : ''} />
                      Send test notification
                    </Button>
                    {testResult && (
                      <p className={`text-xs ${testResult.kind === 'error' ? 'text-destructive' : 'text-success'}`}>
                        {testResult.text}
                      </p>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      </form>

      <Card>
        <CardHeader>
          <CardTitle>Background polling</CardTitle>
          <CardDescription>
            Devices and tailnet keys refresh every {settings._meta.poll_interval_seconds}s.
            {settings._meta.last_polled_at
              ? ` Last polled: ${new Date(settings._meta.last_polled_at).toLocaleString()}.`
              : ' Not polled yet.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" onClick={onPollNow} disabled={polling}>
            <RefreshCw className={polling ? 'animate-spin' : ''} />
            Poll now
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
