// The Ask page's chat actions: the "..." menu of the open chat in its head (Rename / Remove from list / Delete,
// which asks first), a removed chat with "Restore it", editing an old question (its new answer takes the old
// one's place), a saved answer on its own (/q/<id>), the example link (/new?q=) and only the newest answer's
// rows. No chat list on this page since 12-Nov: the chats are History's "Chats" tab (HistoryChats.test.tsx).
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
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

/** Opens the "..." menu of the open chat (in the head of the conversation). */
async function openMenu() {
  const head = (await screen.findByText('Net sales by month', { selector: '.conv-title' })).closest('.conv-head') as HTMLElement
  fireEvent.click(within(head).getByRole('button', { name: 'Options for this chat' }))
  return head
}

describe('AskPage chat actions', () => {
  it('has no chat list (12-Nov: "New chat" and "History" are in the top bar) and loads only the newest rows', async () => {
    const fetch = fakeFetch(replies())

    renderAt('/c/1', <AskPage me={ASHA} />)

    expect(await screen.findByText('Answer to And for Sep?')).toBeInTheDocument()
    expect(screen.queryByRole('complementary', { name: 'Your chats' })).not.toBeInTheDocument()
    expect(screen.queryByText('Removed chats (1)')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Stock value' })).not.toBeInTheDocument()   // another chat: in History
    expect(screen.queryByRole('button', { name: /^Chats$|Hide the chat list|Show the chat list/ })).not.toBeInTheDocument()
    expect(document.querySelector('.ask-layout')).toHaveClass('chats-none')
    await waitFor(() => expect(fetch.mock.calls.map(([url]) => url)).toContain('/api/questions/12/rows'))
    expect(fetch.mock.calls.map(([url]) => url)).not.toContain('/api/questions/11/rows')   // older: on "Show rows"
  })

  it('renames the open chat from the menu in its head', async () => {
    const fetch = fakeFetch(replies({ '/api/chats/1/rename': { body: { chat: { ...SALES, title: 'Sales per month' } } } }))

    renderAt('/c/1', <AskPage me={ASHA} />)
    const head = await openMenu()
    expect(within(head).getByText('2 questions · last one 03 Nov, 09:05 AM')).toBeInTheDocument()
    fireEvent.change(within(head).getByLabelText('New title for this chat'), { target: { value: 'Sales per month' } })
    fireEvent.click(within(head).getByRole('button', { name: 'Rename' }))

    await waitFor(() => expect(callsTo(fetch, '/api/chats/1/rename')).toEqual([{ title: 'Sales per month' }]))
    expect(await screen.findByText('Sales per month', { selector: '.conv-title' })).toBeInTheDocument()
  })

  it('removes the open chat and says where its questions are', async () => {
    let removed = false
    const fetch = fakeFetch(replies({
      '/api/chats': () => ({ body: removed ? { chats: [STOCK], removed: [{ ...SALES, archived: true }, OLD] }
                                           : { chats: [SALES, STOCK], removed: [OLD] } }),
      '/api/chats/1/remove': () => { removed = true; return { body: { chat: { ...SALES, archived: true },
        message: '"Net sales by month" was removed from your chats - its questions are still in History.' } } },
      '/api/chats/2': { body: { chat: STOCK, total: 1, earlier: 0, cards: [card(21, 'Stock value?', { has_rows: false })] } },
    }))

    renderAt('/c/1', <AskPage me={ASHA} />)
    const head = await openMenu()
    fireEvent.click(within(head).getByRole('button', { name: /Remove from list/ }))

    expect(await screen.findByText(/was removed from your chats/)).toBeInTheDocument()   // a toast
    expect(callsTo(fetch, '/api/chats/1/remove')).toHaveLength(1)
    await waitFor(() => expect(window.location.pathname).toBe('/c/2'))    // never back into the removed chat
  })

  it('asks before deleting the open chat for good, and deletes only on yes', async () => {
    const fetch = fakeFetch(replies({
      '/api/chats/1/delete': { body: { deleted: 2, message: '"Net sales by month" was deleted with its 2 questions.' } },
    }))

    renderAt('/c/1', <AskPage me={ASHA} />)
    let head = await openMenu()
    fireEvent.click(within(head).getByRole('button', { name: /Delete/ }))
    let dialog = await screen.findByRole('alertdialog')                      // "Are you sure?"
    expect(dialog).toHaveAccessibleName('Delete this chat and its 2 questions permanently? This cannot be undone.')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(callsTo(fetch, '/api/chats/1/delete')).toHaveLength(0)            // "no": nothing deleted

    head = await openMenu()
    fireEvent.click(within(head).getByRole('button', { name: /Delete/ }))
    dialog = await screen.findByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }))

    expect(await screen.findByText('"Net sales by month" was deleted with its 2 questions.')).toBeInTheDocument()
    expect(callsTo(fetch, '/api/chats/1/delete')).toHaveLength(1)
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
