// The start screen of the Ask page: the heading, the question box in the middle with "MySQL ai_gold · read-only"
// and the round send button, the four starter cards (a click fills the box, nothing is asked yet), and the
// box moving to the bottom once a question is asked.
import { fireEvent, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { callsTo, fakeFetch } from '../test/fakeFetch'
import { ASHA, renderAt } from '../test/render'
import AskPage from './AskPage'
import { starterQuestions } from './AskStart'

describe('AskStart: the start screen', () => {
  it('shows the heading, the big question box and the four starter cards', async () => {
    fakeFetch({ '/api/chats': { body: { chats: [], removed: [] } } })
    renderAt('/new', <AskPage me={ASHA} />)

    const start = (await screen.findByRole('heading', { name: 'What would you like to know?' })).closest('#welcome') as HTMLElement
    const box = within(start).getByLabelText('Your question')                     // the box is in the middle, not docked
    expect(box).toHaveAttribute('placeholder', 'Ask about sales, customers, orders, stock or documents…')
    expect(within(start).getByText('MySQL ai_gold · read-only')).toBeInTheDocument()
    expect(within(start).getByRole('button', { name: 'Ask' })).toBeInTheDocument()
    expect(document.querySelector('.composer')).toBeNull()
    const cards = within(within(start).getByRole('list', { name: 'Starter questions' })).getAllByRole('button')
    expect(cards.map((c) => c.textContent)).toEqual([
      expect.stringMatching(/^Sales/), expect.stringMatching(/^Customers/),
      expect.stringMatching(/^Open orders/), expect.stringMatching(/^Stock/)])
  })

  it('a starter card fills the box and does not ask', async () => {
    const fetch = fakeFetch({ '/api/chats': { body: { chats: [], removed: [] } } })
    renderAt('/new', <AskPage me={ASHA} />)

    fireEvent.click(await screen.findByRole('button', { name: /^Stock/ }))
    expect(screen.getByLabelText('Your question')).toHaveValue('Stock value by item group on the latest stock report')
    fireEvent.click(screen.getByRole('button', { name: /^Customers/ }))            // one of the user's own examples
    expect(screen.getByLabelText('Your question')).toHaveValue('Top 5 customers by invoice value in Aug 2026?')
    expect(callsTo(fetch, '/api/ask')).toHaveLength(0)
    expect(callsTo(fetch, '/api/ask/stream')).toHaveLength(0)
  })

  it('an open chat has the question box at the bottom, without the start screen', async () => {
    const CHAT = { id: 1, title: 'Net sales', archived: false, created_at: '', created_text: '', updated_at: '', updated_text: '', group: 'Today', questions: 0 }
    fakeFetch({
      '/api/chats': { body: { chats: [CHAT], removed: [] } },
      '/api/chats/1': { body: { chat: CHAT, total: 0, earlier: 0, cards: [] } },
    })
    renderAt('/c/1', <AskPage me={ASHA} />)

    const box = await screen.findByPlaceholderText('Ask another question about NOP data…')
    expect(box.closest('.composer')).not.toBeNull()
    expect(screen.queryByText('What would you like to know?')).not.toBeInTheDocument()
    expect(screen.queryByText('MySQL ai_gold · read-only')).not.toBeInTheDocument()
  })
})

describe('starterQuestions', () => {
  it('uses the fixed questions when no example fits', () => {
    expect(starterQuestions([])).toEqual([
      'Net sales of the last 6 NOP months as a line chart', 'Top 10 customers this FY by net sales',
      'List the open sales orders up to today', 'Stock value by item group on the latest stock report'])
  })

  it('gives each fitting example to one card, the most exact card first', () => {
    const picked = starterQuestions(ASHA.examples)
    expect(picked[1]).toBe('Top 5 customers by invoice value in Aug 2026?')            // Customers, not Sales
    expect(picked[2]).toBe('How many sales orders are open and what is their value?')  // Open orders, not Sales
    expect(picked[0]).toBe('Net sales of the last 6 NOP months as a line chart')
  })
})
