// The light / dark look of the whole website. The choice is kept in this browser (localStorage 'mi.theme')
// and shown to the CSS as <html data-theme="light|dark">: the colours in the CSS only watch that attribute.
// main.tsx applies the saved choice before the first paint; the moon / sun button in the top bar flips it.
import { useCallback, useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark'

const THEME_KEY = 'mi.theme'

/** The look chosen in this browser. (Nothing saved, or no storage: light.) */
export function readTheme(): Theme {
  try {
    return window.localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

// everything on the page that shows the theme (the moon / sun button) hears about a change
const listeners = new Set<() => void>()

/** Switches the page to this look and keeps the choice for the next visit. */
export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
  try {
    window.localStorage.setItem(THEME_KEY, theme)
  } catch {
    // storage blocked: this look until the page is loaded again
  }
  listeners.forEach((tell) => tell())
}

/** The look the page has now: the attribute when it is set, else the saved choice. */
function currentTheme(): Theme {
  const shown = document.documentElement.dataset.theme
  if (shown === 'dark' || shown === 'light') return shown
  return readTheme()
}

function listen(tell: () => void) {
  listeners.add(tell)
  return () => { listeners.delete(tell) }
}

/** [the look now, switch to the other one]. */
export function useTheme(): [Theme, () => void] {
  const theme = useSyncExternalStore(listen, currentTheme, () => 'light' as Theme)
  const toggle = useCallback(() => applyTheme(currentTheme() === 'dark' ? 'light' : 'dark'), [])
  return [theme, toggle]
}
