import { useEffect } from 'react'

export function useSystemTheme() {
  useEffect(() => {
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = (matches: boolean) => document.documentElement.classList.toggle('dark', matches)
    apply(mql.matches)
    const listener = (e: MediaQueryListEvent) => apply(e.matches)
    mql.addEventListener('change', listener)
    return () => mql.removeEventListener('change', listener)
  }, [])
}
