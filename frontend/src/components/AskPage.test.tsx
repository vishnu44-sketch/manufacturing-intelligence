// The Ask page's chat actions: the "..." menu (Rename / Remove from list / Delete, which asks first),
// the removed chats with Restore, editing an old question (its new answer takes the old one's place),
// a saved answer on its own (/q/<id>), the example link (/new?q=) and only the newest answer's rows; the chat
// list made small (a rail), kept in this browser.
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { callsTo, fakeFetch } from '../test/fakeFetch'
import { ASHA, renderAt } from '../test/render'
import type { Card, ChatSummary } from '../types'
import AskPage from './AskPage'

function chat(id: number, title: string, extra: Partial<ChatSummary> = {}): ChatSummary {
  return { id, title, archived: false, created_at: '', created_text: '03 Nov 2026 09:00 AM', updated_at: '',
           updated_text: '03 Nov, 09:05 AM', group: 'Today', questions: 2, ...extra }
}

function card(id: number, text: string, extra: Partial<Card> = {}): Card {
  return { id, text, status: 'ok', answer: `Answer to ${text}`, understood_as: '', backup_model: '', token_notice: '',
           time_steps: [], sql: 'SELECT 1', sources: [], secs: 1.2, tries: 1, row_count: 1, has_rows: true,
           rows_url: `/api/questions/${id}/rows`, excel_url: `/api/questions/${id}/excel`, created_at: '',
           created_text: '03 Nov 2026 09:00 AM', edited: false, ...extra }
}

const ROWS = { headers: [{ name: 'n', num: true }], rows: [[{ text: '1', num: true }]], row_count: 1, truncated: false, rows_error: '' }
const SALES = chat(1, 'Net sales by month')
const STOCK = chat(2, 'Stock value', { group: 'Yesterday', questions: 1 })
const OLD = chat(3, 'An old removed chat', { archived: true, group: undefined, questions: 4 })
const DETAIL = { chat: SALES, total: 2, earlier: 0, cards: [card(11, 'Net sales in Aug?'), card(12, 'And for Sep?')] }

function replies(extra = {}) {
  return {
    '/api/chats': { body: { chats: [SALES, STOCK], removed: [OLD] } },
    '/api/chats/1': { body: DETAIL },
    '/api/questions/12/rows': { body: ROWS },
    ...extra,
  }
}

async function openMenu(title: string) {
  const row = (await screen.findByRole('link', { name: title })).closest('.chat-row') as HTMLElement
  fireEvent.click(within(row).getByRole('button', { name: 'Options for this chat' }))
  return row
}

describe('AskPage chat actions', () => {
  it('shows the chats by day, the removed ones folded, and loads only the newest rows', async () => {
    const fetch = fakeFetch(replies())

    renderAt('/c/1', <AskPage me={ASHA} />)

    expect(await screen.findByText('Answer to And for Sep?')).toBeInTheDocument()
    expect(screen.getByText('Today')).toBeInTheDocument()
    expect(screen.getByText('Yesterday')).toBeInTheDocument()
    expect(screen.getByText('Removed chats (1)')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Net sales by month' })).toHaveAttribute('aria-current', 'page')
    await waitFor(() => expect(fetch.mock.calls.map(([url]) => url)).toContain('/api/questions/12/rows'))
    expect(fetch.mock.calls.map(([url]) => url)).not.toContain('/api/questions/11/rows')   // older: on "Show rows"
  })

  it('renames a chat from its menu', async () => {
    const fetch = fakeFetch(replies({ '/api/chats/1/rename': { body: { chat: { ...SALES, title: 'Sales per month' } } } }))

    renderAt('/c/1', <AskPage me={ASHA} />)
    const row = await openMenu('Net sales by month')
    expect(within(row).getByText('2 questions · last one 03 Nov, 09:05 AM')).toBeInTheDocument()
    fireEvent.change(within(row).getByLabelText('New title for this chat'), { target: { value: 'Sales per month' } })
    fireEvent.click(within(row).getByRole('button', { name: 'Rename' }))

    await waitFor(() => expect(callsTo(fetch, '/api/chats/1/rename')).toEqual([{ title: 'Sales per month' }]))
    expect(await screen.findByText('Sales per month', { selector: '.conv-title' })).toBeInTheDocument()
  })

  it('removes the open chat from the list and says where its questions are', async () => {
    let removed = false
    const fetch = fakeFetch(replies({
      '/api/chats': () => ({ body: removed ? { chats: [STOCK], removed: [{ ...SALES, archived: true }, OLD] }
                                           : { chats: [SALES, STOCK], removed: [OLD] } }),
      '/api/chats/1/remove': () => { removed = true; return { body: { chat: { ...SALES, archived: true },
        message: '"Net sales by month" was removed from your chats - its questions are still in History.' } } },
      '/api/chats/2': { body: { chat: STOCK, total: 1, earlier: 0, cards: [card(21, 'Stock value?', { has_rows: false })] } },
    }))

    renderAt('/c/1', <AskPage me={ASHA} />)
    const row = await openMenu('Net sales by month')
    fireEvent.click(within(row).getByRole('button', { name: /Remove from list/ }))

    expect(await screen.findByText(/was removed from your chats/)).toBeInTheDocument()   // a toast
    expect(callsTo(fetch, '/api/chats/1/remove')).toHaveLength(1)
    await waitFor(() => expect(window.location.pathname).toBe('/c/2'))    // never back into the removed chat
    expect(await screen.findByText('Removed chats (2)')).toBeInTheDocument()
  })

  it('asks before deleting a chat for good, and deletes only on yes', async () => {
    const fetch = fakeFetch(replies({
      '/api/chats/1/delete': { body: { deleted: 2, message: '"Net sales by month" was deleted with its 2 questions.' } },
    }))

    renderAt('/c/1', <AskPage me={ASHA} />)
    let row = await openMenu('Net sales by month')
    fireEvent.click(within(row).getByRole('button', { name: /Delete/ }))
    let dialog = await screen.findByRole('alertdialog')                      // "Are you sure?"
    expect(dialog).toHaveAccessibleName('Delete this chat and its 2 questions permanently? This cannot be undone.')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(callsTo(fetch, '/api/chats/1/delete')).toHaveLength(0)            // "no": nothing deleted

    row = await openMenu('Net sales by month')
    fireEvent.click(within(row).getByRole('button', { name: /Delete/ }))
    dialog = await screen.findByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }))

    expect(await screen.findByText('"Net sales by month" was deleted with its 2 questions.')).toBeInTheDocument()
    expect(callsTo(fetch, '/api/chats/1/delete')).toHaveLength(1)
  })

  it('restores a removed chat and opens it', async () => {
    const fetch = fakeFetch(replies({
      '/api/chats/3/restore': { body: { chat: { ...OLD, archived: false } } },
      '/api/chats/3': { body: { chat: { ...OLD, archived: false }, total: 1, earlier: 0, cards: [card(31, 'Old one', { has_rows: false })] } },
    }))

    renderAt('/c/1', <AskPage me={ASHA} />)
    fireEvent.click(await screen.findByText('Removed chats (1)'))
    fireEvent.click(screen.getByRole('button', { name: 'Restore' }))

    await waitFor(() => expect(window.location.pathname).toBe('/c/3'))
    expect(callsTo(fetch, '/api/chats/3/restore')).toHaveLength(1)
    expect(await screen.findByText('Answer to Old one')).toBeInTheDocument()
  })

  it('shows a removed chat with "Restore it"', async () => {
    fakeFetch(replies({ '/api/chats/3': { body: { chat: OLD, total: 1, earlier: 0, cards: [card(31, 'Old one', { has_rows: false })] } } }))

    renderAt('/c/3', <AskPage me={ASHA} />)

    expect(await screen.findByText('This chat was removed from your list.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Restore it' })).toBeInTheDocument()
  })

  it('edits an old question: the new answer takes its place', async () => {
    const edited = card(13, 'Net sales in July?', { edited: true, token_notice: 'This question used 4,344 tokens' })
    const fetch = fakeFetch(replies({
      '/api/questions/11/edit': { body: { chat: SALES, card: edited, replaced: 11 } },
      '/api/questions/13/rows': { body: ROWS },
    }))

    renderAt('/c/1', <AskPage me={ASHA} />)
    await screen.findByText('Answer to Net sales in Aug?')
    fireEvent.click(screen.getAllByRole('button', { name: 'Edit this question' })[0])
    const box = screen.getByLabelText('Edit the question')
    expect(box).toHaveValue('Net sales in Aug?')
    fireEvent.change(box, { target: { value: 'Net sales in July?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save & ask' }))

    expect(await screen.findByText('Answer to Net sales in July?')).toBeInTheDocument()
    expect(callsTo(fetch, '/api/questions/11/edit')).toEqual([{ question: 'Net sales in July?' }])
    expect(screen.queryByText('Answer to Net sales in Aug?')).not.toBeInTheDocument()
    const bubbles = [...document.querySelectorAll('.bubble')].map((b) => b.textContent)
    expect(bubbles).toEqual(['Net sales in July?', 'And for Sep?'])           // same place
    expect(screen.getByText('This question used 4,344 tokens')).toBeInTheDocument()
    expect(screen.getByText(/· edited/)).toBeInTheDocument()
    await waitFor(() => expect(fetch.mock.calls.map(([url]) => url)).toContain('/api/questions/13/rows'))
  })

  it('keeps the edit box open with the message when the edit is refused', async () => {
    fakeFetch(replies({ '/api/questions/11/edit': { status: 400, body: { detail: 'Type the edited question first.' } } }))

    renderAt('/c/1', <AskPage me={ASHA} />)
    await screen.findByText('Answer to Net sales in Aug?')
    fireEvent.click(screen.getAllByRole('button', { name: 'Edit this question' })[0])
    fireEvent.click(screen.getByRole('button', { name: 'Save & ask' }))   // the text is still there: sent as is

    expect(await screen.findByRole('alert')).toHaveTextContent('Type the edited question first.')
    expect(screen.getByLabelText('Edit the question')).toBeInTheDocument()
  })

  it('shows one saved answer with its rows and a link to its chat', async () => {
    const fetch = fakeFetch(replies({
      '/api/questions/11': { body: { card: card(11, 'Net sales in Aug?'), chat: SALES } },
      '/api/questions/11/rows': { body: ROWS },
    }))

    renderAt('/q/11', <AskPage me={ASHA} />)

    expect(await screen.findByText('Saved answer')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Net sales by month', current: false })).toBeInTheDocument()
    expect(screen.getByLabelText('Your question')).toHaveValue('Net sales in Aug?')   // asking continues that chat
    await waitFor(() => expect(fetch.mock.calls.map(([url]) => url)).toContain('/api/questions/11/rows'))
  })

  it('fills the box from an example link', async () => {
    fakeFetch(replies())

    renderAt('/new?q=Open%20sales%20orders%3F', <AskPage me={ASHA} />)

    expect(await screen.findByLabelText('Your question')).toHaveValue('Open sales orders?')
    expect(screen.getByText('What would you like to know?')).toBeInTheDocument()
  })
})

describe('AskPage: the small chat list (05-Nov)', () => {
  it('hides the chat list to a slim rail, and opens it again', async () => {
    fakeFetch(replies())
    const { container } = renderAt('/c/1', <AskPage me={ASHA} />)
    await screen.findByRole('link', { name: 'Net sales by month' })

    fireEvent.click(screen.getByRole('button', { name: 'Hide the chat list' }))
    expect(container.querySelector('.ask-layout')).toHaveClass('chats-slim')
    expect(container.querySelector('.chats')).toHaveClass('slim')
    expect(screen.queryByRole('link', { name: 'Net sales by month' })).not.toBeInTheDocument()   // only the rail
    expect(screen.queryByText('Today')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New chat' })).toBeInTheDocument()
    expect(screen.getByText('Answer to And for Sep?')).toBeInTheDocument()                        // the answers stay
    expect(window.localStorage.getItem('mi.chatListSlim')).toBe('1')

    fireEvent.click(screen.getByRole('button', { name: 'Show the chat list' }))
    expect(container.querySelector('.ask-layout')).not.toHaveClass('chats-slim')
    expect(screen.getByRole('link', { name: 'Net sales by month' })).toBeInTheDocument()
    expect(screen.getByText('Today')).toBeInTheDocument()
    expect(window.localStorage.getItem('mi.chatListSlim')).toBeNull()
  })

  it('"New chat" works from the rail', async () => {
    window.localStorage.setItem('mi.chatListSlim', '1')
    fakeFetch(replies())
    renderAt('/c/1', <AskPage me={ASHA} />)
    await screen.findByText('Answer to And for Sep?')

    fireEvent.click(screen.getByRole('button', { name: 'New chat' }))
    expect(window.location.pathname).toBe('/new')
    expect(await screen.findByText('What would you like to know?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show the chat list' })).toBeInTheDocument()       // still small
  })

  it('keeps the choice in this browser (a new page load starts small)', async () => {
    fakeFetch(replies())
    const first = renderAt('/c/1', <AskPage me={ASHA} />)
    await screen.findByRole('link', { name: 'Net sales by month' })
    fireEvent.click(screen.getByRole('button', { name: 'Hide the chat list' }))
    first.unmount()

    const { container } = renderAt('/c/1', <AskPage me={ASHA} />)
    await screen.findByText('Answer to And for Sep?')
    expect(container.querySelector('.ask-layout')).toHaveClass('chats-slim')
    expect(screen.getByRole('button', { name: 'Show the chat list' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('link', { name: 'Net sales by month' })).not.toBeInTheDocument()
  })

  it('the phone drawer shows the whole list, also when the list was made small', async () => {
    window.localStorage.setItem('mi.chatListSlim', '1')
    fakeFetch(replies())
    renderAt('/c/1', <AskPage me={ASHA} />)
    await screen.findByText('Answer to And for Sep?')

    fireEvent.click(screen.getByRole('button', { name: 'Chats' }))                                // the phone's "Chats"
    expect(await screen.findByRole('link', { name: 'Net sales by month' })).toBeInTheDocument()
  })

  it('opens the list when the browser storage is blocked', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    fakeFetch(replies())
    const { container } = renderAt('/c/1', <AskPage me={ASHA} />)
    await screen.findByRole('link', { name: 'Net sales by month' })

    fireEvent.click(screen.getByRole('button', { name: 'Hide the chat list' }))                   // still works on this page
    expect(container.querySelector('.ask-layout')).toHaveClass('chats-slim')
  })
})
