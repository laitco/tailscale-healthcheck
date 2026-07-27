import { useEffect, useState } from 'react'

/**
 * Trailing-edge debounce of a rapidly-changing value.
 *
 * Used for free-text filters that trigger a server request: without it, every
 * keystroke fires its own query (and its own COUNT), and slow responses can
 * land out of order.
 */
export function useDebounced<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}
