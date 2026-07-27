import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

type ToastVariant = 'success' | 'error'

interface Toast {
  id: number
  message: string
  variant: ToastVariant
}

interface ToastApi {
  /** Transient confirmation - "Poll triggered", "Settings saved". */
  notify: (message: string, variant?: ToastVariant) => void
}

const ToastContext = createContext<ToastApi | null>(null)

const DISMISS_AFTER_MS = 5000

/**
 * Minimal toast host for actions whose result isn't otherwise visible on the
 * page - "Poll now" and the sidebar Refresh button in particular used to fail
 * completely silently. Page-level state (a failed load, a stale snapshot)
 * belongs in an inline <Alert> instead, where it persists.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)

  const notify = useCallback((message: string, variant: ToastVariant = 'success') => {
    const id = nextId.current++
    setToasts((current) => [...current, { id, message, variant }])
    setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), DISMISS_AFTER_MS)
  }, [])

  const api = useMemo(() => ({ notify }), [notify])

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        // polite, not assertive: these are confirmations of something the user
        // just did, so they shouldn't cut off whatever is being read.
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 p-4 sm:items-end"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cn(
              'pointer-events-auto max-w-sm rounded-md border px-4 py-2 text-sm shadow-md',
              toast.variant === 'error'
                ? 'border-destructive/50 bg-destructive/10 text-destructive'
                : 'border-success/50 bg-success/10 text-success',
            )}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside a ToastProvider')
  return ctx
}
