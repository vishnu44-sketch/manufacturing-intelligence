// The website as a whole: a 401 shows the sign-in, the left menu shows the staff pages only to staff, a
// staff page for anyone else says "no access", Home opens first at / (the Ask page is at /ask), the old Django
// addresses open the same screens, and signing out goes back to the sign-in page at /login.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'
import { parseRoute } from './router'
import { callsTo, fakeFetch } from './test/fakeFetch'
import { ASHA, BOSS } from './test/render'

const EMPTY_CHATS = { body: { chats: [], removed: [] } }
const HOME = { body: { first_name: 'Asha', today: '05-Nov-2026', calendar: null, kpis: [], kpi_error: '', tables: [],
  tables_error: '', connections: [], connections_error: '', usage: null, usage_error: '', model: 'openai/gpt-oss-120b' } }

function open(path: string) {
  window.history.pushState(null, '', path)
  return render(<App />)
}

/** The left menu (the top bar has its own "History" link). */
const menu = () => within(screen.getByRole('navigation', { name: 'Main menu' }))
/** Waits for the Ask page: its question box (the box is drawn again once the chats are loaded). */
const askPage = () => waitFor(() => expect(screen.getByLabelText('Your question')).toBeInTheDocument())

describe('App', () => {
  it('shows the sign-in page when the API says 401', async () => {
    fakeFetch({ '/api/me': { status: 401, body: { detail: 'Please sign in.' } } })

    open('/history')

    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByText('History')).not.toBeInTheDocument()
  })

  it('hides the staff menu items from a normal user and says "no access" on a staff page', async () => {
    const fetch = fakeFetch({ '/api/me': { body: ASHA } })

    open('/users')

    expect(await screen.findByText('You do not have access to this page')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'No access' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/')
    expect(screen.getByRole('link', { name: 'Ask AI' })).toHaveAttribute('href', '/ask')
    expect(menu().getByRole('link', { name: 'History' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Memory' })).toHaveAttribute('href', '/memory')   // for every user
    for (const name of [/Users/, /Documents/, /Data/, /Audit/]) {
      expect(screen.queryByRole('link', { name })).not.toBeInTheDocument()
    }
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/me'])   // no staff data was asked for
  })

  it('says "no access" on the Audit page for a normal user without asking the API', async () => {
    const fetch = fakeFetch({ '/api/me': { body: ASHA } })

    open('/audit?action=login_failed')

    expect(await screen.findByText('You do not have access to this page')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Audit/ })).not.toBeInTheDocument()
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/me'])
  })

  it('shows the Audit menu item to staff and opens the log with its filters from the address', async () => {
    fakeFetch({
      '/api/me': { body: BOSS },
      '/api/audit?action=login_failed': { body: { lines: [], page: 1, pages: 1, count: 0, has_previous: false, has_next: false,
                                                  actions: [{ code: 'login_failed', text: 'Sign-in failed' }],
                                                  filters: { user: '', action: 'login_failed', from: '', to: '', q: '' } } },
    })

    open('/audit?action=login_failed')

    expect(await screen.findByText('No audit lines match these filters.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Audit/ })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: /Audit/ })).toHaveAttribute('href', '/audit')
    expect(document.title).toBe('Audit log · Manufacturing Intelligence')
    expect(parseRoute('/audit', '?page=3&user=asha')).toEqual(
      { kind: 'audit', page: 3, user: 'asha', action: '', from: '', to: '', q: '' })
  })

  it('opens the Memory page for a normal user with its menu item lit', async () => {
    fakeFetch({ '/api/me': { body: ASHA }, '/api/memories': { body: { memories: [], limit: 20, max_chars: 300 } } })

    open('/memory')

    expect(await screen.findByText('What I remember about you')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Memory' })).toHaveAttribute('aria-current', 'page')
    expect(document.title).toBe('Memory · Manufacturing Intelligence')
    expect(parseRoute('/memory')).toEqual({ kind: 'memory' })
  })

  it('shows the staff menu to staff with the page lit', async () => {
    fakeFetch({
      '/api/me': { body: BOSS },
      '/api/data': { body: { database: 'ai_gold', mysql_error: '', tables: [], table_count: 0, total: '0',
                             invoices_from: '', invoices_to: '', last_load: '' } },
    })

    open('/data')

    const data = await screen.findByRole('link', { name: /Data/ })
    expect(data).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: /Users/ })).toHaveAttribute('href', '/users')
    expect(screen.getByRole('link', { name: /Documents/ })).toHaveAttribute('href', '/documents')
    expect(await screen.findByText('Records in each table')).toBeInTheDocument()
    expect(document.title).toBe('Data · Manufacturing Intelligence')
  })

  it('moves between pages without a page load', async () => {
    fakeFetch({
      '/api/me': { body: ASHA },
      '/api/chats': EMPTY_CHATS,
      '/api/history': { body: { questions: [], page: 1, pages: 1, count: 0, has_previous: false, has_next: false,
                                usage: { rows: [], period_start: '', period_end: '', week_start: 'Sat 31-Oct 8:20 PM', week_end: 'Sat 07-Nov 8:20 PM' } } },
    })

    open('/ask')
    await askPage()
    expect(screen.getByRole('link', { name: 'Ask AI' })).toHaveAttribute('aria-current', 'page')

    fireEvent.click(menu().getByRole('link', { name: /History/ }))

    expect(await screen.findByText('No questions yet')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/history')
  })

  it('signs out and goes back to the sign-in page', async () => {
    const fetch = fakeFetch({ '/api/me': { body: ASHA }, '/api/chats': EMPTY_CHATS, '/api/logout': { body: { ok: true } } })

    open('/ask')
    fireEvent.click(await screen.findByRole('button', { name: 'User menu' }))   // the round badge in the top bar
    fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }))

    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/login')
    expect(callsTo(fetch, '/api/logout')).toHaveLength(1)
  })

  it('goes on to Home when a signed-in user opens /login', async () => {
    fakeFetch({ '/api/me': { body: ASHA }, '/api/home': HOME })

    open('/login')

    await waitFor(() => expect(window.location.pathname).toBe('/'))
    expect(await screen.findByRole('heading', { name: /, Asha/ })).toBeInTheDocument()
  })

  it('opens Home first at /, as the first menu item, and the Ask page from the menu at /ask', async () => {
    const fetch = fakeFetch({ '/api/me': { body: ASHA }, '/api/home': HOME, '/api/chats': EMPTY_CHATS })

    open('/')

    expect(await screen.findByRole('heading', { name: /, Asha/ })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 1, name: 'Home' })).not.toBeInTheDocument()   // Home has no title row
    expect(document.querySelector('.mi-shell-title')).toBeNull()
    const links = menu().getAllByRole('link')
    expect(links[0]).toHaveAccessibleName('Home')
    expect(links[0]).toHaveAttribute('aria-current', 'page')
    expect(links[1]).toHaveAccessibleName('Ask AI')
    expect(document.title).toBe('Home · Manufacturing Intelligence')
    expect(callsTo(fetch, '/api/home', 'GET')).toHaveLength(1)
    expect(callsTo(fetch, '/api/chats', 'GET')).toHaveLength(0)   // the Ask page is not opened

    fireEvent.click(links[1])                                      // Ask AI, second in the menu

    await askPage()
    expect(window.location.pathname).toBe('/ask')
    expect(document.title).toBe('Ask AI · Manufacturing Intelligence')
    expect(screen.getByRole('heading', { level: 1, name: 'Ask AI' })).toBeInTheDocument()   // the other pages keep it
    expect(document.querySelector('.mi-shell-title')).toHaveTextContent('Ask AI')
  })

  it('the top bar opens a new chat and the History page', async () => {
    fakeFetch({
      '/api/me': { body: ASHA }, '/api/home': HOME, '/api/chats': EMPTY_CHATS,
      '/api/history': { body: { questions: [], page: 1, pages: 1, count: 0, has_previous: false, has_next: false,
                                usage: { rows: [], period_start: '', period_end: '', week_start: '', week_end: '' } } },
    })

    open('/')
    const bar = within(await screen.findByRole('banner'))

    fireEvent.click(bar.getByRole('link', { name: 'History' }))
    expect(await screen.findByText('No questions yet')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/history')

    fireEvent.click(bar.getByRole('link', { name: 'New chat' }))
    await askPage()
    expect(window.location.pathname).toBe('/new')
  })

  it('understands its own addresses and the old Django ones', () => {
    expect(parseRoute('/')).toEqual({ kind: 'home' })
    expect(parseRoute('/ask')).toEqual({ kind: 'latest' })
    expect(parseRoute('/new', '?q=Open%20orders')).toEqual({ kind: 'new', q: 'Open orders' })
    expect(parseRoute('/c/12')).toEqual({ kind: 'chat', id: 12 })
    expect(parseRoute('/q/7')).toEqual({ kind: 'question', id: 7 })
    expect(parseRoute('/history', '?page=2')).toEqual({ kind: 'history', page: 2 })
    expect(parseRoute('/documents', '?source=a.md&q=x')).toEqual({ kind: 'documents', source: 'a.md', find: '', q: 'x' })
    expect(parseRoute('/ask/')).toEqual({ kind: 'latest' })
    expect(parseRoute('/ask/c/3/')).toEqual({ kind: 'chat', id: 3 })
    expect(parseRoute('/ask/9/')).toEqual({ kind: 'question', id: 9 })
    expect(parseRoute('/app/c/4')).toEqual({ kind: 'chat', id: 4 })
    expect(parseRoute('/history/')).toEqual({ kind: 'history', page: 1 })
    expect(parseRoute('/nothing')).toEqual({ kind: 'notfound' })
  })
})
