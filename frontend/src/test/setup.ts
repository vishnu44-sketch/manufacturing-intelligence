// Vitest: the Testing Library matchers (toBeInTheDocument ...) and a clean page, address and fetch after
// each test. jsdom has no window.scrollTo: a quiet stand-in.
import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
import { forgetGraphPage } from '../components/graphData'

window.scrollTo = () => {}
// findBy / waitFor wait up to 3 s (not 1 s): with all tests running at once the lazy pages and charts load slower
configure({ asyncUtilTimeout: 3000 })

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.history.replaceState(null, '', '/')
  document.body.className = ''
  forgetGraphPage() // each test starts with an empty Knowledge graph page
  window.localStorage.clear() // the small menu, the hidden details panel
})
