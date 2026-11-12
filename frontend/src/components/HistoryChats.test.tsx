// History's "Chats" tab (12-Nov: it took the place of the chat list on the left of the Ask page): the chats by
// day with a link to each, the "..." menu (Rename / Remove from list / Delete, which asks first), the removed
// chats with Restore, and the two tabs of the History page.
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
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

describe('HistoryPage tabs', () => {
  const HISTORY = { body: { questions: [], page: 1, pages: 1, count: 0, has_previous: false, has_next: false,
                            usage: { rows: [], period_start: '', period_end: '', week_start: '', week_end: '' } } }

  it('opens on Chats, and Questions is one click away', async () => {
    const fetch = fakeFetch({ '/api/chats': LIST, '/api/history': HISTORY })
    renderAt('/history', <HistoryPage page={1} />)

    expect(screen.getByRole('button', { name: 'Chats' })).toHaveAttribute('aria-pressed', 'true')
    expect(await screen.findByRole('link', { name: 'Net sales by month' })).toBeInTheDocument()
    expect(fetch.mock.calls.map(([url]) => url)).not.toContain('/api/history')     // not read until asked for

    fireEvent.click(screen.getByRole('button', { name: 'Questions' }))
    expect(await screen.findByText('No questions yet')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Net sales by month' })).not.toBeInTheDocument()
  })

  it('opens on Questions for ?tab=questions and for a page of the pager', async () => {
    fakeFetch({ '/api/chats': LIST, '/api/history': HISTORY, '/api/history?page=2': HISTORY })
    const first = renderAt('/history?tab=questions', <HistoryPage page={1} />)
    expect(screen.getByRole('button', { name: 'Questions' })).toHaveAttribute('aria-pressed', 'true')
    first.unmount()
    renderAt('/history?page=2', <HistoryPage page={2} />)
    expect(screen.getByRole('button', { name: 'Questions' })).toHaveAttribute('aria-pressed', 'true')
  })
})
