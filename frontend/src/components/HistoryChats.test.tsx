// History's "Chats" tab (12-Nov: it took the place of the chat list on the left of the Ask page): the chats by
// day with a link to each, the "..." menu (Rename / Remove from list / Delete, which asks first), the removed
// chats with Restore, and the two tabs of the History page.
// 18-Nov: the switch Assistant (first) | ML Insights | All, with counts, kept in this browser.
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { callsTo, fakeFetch } from '../test/fakeFetch'
import { renderAt } from '../test/render'
import type { ChatSummary } from '../types'
import HistoryChats from './HistoryChats'
import HistoryPage from './HistoryPage'

function chat(id: number, title: string, extra: Partial<ChatSummary> = {}): ChatSummary {
  return { id, title, archived: false, created_at: '', created_text: '03 Nov 2026 09:00 AM', updated_at: '',
           updated_text: '03 Nov, 09:05 AM', group: 'Today', questions: 2, ...extra }
}
const SALES = chat(1, 'Net sales by month')
const STOCK = chat(2, 'Stock value', { group: 'Yesterday', questions: 1 })
const OLD = chat(3, 'An old removed chat', { archived: true, group: undefined, questions: 4 })
const LIST = { body: { chats: [SALES, STOCK], removed: [OLD] } }

async function openMenu(title: string) {
  const row = (await screen.findByRole('link', { name: title })).closest('li') as HTMLElement
  fireEvent.click(within(row).getByRole('button', { name: `Options for the chat ${title}` }))
  return row
}

describe('HistoryChats', () => {
  it('shows the chats by day with a link to each, and the removed ones folded', async () => {
    fakeFetch({ '/api/chats': LIST })
    renderAt('/history', <HistoryChats />)

    expect(await screen.findByRole('link', { name: 'Net sales by month' })).toHaveAttribute('href', '/c/1')
    expect(screen.getByRole('link', { name: 'Stock value' })).toHaveAttribute('href', '/c/2')
    expect(screen.getByRole('region', { name: 'Today' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Yesterday' })).toBeInTheDocument()
    expect(screen.getByText('1 question · last one 03 Nov, 09:05 AM')).toBeInTheDocument()
    expect(screen.getByText('Removed chats (1)')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'New chat' })).toHaveAttribute('href', '/new')
  })

  it('marks an ML Insights chat with a small "ML" badge and opens it on ML Insights (17-Nov)', async () => {
    const ML = chat(4, 'Sales forecast for 3 months', { mode: 'ml' })
    const OLD_ML = chat(5, 'Customers at risk', { mode: 'ml', archived: true, group: undefined })
    fakeFetch({ '/api/chats': { body: { chats: [ML, SALES], removed: [OLD_ML] } } })
    renderAt('/history', <HistoryChats />)
    fireEvent.click(await screen.findByRole('button', { name: 'All (2)' }))   // both kinds (18-Nov)

    const link = await screen.findByRole('link', { name: 'Sales forecast for 3 months' })
    expect(link).toHaveAttribute('href', '/insights?chat=4')
    expect(within(link.closest('li') as HTMLElement).getByTitle('A chat of ML Insights - it opens there')).toHaveTextContent('ML Insights chat')
    // a normal chat: no badge, opens on the Assistant as before
    const sales = screen.getByRole('link', { name: 'Net sales by month' })
    expect(sales).toHaveAttribute('href', '/c/1')
    expect(within(sales.closest('li') as HTMLElement).queryByTitle('A chat of ML Insights - it opens there')).not.toBeInTheDocument()
    // a removed ML chat opens there too
    expect(screen.getByRole('link', { name: 'Customers at risk' })).toHaveAttribute('href', '/insights?chat=5')

    fireEvent.click(link)
    expect(window.location.pathname + window.location.search).toBe('/insights?chat=4')
  })

  it('says so when there are no chats yet', async () => {
    fakeFetch({ '/api/chats': { body: { chats: [], removed: [] } } })
    renderAt('/history', <HistoryChats />)
    expect(await screen.findByText('No chats yet')).toBeInTheDocument()
  })

  it('renames a chat from its menu and shows the new title', async () => {
    let renamed = false
    const fetch = fakeFetch({
      '/api/chats': () => ({ body: { chats: [renamed ? { ...SALES, title: 'Sales per month' } : SALES, STOCK], removed: [OLD] } }),
      '/api/chats/1/rename': () => { renamed = true; return { body: { chat: { ...SALES, title: 'Sales per month' } } } },
    })
    renderAt('/history', <HistoryChats />)
    const row = await openMenu('Net sales by month')
    fireEvent.change(within(row).getByLabelText('New title for this chat'), { target: { value: 'Sales per month' } })
    fireEvent.click(within(row).getByRole('button', { name: 'Rename' }))

    await waitFor(() => expect(callsTo(fetch, '/api/chats/1/rename')).toEqual([{ title: 'Sales per month' }]))
    expect(await screen.findByRole('link', { name: 'Sales per month' })).toBeInTheDocument()
  })

  it('removes a chat from the list with a message, and restores a removed one', async () => {
    let removed = false
    let restored = false
    const fetch = fakeFetch({
      '/api/chats': () => ({ body: {
        chats: [...(removed ? [] : [SALES]), STOCK, ...(restored ? [{ ...OLD, archived: false, group: 'Older' }] : [])],
        removed: [...(removed ? [{ ...SALES, archived: true }] : []), ...(restored ? [] : [OLD])] } }),
      '/api/chats/1/remove': () => { removed = true; return { body: { chat: { ...SALES, archived: true },
        message: '"Net sales by month" was removed from your chats - its questions are still in History.' } } },
      '/api/chats/3/restore': () => { restored = true; return { body: { chat: { ...OLD, archived: false } } } },
    })
    renderAt('/history', <HistoryChats />)
    const row = await openMenu('Net sales by month')
    fireEvent.click(within(row).getByRole('button', { name: /Remove from list/ }))

    expect(await screen.findByText(/was removed from your chats/)).toBeInTheDocument()   // a toast
    expect(await screen.findByText('Removed chats (2)')).toBeInTheDocument()

    const old = screen.getByRole('link', { name: 'An old removed chat' }).closest('li') as HTMLElement
    fireEvent.click(within(old).getByRole('button', { name: 'Restore' }))
    await waitFor(() => expect(callsTo(fetch, '/api/chats/3/restore')).toHaveLength(1))
    expect(await screen.findByRole('region', { name: 'Older' })).toBeInTheDocument()     // back in the list
    expect(screen.getByText('Removed chats (1)')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/history')                                     // stays on History
  })

  it('asks before deleting a chat for good, and deletes only on yes', async () => {
    const fetch = fakeFetch({
      '/api/chats': LIST,
      '/api/chats/1/delete': { body: { deleted: 2, message: '"Net sales by month" was deleted with its 2 questions.' } },
    })
    renderAt('/history', <HistoryChats />)
    let row = await openMenu('Net sales by month')
    fireEvent.click(within(row).getByRole('button', { name: /Delete/ }))
    let dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveAccessibleName('Delete this chat and its 2 questions permanently? This cannot be undone.')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(callsTo(fetch, '/api/chats/1/delete')).toHaveLength(0)

    row = await openMenu('Net sales by month')
    fireEvent.click(within(row).getByRole('button', { name: /Delete/ }))
    dialog = await screen.findByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }))
    expect(await screen.findByText('"Net sales by month" was deleted with its 2 questions.')).toBeInTheDocument()
    expect(callsTo(fetch, '/api/chats/1/delete')).toHaveLength(1)
  })

  it('shows a message when the chats cannot be read', async () => {
    fakeFetch({ '/api/chats': { status: 503, body: { detail: 'The chats cannot be read right now.' } } })
    renderAt('/history', <HistoryChats />)
    expect(await screen.findByRole('alert')).toHaveTextContent('The chats cannot be read right now.')
  })
})

describe('HistoryChats switch: Assistant | ML Insights | All (18-Nov)', () => {
  const ML = chat(4, 'Sales forecast for 3 months', { mode: 'ml' })
  const OLD_ML = chat(5, 'Customers at risk', { mode: 'ml', archived: true, group: undefined })
  const BOTH = { body: { chats: [ML, SALES, STOCK], removed: [OLD, OLD_ML] } }
  const pressed = (name: string) => expect(screen.getByRole('button', { name })).toHaveAttribute('aria-pressed', 'true')
  const BADGE = 'A chat of ML Insights - it opens there'

  it('has three tabs with their counts and opens on the Assistant: no ML chat there', async () => {
    fakeFetch({ '/api/chats': BOTH })
    renderAt('/history', <HistoryChats />)

    expect(await screen.findByRole('link', { name: 'Net sales by month' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Which chats to show' })).toBeInTheDocument()
    pressed('Assistant (2)')
    expect(screen.getByRole('button', { name: 'ML Insights (1)' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'All (3)' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('link', { name: 'Stock value' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Sales forecast for 3 months' })).not.toBeInTheDocument()
    expect(screen.queryByTitle(BADGE)).not.toBeInTheDocument()
    expect(screen.getByText('Removed chats (1)')).toBeInTheDocument()                   // only the Assistant's removed one
    expect(screen.queryByRole('link', { name: 'Customers at risk' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'New chat' })).toHaveAttribute('href', '/new')
  })

  it('ML Insights shows only the ML chats (and removed ones), All shows both with the badge; the choice is kept', async () => {
    fakeFetch({ '/api/chats': BOTH })
    renderAt('/history', <HistoryChats />)

    fireEvent.click(await screen.findByRole('button', { name: 'ML Insights (1)' }))
    pressed('ML Insights (1)')
    expect(screen.getByRole('link', { name: 'Sales forecast for 3 months' })).toHaveAttribute('href', '/insights?chat=4')
    expect(screen.queryByRole('link', { name: 'Net sales by month' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Stock value' })).not.toBeInTheDocument()
    expect(screen.getByText('Removed chats (1)')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Customers at risk' })).toHaveAttribute('href', '/insights?chat=5')
    expect(screen.getByRole('link', { name: 'New chat' })).toHaveAttribute('href', '/insights?new=1')
    expect(window.localStorage.getItem('mi.historyMode')).toBe('ml')

    fireEvent.click(screen.getByRole('button', { name: 'All (3)' }))
    pressed('All (3)')
    for (const name of ['Sales forecast for 3 months', 'Net sales by month', 'Stock value']) {
      expect(screen.getByRole('link', { name })).toBeInTheDocument()
    }
    expect(within(screen.getByRole('link', { name: 'Sales forecast for 3 months' }).closest('li') as HTMLElement)
      .getByTitle(BADGE)).toBeInTheDocument()
    expect(screen.getByText('Removed chats (2)')).toBeInTheDocument()
    expect(window.localStorage.getItem('mi.historyMode')).toBe('all')

    fireEvent.click(screen.getByRole('button', { name: 'Assistant (2)' }))
    expect(window.localStorage.getItem('mi.historyMode')).toBeNull()                    // the first one: nothing kept
  })

  it('opens on the last choice of this browser', async () => {
    window.localStorage.setItem('mi.historyMode', 'ml')
    fakeFetch({ '/api/chats': BOTH })
    renderAt('/history', <HistoryChats />)

    expect(await screen.findByRole('link', { name: 'Sales forecast for 3 months' })).toBeInTheDocument()
    pressed('ML Insights (1)')
    expect(screen.queryByRole('link', { name: 'Net sales by month' })).not.toBeInTheDocument()
  })

  it('works without the browser storage (the Assistant first)', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    fakeFetch({ '/api/chats': BOTH })
    renderAt('/history', <HistoryChats />)

    expect(await screen.findByRole('link', { name: 'Net sales by month' })).toBeInTheDocument()
    pressed('Assistant (2)')
    fireEvent.click(screen.getByRole('button', { name: 'ML Insights (1)' }))
    pressed('ML Insights (1)')
    expect(screen.getByRole('link', { name: 'Sales forecast for 3 months' })).toBeInTheDocument()
  })

  it('says so when one side has no chats', async () => {
    fakeFetch({ '/api/chats': LIST })
    renderAt('/history', <HistoryChats />)
    fireEvent.click(await screen.findByRole('button', { name: 'ML Insights (0)' }))
    expect(screen.getByText('No ML Insights chats yet')).toBeInTheDocument()
    expect(screen.queryByText('Removed chats (1)')).not.toBeInTheDocument()            // the removed one is the Assistant's
  })

  it('the chat menu works under ML Insights: remove puts the chat in its removed list', async () => {
    let removed = false
    const fetch = fakeFetch({
      '/api/chats': () => ({ body: { chats: [...(removed ? [] : [ML]), SALES],
                                     removed: [...(removed ? [{ ...ML, archived: true, group: undefined }] : []), OLD_ML, OLD] } }),
      '/api/chats/4/remove': () => { removed = true; return { body: { chat: { ...ML, archived: true }, message: 'Removed.' } } },
    })
    window.localStorage.setItem('mi.historyMode', 'ml')
    renderAt('/history', <HistoryChats />)
    const row = await openMenu('Sales forecast for 3 months')
    fireEvent.click(within(row).getByRole('button', { name: /Remove from list/ }))

    await waitFor(() => expect(callsTo(fetch, '/api/chats/4/remove')).toHaveLength(1))
    expect(await screen.findByText('Removed chats (2)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ML Insights (0)' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('No ML Insights chats yet')).toBeInTheDocument()
  })
})

describe('HistoryPage tabs', () => {
  const HISTORY = { body: { questions: [], page: 1, pages: 1, count: 0, has_previous: false, has_next: false,
                            usage: { rows: [], period_start: '', period_end: '', week_start: '', week_end: '' } } }

  it('opens on Chats, and Questions is one click away', async () => {
    const fetch = fakeFetch({ '/api/chats': LIST, '/api/history?mode=assistant': HISTORY })
    renderAt('/history', <HistoryPage page={1} />)

    expect(screen.getByRole('button', { name: 'Chats' })).toHaveAttribute('aria-pressed', 'true')
    expect(await screen.findByRole('link', { name: 'Net sales by month' })).toBeInTheDocument()
    expect(fetch.mock.calls.filter(([url]) => url.startsWith('/api/history'))).toHaveLength(0) // not read until asked for

    fireEvent.click(screen.getByRole('button', { name: 'Questions' }))
    expect(await screen.findByText('No questions yet')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Net sales by month' })).not.toBeInTheDocument()
  })

  it('opens on Questions for ?tab=questions and for a page of the pager', async () => {
    fakeFetch({ '/api/chats': LIST, '/api/history?mode=assistant': HISTORY, '/api/history?page=2&mode=assistant': HISTORY })
    const first = renderAt('/history?tab=questions', <HistoryPage page={1} />)
    expect(screen.getByRole('button', { name: 'Questions' })).toHaveAttribute('aria-pressed', 'true')
    first.unmount()
    renderAt('/history?page=2', <HistoryPage page={2} />)
    expect(screen.getByRole('button', { name: 'Questions' })).toHaveAttribute('aria-pressed', 'true')
  })
})
