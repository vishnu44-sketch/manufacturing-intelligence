// The website's own addresses (no router library). Django serves the same index.html at every one of
// them, and the app shows the screen:
//   /            Home (the first page after signing in)       /history[?page=2]   History
//   /ask         the latest chat (or the new-chat screen)
//   /new[?q=..]  the empty new-chat screen (box filled)      /users              Users (staff)
//   /c/<id>      one chat                                     /documents[?...]    Documents (staff)
//   /q/<id>      one saved answer with its rows              /data               Data (staff)
//   /login       the sign-in page
//   /graph       the Knowledge graph (every user)            /sql                SQL (staff)
//   /insights[?chat=<id>]  ML Insights: the ML question box and its chat (every user); ?chat= opens an ML chat,
//                          /insights alone the latest ML chat (none yet: the empty box), ?new=1 a new, empty ML chat,
//                          ?new=1&ask=<question> a new ML chat that asks that question once (a card of the ML Dashboard)
//   /ml-dashboard          the ML Dashboard: the 6 ML result cards (every user)
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
  | { kind: 'sql' }
  | { kind: 'graph' }
  // fresh: ?new=1, a new ML chat (not the latest one); ask: ?ask=, a question to ask in it at once ('' none)
  | { kind: 'insights'; chat: number | null; fresh: boolean; ask: string }
  | { kind: 'mldashboard' }
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
  if (rest === '/sql') return { kind: 'sql' }
  if (rest === '/graph') return { kind: 'graph' }
  if (rest === '/insights') {
    const chat = Number(params.get('chat')) || null
    const fresh = chat === null && params.get('new') === '1'
    return { kind: 'insights', chat, fresh, ask: fresh ? (params.get('ask') ?? '').trim() : '' }
  }
  if (rest === '/ml-dashboard') return { kind: 'mldashboard' }
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
/** ML Insights, with one of its ML chats open (or none: the page with an empty question box). */
export const insightsPath = (chatId: number | null = null) => (chatId ? `/insights?chat=${chatId}` : '/insights')
/** A new, empty ML chat on ML Insights (the top bar's "New chat" on that page); /insights alone reopens the latest one. */
export const NEW_ML_CHAT_PATH = '/insights?new=1'
/** A card's "Ask about this" on the ML Dashboard: ML Insights asks the question once, in a new ML chat. */
export const askInMlPath = (question: string) => `${NEW_ML_CHAT_PATH}&ask=${encodeURIComponent(question)}`
/** The ML Dashboard: the 6 ML result cards. */
export const ML_DASHBOARD_PATH = '/ml-dashboard'
/** Where a chat opens: an ML chat on ML Insights, any other on the Assistant. */
export const openChatPath = (chat: { id: number; mode?: string }) => (chat.mode === 'ml' ? insightsPath(chat.id) : chatPath(chat.id))

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
