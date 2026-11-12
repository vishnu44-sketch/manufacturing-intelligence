// The website: the Login page until the API knows the user, then each page in the shell (dark menu on
// the left, top bar) by its address - Home (at /, the first page), Ask AI, History, Memory, Knowledge graph, and for staff Users, Documents,
// Data and Audit (anyone else gets "no access"). Any 401 from the API brings the Login page back; signing out goes to /login.
import { useCallback, useEffect, useState } from 'react'
import { ApiError, api, setUnauthorizedHandler } from './api'
import AskPage from './components/AskPage'
import AuditPage from './components/AuditPage'
import DataPage from './components/DataPage'
import DocumentsPage from './components/DocumentsPage'
import GraphPage from './components/GraphPage'
import { forgetGraphPage } from './components/graphData'
import HistoryPage from './components/HistoryPage'
import HomePage from './components/HomePage'
import Login from './components/Login'
import MemoryPage from './components/MemoryPage'
import Shell, { type MenuItem } from './components/Shell'
import UsersPage from './components/UsersPage'
import { NoAccess, NotFound } from './components/common'
import { type Route, RouterProvider, useRouter } from './router'
import type { Me } from './types'

type Auth = { state: 'loading' } | { state: 'out' } | { state: 'in'; me: Me } | { state: 'down'; message: string }

const STAFF_PAGES = new Set<Route['kind']>(['users', 'documents', 'data', 'audit'])

/** [title, lit menu item] of a page. */
function pageOf(route: Route, me: Me): [string, MenuItem] {
  if (STAFF_PAGES.has(route.kind) && !me.is_staff) return ['No access', '']
  switch (route.kind) {
    case 'home': return ['Home', 'home']
    case 'history': return ['History', 'history']
    case 'memory': return ['Memory', 'memory']
    case 'graph': return ['Knowledge graph', 'graph']
    case 'users': return ['Users', 'users']
    case 'documents': return ['Documents', 'documents']
    case 'data': return ['Data', 'data']
    case 'audit': return ['Audit log', 'audit']
    case 'notfound': return ['Not found', '']
    default: return ['Ask AI', 'ask']
  }
}

function Page({ route, me }: { route: Route; me: Me }) {
  if (STAFF_PAGES.has(route.kind) && !me.is_staff) return <NoAccess />
  switch (route.kind) {
    case 'home': return <HomePage me={me} />
    case 'history': return <HistoryPage page={route.page} />
    case 'memory': return <MemoryPage />
    case 'graph': return <GraphPage />
    case 'users': return <UsersPage />
    case 'documents': return <DocumentsPage source={route.source} find={route.find} q={route.q} />
    case 'data': return <DataPage />
    case 'audit':
      return <AuditPage page={route.page} user={route.user} action={route.action} from={route.from} to={route.to} q={route.q} />
    case 'notfound': return <NotFound />
    default: return <AskPage me={me} />
  }
}

function Site() {
  const { route, navigate } = useRouter()
  const [auth, setAuth] = useState<Auth>({ state: 'loading' })

  const loadMe = useCallback(() => {
    api
      .me()
      .then((me) => setAuth({ state: 'in', me }))
      .catch((error) => {
        if (error instanceof ApiError) setAuth({ state: 'down', message: error.message })
        // an AuthError already switched to the Login page (the 401 handler)
      })
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      forgetGraphPage() // the next person to sign in here must not see this user's graph
      setAuth({ state: 'out' })
    })
    loadMe()
    return () => setUnauthorizedHandler(null)
  }, [loadMe])

  // signed in on /login: on to Home
  useEffect(() => {
    if (auth.state === 'in' && route.kind === 'login') navigate('/', { replace: true })
  }, [auth.state, route.kind, navigate])

  async function signOut() {
    try {
      await api.logout()
    } catch {
      // signed out on this side anyway
    } finally {
      forgetGraphPage()
      setAuth({ state: 'out' })
      navigate('/login')
    }
  }

  if (auth.state === 'loading') {
    return (
      <div className="app-loading">
        <span className="dots"><i /><i /><i /></span> Loading…
      </div>
    )
  }
  if (auth.state === 'down') {
    return (
      <div className="app-loading">
        <div className="errbox">{auth.message}</div>
      </div>
    )
  }
  if (auth.state === 'out') return <Login onSignedIn={loadMe} />
  if (route.kind === 'login') return null // on its way to / (Home)
  const [title, active] = pageOf(route, auth.me)
  return (
    // Home has no top bar: its banner shows the greeting and the clock
    <Shell me={auth.me} title={title} active={active} onSignOut={signOut} header={route.kind !== 'home'}>
      <Page route={route} me={auth.me} />
    </Shell>
  )
}

export default function App() {
  return (
    <RouterProvider>
      <Site />
    </RouterProvider>
  )
}
