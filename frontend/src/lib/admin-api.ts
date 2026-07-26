import type { SettingsResponse } from '@/lib/types'

export type AdminStatus = {
  tailnet_configured: boolean
  auth_configured: boolean
  has_users: boolean
  authenticated: boolean
  version: string
}

export type AdminSettings = SettingsResponse

export type AdminUser = {
  id: number
  username: string
  created_at: string
  last_login_at: string | null
}

export type AuditEntry = {
  id: number
  occurred_at: string
  entity_type: string
  entity_id: string
  entity_name: string
  action: string
  changes: unknown
  actor: string | null
}

class AdminApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...(init?.headers || {}) },
  })
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    // no body
  }
  if (!res.ok) {
    const message = (body as { error?: string } | null)?.error || `Request failed with status ${res.status}`
    throw new AdminApiError(message, res.status)
  }
  return body as T
}

export function fetchAdminStatus(): Promise<AdminStatus> {
  return request('/admin/api/status')
}

export function submitSetup(payload: Record<string, string>): Promise<{ setup_complete: boolean }> {
  return request('/admin/api/setup', { method: 'POST', body: JSON.stringify(payload) })
}

export function login(username: string, password: string): Promise<{ ok: boolean; mfa_required?: boolean }> {
  return request('/admin/api/login', { method: 'POST', body: JSON.stringify({ username, password }) })
}

export function loginMfa(payload: { code?: string; recovery_code?: string }): Promise<{ ok: boolean; username: string }> {
  return request('/admin/api/login/mfa', { method: 'POST', body: JSON.stringify(payload) })
}

export function logout(): Promise<{ ok: boolean }> {
  return request('/admin/api/logout', { method: 'POST' })
}

export function fetchSettings(): Promise<AdminSettings> {
  return request('/admin/api/settings')
}

export function updateSettings(
  payload: Record<string, string | number | boolean>,
): Promise<{ ok: boolean; updated: string[]; restart_required_for: string[] }> {
  return request('/admin/api/settings', { method: 'POST', body: JSON.stringify(payload) })
}

export async function getApiBaseUrl(): Promise<string> {
  try {
    const settings = await fetchSettings()
    const value = settings.api_base_url?.value
    return (typeof value === 'string' && value) || window.location.origin
  } catch {
    return window.location.origin
  }
}

export function pollNow(): Promise<{ ok: boolean; last_polled_at: string | null }> {
  return request('/admin/api/poll-now', { method: 'POST' })
}

export function fetchUsers(): Promise<{ users: AdminUser[] }> {
  return request('/admin/api/users')
}

export function createUser(username: string, password: string): Promise<{ ok: boolean }> {
  return request('/admin/api/users', { method: 'POST', body: JSON.stringify({ username, password }) })
}

export function deleteUser(username: string): Promise<{ ok: boolean }> {
  return request(`/admin/api/users/${encodeURIComponent(username)}`, { method: 'DELETE' })
}

export function fetchAuditLog(
  params: Record<string, string> & { actor?: string },
): Promise<{ entries: AuditEntry[] }> {
  const qs = new URLSearchParams(Object.fromEntries(Object.entries(params).filter(([, v]) => v))).toString()
  return request(`/admin/api/audit${qs ? `?${qs}` : ''}`)
}

export type AuditFiltersResponse = {
  actors: string[]
  entity_ids: { entity_type: string; entity_id: string; name: string }[]
  entity_types: string[]
  actions: string[]
}

export function fetchAuditFilters(entityType?: string): Promise<AuditFiltersResponse> {
  const qs = entityType ? `?entity_type=${encodeURIComponent(entityType)}` : ''
  return request(`/admin/api/audit/filters${qs}`)
}

export type PollerLogEntry = {
  id: number
  occurred_at: string
  event_type: string
  message: string
  detail: Record<string, unknown> | null
}

export type PollerLogResponse = {
  entries: PollerLogEntry[]
  event_types: string[]
  enabled: boolean
  last_polled_at: string | null
  poll_interval_seconds: number
}

export function fetchPollerLog(limit = 300): Promise<PollerLogResponse> {
  return request(`/admin/api/debug/poller-log?limit=${limit}`)
}

export type MetricsHistoryEntry = {
  id: number
  occurred_at: string
  counter_healthy_true: number
  counter_healthy_false: number
  counter_healthy_online_true: number
  counter_healthy_online_false: number
  counter_key_healthy_true: number
  counter_key_healthy_false: number
  counter_update_healthy_true: number
  counter_update_healthy_false: number
  keys_counter_healthy_true: number
  keys_counter_healthy_false: number
}

export function fetchMetricsHistory(hours = 24): Promise<{ entries: MetricsHistoryEntry[] }> {
  return request(`/admin/api/metrics-history?hours=${hours}`)
}

export function generateToken(): Promise<{ token: string }> {
  return request('/admin/api/settings/generate-token', { method: 'POST' })
}

export type ProfileResponse = { username: string; mfa: { enabled: boolean } }

export function fetchProfile(): Promise<ProfileResponse> {
  return request('/admin/api/profile')
}

export function changePassword(current_password: string, new_password: string): Promise<{ ok: boolean }> {
  return request('/admin/api/profile/password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) })
}

export function enrollMfa(): Promise<{ secret: string; provisioning_uri: string }> {
  return request('/admin/api/profile/mfa/enroll', { method: 'POST' })
}

export function confirmMfa(code: string): Promise<{ ok: boolean; recovery_codes: string[] }> {
  return request('/admin/api/profile/mfa/confirm', { method: 'POST', body: JSON.stringify({ code }) })
}

export function disableMfa(code: string): Promise<{ ok: boolean }> {
  return request('/admin/api/profile/mfa/disable', { method: 'POST', body: JSON.stringify({ code }) })
}

export { AdminApiError }
