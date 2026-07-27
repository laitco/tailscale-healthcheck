import { useEffect, useRef, useState } from 'react'
import { Play } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { getApiBaseUrl, fetchSettings } from '@/lib/admin-api'

interface EndpointDef {
  method: 'GET'
  path: string
  group: string
  description: string
  params?: { name: string; kind: 'path' | 'query'; description: string }[]
  authNote: string
  example: unknown
  hasIdentifier?: boolean
}

function slugFor(path: string): string {
  return path
    .replace(/^\//, '')
    .replace(/[<>]/g, '')
    .replace(/\//g, '-')
}

const ENDPOINTS: EndpointDef[] = [
  {
    method: 'GET',
    path: '/health',
    group: 'Health',
    description: 'Overall device health summary and aggregate metrics for the tailnet.',
    authNote:
      'Unauthenticated by default. If HEALTH_ENDPOINT_TOKEN is configured, requests must include an X-Health-Token header matching it.',
    example: {
      devices: [
        {
          id: 'n123456CNTRL',
          hostname: 'web-01',
          device: 'web-01',
          machineName: 'web-01',
          os: 'linux',
          clientVersion: '1.72.0-t1234abcd',
          lastSeen: '2026-07-26T08:12:00Z',
          tags: ['tag:prod'],
          healthy: true,
          online: true,
          updateAvailable: false,
          update_healthy: true,
          keyExpiryDisabled: false,
          keyExpiryTimestamp: '2026-09-01T00:00:00Z',
          key_healthy: true,
          key_days_to_expire: 37,
        },
      ],
      metrics: {
        global_healthy: true,
        global_online_healthy: true,
        global_key_healthy: true,
        global_update_healthy: true,
        counter_healthy_online_true: 12,
        counter_healthy_online_false: 0,
        counter_key_healthy_true: 12,
        counter_key_healthy_false: 0,
        counter_update_healthy_true: 11,
        counter_update_healthy_false: 1,
      },
      poll_meta: { last_polled_at: '2026-07-26T08:12:03Z', poll_interval_seconds: 60 },
    },
  },
  {
    method: 'GET',
    path: '/health/<identifier>',
    group: 'Health',
    description: 'Health for a single device, matched by hostname, id, name, or machine name.',
    params: [{ name: 'identifier', kind: 'path', description: 'Hostname, device id, name, or machine name.' }],
    authNote: 'Requires an authenticated session (login).',
    hasIdentifier: true,
    example: {
      device: {
        id: 'n123456CNTRL',
        hostname: 'web-01',
        device: 'web-01',
        machineName: 'web-01',
        os: 'linux',
        clientVersion: '1.72.0-t1234abcd',
        lastSeen: '2026-07-26T08:12:00Z',
        tags: ['tag:prod'],
        healthy: true,
        online: true,
        updateAvailable: false,
        update_healthy: true,
        keyExpiryDisabled: false,
        keyExpiryTimestamp: '2026-09-01T00:00:00Z',
        key_healthy: true,
        key_days_to_expire: 37,
      },
    },
  },
  {
    method: 'GET',
    path: '/health/healthy',
    group: 'Health',
    description: 'Same shape as /health, filtered to only devices currently considered healthy.',
    authNote: 'Requires an authenticated session (login).',
    example: {
      devices: [{ id: 'n123456CNTRL', hostname: 'web-01', healthy: true, online: true }],
      metrics: { global_healthy: true, counter_healthy_online_true: 12, counter_healthy_online_false: 0 },
    },
  },
  {
    method: 'GET',
    path: '/health/unhealthy',
    group: 'Health',
    description: 'Same shape as /health, filtered to only devices currently considered unhealthy.',
    authNote: 'Requires an authenticated session (login).',
    example: {
      devices: [{ id: 'n789012CNTRL', hostname: 'legacy-box', healthy: false, online: false }],
      metrics: { global_healthy: false, counter_healthy_online_true: 11, counter_healthy_online_false: 1 },
    },
  },
  {
    method: 'GET',
    path: '/keys',
    group: 'Keys',
    description: 'Tailnet API and auth key health, including expiry status.',
    authNote: 'Requires an authenticated session (login).',
    example: {
      keys: [
        {
          id: 'k123456CNTRL',
          description: 'ci-deploy',
          keyType: 'auth',
          created: '2026-01-01T00:00:00Z',
          expires: '2026-08-01T00:00:00Z',
          key_healthy: true,
          key_days_to_expire: 6,
        },
      ],
      metrics: {
        tailnet_configured: true,
        has_keys: true,
        global_keys_healthy: true,
        counter_key_healthy_true: 1,
        total_keys: 1,
      },
    },
  },
  {
    method: 'GET',
    path: '/health/cache/invalidate',
    group: 'Operations',
    description: 'Clears the response cache and triggers an immediate poll of the Tailscale API.',
    authNote: 'Requires an authenticated session (login).',
    example: { ok: true },
  },
]

const GROUPS = Array.from(new Set(ENDPOINTS.map((e) => e.group)))

interface TryState {
  loading: boolean
  status?: number
  body?: string
  error?: string
}

// Only /health (and its trailing-slash form /health/) is ever unauthenticated by
// default, so it's the only endpoint the health-endpoint-token field applies to.
const HEALTH_TOKEN_ENDPOINTS = new Set(['/health'])

export default function ApiDocsPage() {
  const [baseUrl, setBaseUrl] = useState<string | null>(null)
  const [identifierInputs, setIdentifierInputs] = useState<Record<string, string>>({})
  const [tryStates, setTryStates] = useState<Record<string, TryState>>({})
  const [healthTokenConfigured, setHealthTokenConfigured] = useState(false)
  const [healthTokenInputs, setHealthTokenInputs] = useState<Record<string, string>>({})
  const [activeSlug, setActiveSlug] = useState<string>(slugFor(ENDPOINTS[0].path))
  const sectionRefs = useRef<Map<string, HTMLElement>>(new Map())

  useEffect(() => {
    getApiBaseUrl().then(setBaseUrl)
    fetchSettings()
      .then((settings) => setHealthTokenConfigured(Boolean(settings.health_endpoint_token?.configured)))
      .catch(() => {
        // best-effort only; field simply won't show if this fails
      })
  }, [])

  // Scroll-spy: highlight the nav entry for whichever section is nearest the top
  // of the viewport. Falls back gracefully to a static (non-highlighted) list if
  // IntersectionObserver ever fails to report anything.
  useEffect(() => {
    const elements = Array.from(sectionRefs.current.values())
    if (elements.length === 0) return
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting)
        if (visible.length === 0) return
        visible.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        const slug = visible[0].target.getAttribute('data-slug')
        if (slug) setActiveSlug(slug)
      },
      { rootMargin: '-72px 0px -70% 0px', threshold: 0 },
    )
    elements.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [baseUrl])

  if (baseUrl === null) {
    return <Skeleton className="h-96" />
  }

  function pathFor(endpoint: EndpointDef): string {
    if (!endpoint.hasIdentifier) return endpoint.path
    const identifier = identifierInputs[endpoint.path]?.trim()
    if (!identifier) return endpoint.path
    return `/health/${encodeURIComponent(identifier)}`
  }

  async function tryIt(endpoint: EndpointDef) {
    const key = endpoint.path
    if (endpoint.hasIdentifier && !identifierInputs[key]?.trim()) {
      setTryStates((s) => ({ ...s, [key]: { loading: false, error: 'Enter a device identifier first.' } }))
      return
    }
    setTryStates((s) => ({ ...s, [key]: { loading: true } }))
    const url = `${baseUrl}${pathFor(endpoint)}`
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (HEALTH_TOKEN_ENDPOINTS.has(endpoint.path)) {
      const token = healthTokenInputs[endpoint.path]?.trim()
      if (token) headers['X-Health-Token'] = token
    }
    try {
      const res = await fetch(url, { headers })
      let body: string
      try {
        body = JSON.stringify(await res.json(), null, 2)
      } catch {
        body = await res.text()
      }
      setTryStates((s) => ({ ...s, [key]: { loading: false, status: res.status, body } }))
    } catch (err) {
      setTryStates((s) => ({
        ...s,
        [key]: { loading: false, error: err instanceof Error ? err.message : 'Request failed' },
      }))
    }
  }

  function jumpTo(slug: string) {
    const el = sectionRefs.current.get(slug)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      setActiveSlug(slug)
    }
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[14rem_1fr]">
      {/* Left: in-page navigation */}
      <nav className="lg:sticky lg:top-4 lg:h-fit">
        <div className="mb-3 rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
          Base URL
          <div className="mt-1 truncate font-mono text-[0.7rem] text-foreground" title={baseUrl}>
            {baseUrl}
          </div>
        </div>
        <div className="flex gap-4 overflow-x-auto pb-2 lg:block lg:space-y-4 lg:overflow-visible lg:pb-0">
          {GROUPS.map((group) => (
            <div key={group} className="shrink-0 lg:shrink">
              <p className="mb-1 text-[0.7rem] font-semibold uppercase tracking-wide text-muted-foreground">
                {group}
              </p>
              <ul className="space-y-0.5">
                {ENDPOINTS.filter((e) => e.group === group).map((e) => {
                  const slug = slugFor(e.path)
                  const active = activeSlug === slug
                  return (
                    <li key={e.path}>
                      <a
                        href={`#${slug}`}
                        onClick={(ev) => {
                          ev.preventDefault()
                          jumpTo(slug)
                        }}
                        className={cn(
                          'block whitespace-nowrap rounded-md px-2 py-1 font-mono text-xs transition-colors',
                          active
                            ? 'bg-primary/10 font-medium text-primary'
                            : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                        )}
                      >
                        {e.path}
                      </a>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
        </div>
      </nav>

      {/* Middle + right: reference content */}
      <div className="min-w-0 space-y-10">
        {GROUPS.map((group) => (
          <section key={group} className="space-y-6">
            <div>
              <h2 className="text-lg font-semibold tracking-tight">{group}</h2>
              <Separator className="mt-2" />
            </div>

            {ENDPOINTS.filter((e) => e.group === group).map((endpoint) => {
              const slug = slugFor(endpoint.path)
              const state = tryStates[endpoint.path]
              return (
                <div
                  key={endpoint.path}
                  id={slug}
                  data-slug={slug}
                  ref={(el) => {
                    if (el) sectionRefs.current.set(slug, el)
                    else sectionRefs.current.delete(slug)
                  }}
                  className="scroll-mt-20"
                >
                  <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
                    {/* Middle: description, params, notes */}
                    <div className="space-y-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge>{endpoint.method}</Badge>
                        <h3 className="font-mono text-base font-semibold">{endpoint.path}</h3>
                      </div>
                      <p className="text-sm text-muted-foreground">{endpoint.description}</p>
                      <p className="text-xs text-muted-foreground">{endpoint.authNote}</p>

                      {endpoint.params && endpoint.params.length > 0 && (
                        <div className="space-y-1">
                          <p className="text-xs font-medium text-muted-foreground">Parameters</p>
                          <div className="overflow-x-auto rounded-md border">
                            <table className="w-full text-xs/relaxed">
                              <thead>
                                <tr className="border-b bg-muted/50 text-left">
                                  <th className="px-2 py-1 font-medium">Param</th>
                                  <th className="px-2 py-1 font-medium">Kind</th>
                                  <th className="px-2 py-1 font-medium">Description</th>
                                </tr>
                              </thead>
                              <tbody>
                                {endpoint.params.map((p) => (
                                  <tr key={p.name} className="border-b last:border-0">
                                    <td className="px-2 py-1 font-mono">{p.name}</td>
                                    <td className="px-2 py-1">{p.kind}</td>
                                    <td className="px-2 py-1 text-muted-foreground">{p.description}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}

                      <div className="space-y-1">
                        <p className="text-xs font-medium text-muted-foreground">curl</p>
                        <pre className="overflow-x-auto rounded-md border bg-muted/30 p-2 font-mono text-[0.7rem]">
                          curl {baseUrl}
                          {pathFor(endpoint)}
                        </pre>
                      </div>
                    </div>

                    {/* Right: interactive try-it */}
                    <Card>
                      <CardHeader>
                        <CardTitle className="text-sm text-muted-foreground">Try it</CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        <div className="flex flex-wrap items-center gap-2">
                          {endpoint.hasIdentifier && (
                            <Input
                              placeholder="Device identifier, e.g. web-01"
                              className="max-w-xs"
                              value={identifierInputs[endpoint.path] ?? ''}
                              onChange={(e) =>
                                setIdentifierInputs((s) => ({ ...s, [endpoint.path]: e.target.value }))
                              }
                            />
                          )}
                          {healthTokenConfigured && HEALTH_TOKEN_ENDPOINTS.has(endpoint.path) && (
                            <Input
                              placeholder="X-Health-Token"
                              className="max-w-xs"
                              value={healthTokenInputs[endpoint.path] ?? ''}
                              onChange={(e) =>
                                setHealthTokenInputs((s) => ({ ...s, [endpoint.path]: e.target.value }))
                              }
                            />
                          )}
                          <Button variant="outline" onClick={() => tryIt(endpoint)} disabled={state?.loading}>
                            <Play />
                            {state?.loading ? 'Requesting…' : 'Try it'}
                          </Button>
                        </div>

                        <div className="space-y-1">
                          <p className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                            {state && (state.body || state.error) ? (
                              <>
                                Response
                                <Badge variant="default">
                                  Live{state.status !== undefined ? ` (${state.status})` : ''}
                                </Badge>
                              </>
                            ) : (
                              <>
                                Response
                                <Badge variant="outline">Example</Badge>
                              </>
                            )}
                          </p>
                          <pre className="max-h-80 overflow-auto rounded-md border bg-muted/30 p-2 font-mono text-[0.7rem]">
                            {state && (state.body || state.error)
                              ? (state.error ?? state.body)
                              : JSON.stringify(endpoint.example, null, 2)}
                          </pre>
                        </div>
                      </CardContent>
                    </Card>
                  </div>
                </div>
              )
            })}
          </section>
        ))}
      </div>
    </div>
  )
}
