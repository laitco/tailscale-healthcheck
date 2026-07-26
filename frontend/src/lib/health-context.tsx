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
