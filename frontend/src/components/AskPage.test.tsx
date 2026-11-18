// The Ask page's chat actions: the "..." menu of the open chat (Rename / Remove from list / Delete, which asks
// first; 16-Nov: no head row - the button floats at the top right of the conversation, the browser tab shows the
// chat title, the thread sits in a centred column and the box grows with the text), a removed chat with "Restore it", editing an old question (its new answer takes the old
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

/** Opens the "..." menu of the open chat (16-Nov: no head row - the button floats at the top right of the
 *  conversation) and gives back the place of the menu. */
async function openMenu() {
  const button = await screen.findByRole('button', { name: 'Options for this chat' })
  fireEvent.click(button)
  return button.closest('.conv-menu') as HTMLElement
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

  it('has no head row above the conversation (16-Nov): the browser tab shows the chat title', async () => {
    fakeFetch(replies())

    renderAt('/c/1', <AskPage me={ASHA} />)

    expect(await screen.findByText('Answer to And for Sep?')).toBeInTheDocument()
    expect(document.querySelector('.conv-head')).toBeNull()
    expect(document.querySelector('.conv-title')).toBeNull()
    expect(screen.queryByText(/2 questions · started/)).not.toBeInTheDocument()
    expect(screen.queryByText('Net sales by month')).not.toBeInTheDocument()       // the title is in the tab only
    await waitFor(() => expect(document.title).toBe('Net sales by month · SS Manufacturing'))
    // the "..." button floats at the top right of the conversation, over the scrolled thread
    const menu = screen.getByRole('button', { name: 'Options for this chat' }).closest('.conv-menu') as HTMLElement
    expect(menu.parentElement).toHaveClass('conv-scroll', 'has-menu')
    expect(menu.nextElementSibling).toHaveClass('conv-col')
  })

  it('puts the thread and the question box in a centred column of at most 920 px', async () => {
    fakeFetch(replies())

    renderAt('/c/1', <AskPage me={ASHA} />)

    const thread = (await screen.findByText('Answer to And for Sep?')).closest('#thread') as HTMLElement
    const column = thread.closest('.conv-col') as HTMLElement
    expect(column).toHaveClass('mx-auto', 'w-full', 'max-w-[min(920px,calc(100%_-_88px))]', 'max-[700px]:max-w-full')
    const composer = screen.getByLabelText('Your question').closest('.composer') as HTMLElement
    expect(composer).toHaveClass('conv-col', 'mx-auto', 'max-w-[min(920px,calc(100%_-_88px))]')
  })

  it('a saved answer has no "..." menu and the plain 920 px column', async () => {
    fakeFetch(replies({
      '/api/questions/11': { body: { card: card(11, 'Net sales in Aug?'), chat: SALES } },
      '/api/questions/11/rows': { body: ROWS },
    }))

    renderAt('/q/11', <AskPage me={ASHA} />)

    expect(await screen.findByText('Saved answer')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Options for this chat' })).not.toBeInTheDocument()
    expect(document.querySelector('#thread')!.closest('.conv-col')).toHaveClass('max-w-[920px]')
  })

  it('the question box under a conversation is one row and grows with the text up to 6 rows', async () => {
    fakeFetch(replies())
    // jsdom does no layout: a box is 24 px per line of text and 12 px of padding high
    Object.defineProperty(HTMLTextAreaElement.prototype, 'scrollHeight', {
      configurable: true, get() { return 24 * (this as HTMLTextAreaElement).value.split('\n').length + 12 },
    })
    try {
      renderAt('/c/1', <AskPage me={ASHA} />)
      await screen.findByText('Answer to And for Sep?')
      const box = screen.getByLabelText('Your question') as HTMLTextAreaElement

      expect(box).toHaveAttribute('rows', '1')
      expect(box).toHaveClass('min-h-9!', 'max-h-[156px]!')
      expect(box.style.height).toBe('36px')                                            // one row
      fireEvent.change(box, { target: { value: 'Net sales\nby month\nfor FY 2026' } })
      expect(box.style.height).toBe('84px')                                            // three rows
      fireEvent.change(box, { target: { value: Array.from({ length: 10 }, (_, i) => `line ${i}`).join('\n') } })
      expect(box.style.height).toBe('156px')                                           // 6 rows at most, then it scrolls
      // the round send button sits inside the box, at the right of the text
      expect(box.parentElement).toContainElement(screen.getByRole('button', { name: 'Ask' }))
    } finally {
      delete (HTMLTextAreaElement.prototype as { scrollHeight?: number }).scrollHeight   // jsdom's own again
    }
  })

  it('the send button sits inside the rounded question box and is on only while there is text (17-Nov)', async () => {
    fakeFetch(replies())
    renderAt('/c/1', <AskPage me={ASHA} />)
    await screen.findByText('Answer to And for Sep?')
    const box = screen.getByLabelText('Your question')
    const send = screen.getByRole('button', { name: 'Ask' })

    // one pill: the field and the button share the same rounded container, inside the form "composer"
    const pill = box.closest('[data-question-box]') as HTMLElement
    expect(pill).toContainElement(send)
    expect(pill).toHaveClass('rounded-[28px]')
    expect(pill.closest('form')).toHaveAttribute('id', 'composer')

    expect(send).toBeDisabled()                                                    // empty: grey and off
    fireEvent.change(box, { target: { value: 'Net sales in Oct?' } })
    expect(send).toBeEnabled()                                                     // text: the brand colour
    expect(send).not.toHaveClass('bg-secondary')
    fireEvent.change(box, { target: { value: '   ' } })
    expect(send).toBeDisabled()                                                    // spaces only count as empty
  })

  it('renames the open chat from its "..." menu', async () => {
    const fetch = fakeFetch(replies({ '/api/chats/1/rename': { body: { chat: { ...SALES, title: 'Sales per month' } } } }))

    renderAt('/c/1', <AskPage me={ASHA} />)
    const menu = await openMenu()
    expect(within(menu).getByText('2 questions · last one 03 Nov, 09:05 AM')).toBeInTheDocument()
    fireEvent.change(within(menu).getByLabelText('New title for this chat'), { target: { value: 'Sales per month' } })
    fireEvent.click(within(menu).getByRole('button', { name: 'Rename' }))

    await waitFor(() => expect(callsTo(fetch, '/api/chats/1/rename')).toEqual([{ title: 'Sales per month' }]))
    await waitFor(() => expect(document.title).toBe('Sales per month · SS Manufacturing'))   // the tab follows
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
    const menu = await openMenu()
    fireEvent.click(within(menu).getByRole('button', { name: /Remove from list/ }))

    expect(await screen.findByText(/was removed from your chats/)).toBeInTheDocument()   // a toast
    expect(callsTo(fetch, '/api/chats/1/remove')).toHaveLength(1)
    await waitFor(() => expect(window.location.pathname).toBe('/c/2'))    // never back into the removed chat
  })

  it('asks before deleting the open chat for good, and deletes only on yes', async () => {
    const fetch = fakeFetch(replies({
      '/api/chats/1/delete': { body: { deleted: 2, message: '"Net sales by month" was deleted with its 2 questions.' } },
    }))

    renderAt('/c/1', <AskPage me={ASHA} />)
    let menu = await openMenu()
    fireEvent.click(within(menu).getByRole('button', { name: /Delete/ }))
    let dialog = await screen.findByRole('alertdialog')                      // "Are you sure?"
    expect(dialog).toHaveAccessibleName('Delete this chat and its 2 questions permanently? This cannot be undone.')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(callsTo(fetch, '/api/chats/1/delete')).toHaveLength(0)            // "no": nothing deleted

    menu = await openMenu()
    fireEvent.click(within(menu).getByRole('button', { name: /Delete/ }))
    dialog = await screen.findByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }))

    expect(await screen.findByText('"Net sales by month" was deleted with its 2 questions.')).toBeInTheDocument()
    expect(callsTo(fetch, '/api/chats/1/delete')).toHaveLength(1)
  })

  it('shows a removed chat with "Restore it"', async () => {
    fakeFetch(replies({ '/api/chats/3': { body: { chat: OLD, total: 1, earlier: 0, cards: [card(31, 'Old one', { has_rows: false })] } } }))

    renderAt('/c/3', <AskPage me={ASHA} />)

    const notice = await screen.findByText('This chat was removed from your list.')
    expect(screen.getByRole('button', { name: 'Restore it' })).toBeInTheDocument()
    // 16-Nov: a slim line at the top of the conversation's column, above the thread
    expect(notice.closest('.conv-col')).toContainElement(document.querySelector('#thread') as HTMLElement)
    expect(notice.parentElement!.nextElementSibling).toHaveAttribute('id', 'thread')
    expect(screen.getByRole('button', { name: 'Options for this chat' })).toBeInTheDocument()   // the menu is still there
  })

  it('"Restore it" puts a removed chat back in the list', async () => {
    const fetch = fakeFetch(replies({
      '/api/chats/3': { body: { chat: OLD, total: 1, earlier: 0, cards: [card(31, 'Old one', { has_rows: false })] } },
      '/api/chats/3/restore': { body: { chat: { ...OLD, archived: false } } },
    }))

    renderAt('/c/3', <AskPage me={ASHA} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Restore it' }))

    await waitFor(() => expect(screen.queryByText('This chat was removed from your list.')).not.toBeInTheDocument())
    expect(callsTo(fetch, '/api/chats/3/restore')).toHaveLength(1)
  })

  it('copies a question with one click and says "Copied"; marked text in the bubble can be seen (12-Nov)', async () => {
    fakeFetch(replies())
    const written: string[] = []
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (text: string) => { written.push(text) } } })

    renderAt('/c/1', <AskPage me={ASHA} />)
    const bubble = await screen.findByText('And for Sep?', { selector: '.bubble' })
    expect(bubble).toHaveClass('selection:bg-primary-foreground', 'selection:text-primary')   // not blue on blue
    const item = bubble.closest('.chat-item') as HTMLElement
    fireEvent.click(within(item).getByRole('button', { name: 'Copy this question' }))

    expect(await within(item).findByRole('button', { name: 'Copied' })).toHaveTextContent('Copied')
    expect(written).toEqual(['And for Sep?'])
    await waitFor(() => expect(within(item).getByRole('button', { name: 'Copy this question' })).toBeInTheDocument(), { timeout: 3000 })
  })

  it('copies the old way where the clipboard API is not there (plain http in the office)', async () => {
    fakeFetch(replies())
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
    const copied: string[] = []
    document.execCommand = ((command: string) => {
      copied.push(`${command}:${(document.activeElement as HTMLTextAreaElement | null)?.value ?? document.querySelector<HTMLTextAreaElement>('body > textarea')?.value}`)
      return true
    }) as typeof document.execCommand

    renderAt('/c/1', <AskPage me={ASHA} />)
    const item = (await screen.findByText('Net sales in Aug?', { selector: '.bubble' })).closest('.chat-item') as HTMLElement
    fireEvent.click(within(item).getByRole('button', { name: 'Copy this question' }))

    expect(await within(item).findByRole('button', { name: 'Copied' })).toBeInTheDocument()
    expect(copied).toEqual(['copy:Net sales in Aug?'])
    expect(document.querySelector('body > textarea')).toBeNull()                 // the hidden box is gone again
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

    const note = (await screen.findByText('Saved answer')).parentElement as HTMLElement   // a slim line, no head row
    expect(note).toHaveClass('saved-note')
    expect(note).toHaveTextContent('Saved answer · From the chat Net sales by month · the rows come from running the saved SQL again (no AI call).')
    expect(within(note).getByRole('link', { name: 'Net sales by month', current: false })).toHaveAttribute('href', '/c/1')
    expect(document.querySelector('.conv-head')).toBeNull()
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
