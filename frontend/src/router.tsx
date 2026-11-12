// The website's own addresses (no router library). Django serves the same index.html at every one of
// them, and the app shows the screen:
//   /            Home (the first page after signing in)       /history[?page=2]   History
//   /ask         the latest chat (or the new-chat screen)
//   /new[?q=..]  the empty new-chat screen (box filled)      /users              Users (staff)
//   /c/<id>      one chat                                     /documents[?...]    Documents (staff)
//   /q/<id>      one saved answer with its rows              /data               Data (staff)
//   /login       the sign-in page                             /memory             Memory (every user)
//   /graph       the Knowledge graph (every user)
//   /audit[?page=2&user=..&action=..&from=..&to=..&q=..]       the Audit log (staff)
// The old Django addresses (/ask/, /ask/new/, /ask/c/<id>/, /ask/<id>/, /app/...) still open the same screens.
import {
  type AnchorHTMLAttributes, type MouseEvent, type ReactNode, createContext, useCallback, useContext, useEffect,
  useMemo, useState,
} from 'react'

export type Route =
  | { kind: 'home' }
  | { kind: 'latest' }
  | { kind: 'new'; q: string }
  | { kind: 'chat'; id: number }
  | { kind: 'question'; id: number }
  | { kind: 'history'; page: number }
  | { kind: 'documents'; source: string; find: string; q: string }
  | { kind: 'users' }
  | { kind: 'data' }
  | { kind: 'memory' }
  | { kind: 'graph' }
  | { kind: 'audit'; page: number; user: string; action: string; from: string; to: string; q: string }
  | { kind: 'login' }
  | { kind: 'notfound' }

export function parseRoute(pathname: string, search = ''): Route {
  const params = new URLSearchParams(search)
  let rest = pathname.replace(/^\/app(?=\/|$)/, '') // the old /app/ addresses of the first React version
  rest = rest.replace(/\/+$/, '') || '/'
  if (rest === '/') return { kind: 'home' }
  if (rest === '/ask') return { kind: 'latest' }
  if (rest === '/new' || rest === '/ask/new') return { kind: 'new', q: params.get('q') ?? '' }
  const chat = rest.match(/^(?:\/ask)?\/c\/(\d+)$/)
  if (chat) return { kind: 'chat', id: Number(chat[1]) }
  const saved = rest.match(/^(?:\/q|\/ask)\/(\d+)$/)
  if (saved) return { kind: 'question', id: Number(saved[1]) }
  if (rest === '/history') return { kind: 'history', page: Math.max(1, Number(params.get('page')) || 1) }
  if (rest === '/documents') {
    return { kind: 'documents', source: params.get('source') ?? '', find: params.get('find') ?? '', q: params.get('q') ?? '' }
  }
  if (rest === '/users') return { kind: 'users' }
  if (rest === '/data') return { kind: 'data' }
  if (rest === '/memory') return { kind: 'memory' }
  if (rest === '/graph') return { kind: 'graph' }
  if (rest === '/audit') {
    return {
      kind: 'audit', page: Math.max(1, Number(params.get('page')) || 1), user: params.get('user') ?? '',
      action: params.get('action') ?? '', from: params.get('from') ?? '', to: params.get('to') ?? '', q: params.get('q') ?? '',
    }
  }
  if (rest === '/login') return { kind: 'login' }
  return { kind: 'notfound' }
}

export const ASK_PATH = '/ask' // the Ask page (the latest chat); "/" is Home
export const chatPath = (id: number) => `/c/${id}`
export const questionPath = (id: number) => `/q/${id}`

interface Router {
  route: Route
  state: unknown // what navigate() passed along (e.g. History's "Ask again")
  navigate: (path: string, options?: { replace?: boolean; state?: unknown }) => void
}

const RouterContext = createContext<Router | null>(null)

function current() {
  return { route: parseRoute(window.location.pathname, window.location.search), state: window.history.state as unknown }
}

/** Holds the address for the whole app: navigate() changes it without a page load, Back / Forward too. */
export function RouterProvider({ children }: { children: ReactNode }) {
  const [where, setWhere] = useState(current)
  useEffect(() => {
    const back = () => setWhere(current())
    window.addEventListener('popstate', back)
    return () => window.removeEventListener('popstate', back)
  }, [])
  const navigate = useCallback((path: string, options: { replace?: boolean; state?: unknown } = {}) => {
    const state = options.state ?? null
    if (options.replace) window.history.replaceState(state, '', path)
    else window.history.pushState(state, '', path)
    setWhere(current())
    window.scrollTo?.(0, 0)
  }, [])
  const value = useMemo(() => ({ ...where, navigate }), [where, navigate])
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>
}

export function useRouter(): Router {
  const router = useContext(RouterContext)
  if (!router) throw new Error('useRouter needs a RouterProvider around the app')
  return router
}

/** A link inside the app: a plain click changes the screen without a page load; Ctrl / middle click
 *  opens a new tab as usual. */
export function Link({ to, onClick, children, ...rest }:
  { to: string; children: ReactNode } & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'>) {
  const { navigate } = useRouter()
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event)
    if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return
    event.preventDefault()
    navigate(to)
  }
  return <a href={to} onClick={follow} {...rest}>{children}</a>
}
