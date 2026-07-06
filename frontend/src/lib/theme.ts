'use client'

// Light/Dark theme state. A UI PREFERENCE only (never business data) — persisted in
// localStorage so an explicit choice survives a reload, defaulting to the OS
// `prefers-color-scheme` when the user has not chosen. The `.dark` class on <html>
// is the single source of truth Tailwind's class dark-mode variant keys off; the
// pre-paint <script> in layout.tsx sets it before first paint to avoid a flash.

import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

// Must match the key read by the inline pre-paint script in layout.tsx.
export const THEME_STORAGE_KEY = 'ar-theme'

export function getSystemTheme(): Theme {
  if (typeof window === 'undefined' || !window.matchMedia) return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function getStoredTheme(): Theme | null {
  if (typeof window === 'undefined') return null
  try {
    const v = window.localStorage.getItem(THEME_STORAGE_KEY)
    return v === 'light' || v === 'dark' ? v : null
  } catch {
    return null
  }
}

/** Reflect the resolved theme on <html> (the class Tailwind's dark variant reads). */
export function applyTheme(theme: Theme): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
}

/**
 * Toggle-button state. Resolves stored-override-wins-else-system on mount, follows
 * live OS changes only while the user has made no explicit choice, and persists an
 * explicit pick. Initial state is 'light' so the first client render matches the
 * static build output (no hydration mismatch); the pre-paint script has already set
 * the real class, so there is no visual flash.
 */
export function useTheme() {
  const [theme, setThemeState] = useState<Theme>('light')

  useEffect(() => {
    const resolved = getStoredTheme() ?? getSystemTheme()
    setThemeState(resolved)
    applyTheme(resolved)

    if (!window.matchMedia) return
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      // Only auto-follow the OS when the user has NOT pinned a preference.
      if (getStoredTheme() === null) {
        const sys = getSystemTheme()
        setThemeState(sys)
        applyTheme(sys)
      }
    }
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  const setTheme = useCallback((next: Theme) => {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      /* storage unavailable (private mode) — still apply for this session */
    }
    setThemeState(next)
    applyTheme(next)
  }, [])

  const toggle = useCallback(() => {
    setThemeState((prev) => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark'
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, next)
      } catch {
        /* ignore */
      }
      applyTheme(next)
      return next
    })
  }, [])

  return { theme, setTheme, toggle }
}

/**
 * Read-only observer of the active theme for non-DOM consumers (the Recharts charts,
 * whose tick/grid/tooltip colors are inline props, not Tailwind classes). Re-renders
 * when the `.dark` class on <html> changes so charts recolor on toggle.
 */
export function useIsDark(): boolean {
  const [isDark, setIsDark] = useState(false)
  useEffect(() => {
    const root = document.documentElement
    const update = () => setIsDark(root.classList.contains('dark'))
    update()
    const obs = new MutationObserver(update)
    obs.observe(root, { attributes: true, attributeFilter: ['class'] })
    return () => obs.disconnect()
  }, [])
  return isDark
}
