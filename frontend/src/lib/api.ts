import type { Device, HealthResponse, KeysResponse } from '@/lib/types'

class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    let message = `Request failed with status ${res.status}`
    try {
      const body = await res.json()
      if (body?.error) message = body.error
    } catch {
      // ignore non-JSON error bodies
    }
    throw new ApiError(message, res.status)
  }
  return res.json() as Promise<T>
}

export function fetchHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>('/health')
}

export function fetchKeys(): Promise<KeysResponse> {
  return getJson<KeysResponse>('/keys')
}

export async function fetchDeviceByIdentifier(identifier: string): Promise<Device> {
  const data = await getJson<{ device: Device }>(`/health/${encodeURIComponent(identifier)}`)
  return data.device
}

export function invalidateCache(): Promise<void> {
  return fetch('/health/cache/invalidate', { headers: { Accept: 'application/json' } }).then(() => undefined)
}

export { ApiError }
