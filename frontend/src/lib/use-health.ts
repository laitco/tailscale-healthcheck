import { useCallback, useEffect, useState } from 'react'
import { fetchHealth, fetchKeys, invalidateCache } from '@/lib/api'
import type { HealthResponse, KeysResponse } from '@/lib/types'

interface HealthState {
  health: HealthResponse | null
  keys: KeysResponse | null
  loading: boolean
  error: string | null
  loadedAt: number | null
}

function unavailableKeysResponse(message: string): KeysResponse {
  return {
    keys: [],
    metrics: {
      tailnet_configured: true,
      keys_error: message,
      has_keys: false,
      global_keys_healthy: true,
      counter_key_healthy_true: 0,
      total_keys: 0,
    },
  }
}

export function useHealth() {
  const [state, setState] = useState<HealthState>({
    health: null,
    keys: null,
    loading: true,
    error: null,
    loadedAt: null,
  })

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }))

    // Keys are a secondary, best-effort section (commonly unavailable when
    // the configured token lacks the Keys scope) - a keys-only failure must
    // not blank out the rest of the app, so it's isolated from the health
    // fetch and degrades to an "unavailable" state instead.
    const [healthResult, keysResult] = await Promise.allSettled([fetchHealth(), fetchKeys()])

    if (healthResult.status === 'rejected') {
      const err = healthResult.reason
      setState((s) => ({ ...s, loading: false, error: err instanceof Error ? err.message : 'Failed to load' }))
      return
    }

    const keys =
      keysResult.status === 'fulfilled'
        ? keysResult.value
        : unavailableKeysResponse(
            keysResult.reason instanceof Error ? keysResult.reason.message : 'Failed to load tailnet keys',
          )

    setState({ health: healthResult.value, keys, loading: false, error: null, loadedAt: Date.now() })
  }, [])

  const refresh = useCallback(async () => {
    try {
      await invalidateCache()
    } catch {
      // best-effort; still reload
    }
    await load()
  }, [load])

  useEffect(() => {
    load()
  }, [load])

  // Auto-refetch on the same cadence as the background poller, so the UI
  // doesn't sit on stale data until someone manually hits Refresh.
  const pollIntervalSeconds = state.health?.poll_meta?.poll_interval_seconds ?? null
  useEffect(() => {
    if (pollIntervalSeconds == null || state.loadedAt == null) return
    const elapsedMs = Date.now() - state.loadedAt
    const remainingMs = Math.max(0, pollIntervalSeconds * 1000 - elapsedMs)
    const timer = setTimeout(() => {
      load()
    }, remainingMs)
    return () => clearTimeout(timer)
  }, [pollIntervalSeconds, state.loadedAt, load])

  return { ...state, reload: load, refresh }
}
