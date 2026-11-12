// shadcn/ui Toaster (sonner): the small messages ("... was removed from your chats") at the top of the
// Ask page. The page font, green for done and red for a problem; light or dark like the page
// (it watches data-theme on <html>, which the theme switch sets).
import { type CSSProperties, useSyncExternalStore } from 'react'
import { Toaster as Sonner, type ToasterProps } from 'sonner'

// tell React when <html data-theme> changes
function watchTheme(changed: () => void) {
  const watcher = new MutationObserver(changed)
  watcher.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  return () => watcher.disconnect()
}

function pageTheme(): 'light' | 'dark' {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'
}

function Toaster(props: ToasterProps) {
  const theme = useSyncExternalStore(watchTheme, pageTheme, () => 'light' as const)
  return (
    <Sonner theme={theme} richColors closeButton className="toaster group"
      style={{
        fontFamily: 'inherit',
        '--normal-bg': 'var(--surface)',
        '--normal-text': 'var(--ink)',
        '--normal-border': 'var(--line)',
        '--border-radius': '12px',
      } as CSSProperties}
      {...props} />
  )
}

export { Toaster }
