import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * A piece of filter state stored in the URL query string instead of component
 * state, so a filtered view survives a reload, can be shared as a link, and
 * responds to browser back/forward.
 *
 * Values equal to `fallback` are removed from the query string rather than
 * written out, which keeps the default view at a clean URL.
 */
export function useUrlState(
  key: string,
  fallback: string,
): [string, (value: string) => void] {
  const [params, setParams] = useSearchParams()
  const value = params.get(key) ?? fallback

  const setValue = useCallback(
    (next: string) => {
      setParams(
        (current) => {
          // Build from `current` rather than the captured `params` so several
          // setters firing in one event don't clobber each other's writes.
          const updated = new URLSearchParams(current)
          if (next === fallback || next === '') {
            updated.delete(key)
          } else {
            updated.set(key, next)
          }
          return updated
        },
        { replace: true }, // filter tweaks shouldn't each add a history entry
      )
    },
    [key, fallback, setParams],
  )

  return [value, setValue]
}
