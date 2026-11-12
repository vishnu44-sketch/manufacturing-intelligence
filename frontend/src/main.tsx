import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// the site's look (moved here from the old Django pages; it starts with the font @import), then the React extras
import './styles/app.css'
import './extra.css'
// Tailwind CSS + shadcn/ui colours for the restyled Ask page (no Preflight reset: the other pages do not change)
import './tailwind.css'
import App from './App'
import { applyTheme, readTheme } from './lib/theme'

// the light / dark look chosen in this browser, set on <html data-theme> before the first paint
applyTheme(readTheme())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
