export interface Device {
  id: string
  hostname: string
  device: string
  machineName: string
  os: string
  clientVersion: string
  lastSeen: string
  tags: string[]
  healthy: boolean
  online: boolean
  updateAvailable: boolean
  update_healthy: boolean
  keyExpiryDisabled: boolean
  keyExpiryTimestamp: string | null
  key_healthy: boolean
  key_days_to_expire: number | null
  [key: string]: unknown
}

export interface HealthMetrics {
  global_healthy: boolean
  global_online_healthy: boolean
  global_key_healthy: boolean
  global_update_healthy: boolean
  counter_healthy_online_true: number
  counter_healthy_online_false: number
  counter_key_healthy_true: number
  counter_key_healthy_false: number
  counter_update_healthy_true: number
  counter_update_healthy_false: number
  [key: string]: unknown
}

export interface CacheMeta {
  hit: boolean
  backend: string
  expires_at: string | null
  ttl_seconds: number | null
  loaded_at_iso: string | null
}

export interface HealthResponse {
  devices: Device[]
  metrics: HealthMetrics
  cache_meta?: CacheMeta
  settings?: Record<string, unknown>
}

export interface TailnetKey {
  id: string
  description: string
  keyType: string
  created: string | null
  expires: string | null
  key_healthy: boolean
  key_days_to_expire: number | null
  [key: string]: unknown
}

export interface KeyMetrics {
  tailnet_configured: boolean
  keys_error?: string | null
  has_keys: boolean
  global_keys_healthy: boolean
  counter_key_healthy_true: number
  total_keys: number
  [key: string]: unknown
}

export interface KeysResponse {
  keys: TailnetKey[]
  metrics: KeyMetrics
}
