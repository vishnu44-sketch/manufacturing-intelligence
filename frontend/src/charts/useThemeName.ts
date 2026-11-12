// The theme the charts draw in: 'dark' while <html data-theme="dark"> is set, else 'light'. The menu's switch
// only sets that attribute; this hook watches it (a MutationObserver), so a chart reads its colours again and
// draws itself anew the moment the theme changes - no page reload, nothing imported from the switch's own code.
import { useSyncExternalStore } from 'react'
import { type ThemeName, themeName } from './chartOption'

/** Calls `changed` each time the data-theme attribute of <html> changes; gives back the function that stops it. */
function watchTheme(changed: () => void): () => void {
  if (typeof MutationObserver === 'undefined') return () => {}
  const watch = new MutationObserver(changed)
  watch.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  return () => watch.disconnect()
}

export default function useThemeName(): ThemeName {
  return useSyncExternalStore(watchTheme, themeName, () => 'light' as ThemeName)
}
