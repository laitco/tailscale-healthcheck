import { createContext, useContext, type ReactNode } from 'react'
import { useHealth } from '@/lib/use-health'

type HealthContextValue = ReturnType<typeof useHealth>

const HealthContext = createContext<HealthContextValue | null>(null)

export function HealthProvider({ children }: { children: ReactNode }) {
  const value = useHealth()
  return <HealthContext.Provider value={value}>{children}</HealthContext.Provider>
}

export function useHealthContext() {
  const ctx = useContext(HealthContext)
  if (!ctx) throw new Error('useHealthContext must be used within a HealthProvider')
  return ctx
}

/**
 * The tailnet's configured timezone, for formatDateTime(). Comes from
 * /health's poll_meta rather than /admin/api/settings, so non-admin-scoped
 * pages don't have to pull the entire settings payload to format a date.
 * Undefined until the first successful health load; formatDateTime() falls
 * back to browser-local until then.
 */
export function useTimezone(): string | undefined {
  return useHealthContext().health?.poll_meta?.timezone
}
