import { useCallback, useEffect, useState } from 'react'
import { fetchHealth, fetchKeys, invalidateCache } from '@/lib/api'
import type { HealthResponse, KeysResponse } from '@/lib/types'

// Fallback retry cadence used before the app has ever obtained a real
// poll_interval_seconds from a successful /health response (e.g. the very
// first load on page open failed).
const DEFAULT_RETRY_SECONDS = 15

interface HealthState {
  health: HealthResponse | null
  keys: KeysResponse | null
  loading: boolean
  error: string | null
  loadedAt: number | null
  lastAttemptAt: number | null
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
    lastAttemptAt: null,
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
      // lastAttemptAt (not loadedAt, which intentionally keeps the old
      // successful snapshot on screen) is what the auto-refresh effect
      // below reschedules from - without updating it here, a single
      // transient failure would stop automatic refreshing permanently,
      // since loadedAt/pollIntervalSeconds wouldn't change and the effect
      // would never re-run to schedule the next attempt.
      setState((s) => ({
        ...s,
        loading: false,
        error: err instanceof Error ? err.message : 'Failed to load',
        lastAttemptAt: Date.now(),
      }))
      return
    }

    const keys =
      keysResult.status === 'fulfilled'
        ? keysResult.value
        : unavailableKeysResponse(
            keysResult.reason instanceof Error ? keysResult.reason.message : 'Failed to load tailnet keys',
          )

    const now = Date.now()
    setState({ health: healthResult.value, keys, loading: false, error: null, loadedAt: now, lastAttemptAt: now })
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
  //
  // pollIntervalSeconds only exists once a load has ever *succeeded*
  // (poll_meta comes from the response body) - if the very first /health
  // fetch on page load fails, state.health stays null forever and this
  // would otherwise never schedule a retry at all. DEFAULT_RETRY_SECONDS is
  // the fallback used until real poll_meta has been obtained at least once.
  const pollIntervalSeconds = state.health?.poll_meta?.poll_interval_seconds ?? DEFAULT_RETRY_SECONDS
  useEffect(() => {
    if (state.lastAttemptAt == null) return
    const elapsedMs = Date.now() - state.lastAttemptAt
    const remainingMs = Math.max(0, pollIntervalSeconds * 1000 - elapsedMs)
    const timer = setTimeout(() => {
      load()
    }, remainingMs)
    return () => clearTimeout(timer)
  }, [pollIntervalSeconds, state.lastAttemptAt, load])

  return { ...state, reload: load, refresh }
}
