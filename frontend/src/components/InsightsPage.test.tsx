// ML Insights (/insights, every user): the page's own question box (an ML chat, mode "ml", 17-Nov) - the ready
// questions, the streamed answer, follow-ups, an ML chat opened from its address (/insights?chat=<id>). 18-Nov:
// /insights alone reopens the latest ML chat, the top bar's "New chat" starts a new ML chat on this page
// (/insights?new=1; no "New ML chat" button); the 6 result cards moved to the ML Dashboard (MlDashboard.test.tsx) -
// a link at the top opens it, and its "Ask about this" comes back as /insights?new=1&ask=<question>, asked once.
// ECharts and fetch are fakes.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { askInMlPath, parseRoute } from '../router'
import { charts } from '../test/fakeEcharts'
import { callsTo, fakeFetch, type Replies } from '../test/fakeFetch'
import { ASHA, renderAt } from '../test/render'
import type { Card, ChatSummary } from '../types'
import AskPage from './AskPage'
import InsightsPage from './InsightsPage'
import { ASK } from './MlDashboard'

vi.mock('../charts/echarts', () => import('../test/fakeEcharts'))

afterEach(() => {
  charts.length = 0
})

describe('ML Insights in the app', () => {
  it('is in the menu (Intelligence) for a normal user, lit on its page, with its tab title; no result cards', async () => {
    expect(parseRoute('/insights')).toEqual({ kind: 'insights', chat: null, fresh: false, ask: '' })
    expect(parseRoute('/insights', '?chat=7')).toEqual({ kind: 'insights', chat: 7, fresh: false, ask: '' })
    expect(parseRoute('/insights', '?new=1')).toEqual({ kind: 'insights', chat: null, fresh: true, ask: '' })
    expect(parseRoute('/insights', '?new=1&ask=Which%20items%3F')).toEqual({ kind: 'insights', chat: null, fresh: true, ask: 'Which items?' })
    expect(parseRoute('/insights', '?chat=7&ask=Which%20items%3F')).toEqual({ kind: 'insights', chat: 7, fresh: false, ask: '' })
    const fetch = fakeFetch({ '/api/me': { body: ASHA }, '/api/chats': { body: { chats: [], removed: [] } } })
    window.history.pushState(null, '', '/insights')
    render(<App />)
    const link = await screen.findByRole('link', { name: 'ML Insights' }, { timeout: 4000 })
    expect(link).toHaveAttribute('href', '/insights')
    expect(link).toHaveAttribute('aria-current', 'page')
    const group = screen.getByRole('group', { name: 'Intelligence' })
    expect(within(group).getAllByRole('link').map((a) => a.textContent)).toEqual(['Knowledge graph', 'ML Insights', 'ML Dashboard'])
    await waitFor(() => expect(document.title).toBe('ML Insights · SS Manufacturing'))
    expect(screen.getByRole('heading', { level: 1, name: 'ML Insights' })).toBeInTheDocument()
    expect(await screen.findByLabelText('Your question about forecasts and insights')).toBeInTheDocument()
    // the cards are on the ML Dashboard now: not read, not shown here
    expect(fetch).not.toHaveBeenCalledWith('/api/insights', expect.anything())
    expect(screen.queryByRole('region', { name: 'Stock running out' })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Latest results' })).not.toBeInTheDocument()
  })
})


// ------------------------------------------------------------------------------------------------ the ML chat

const ML_CHAT: ChatSummary = { id: 7, title: ASK.forecast, archived: false, created_at: '', created_text: '17 Nov 2026 10:00 AM',
                               updated_at: '', updated_text: '17 Nov, 10:00 AM', group: 'Today', questions: 1, mode: 'ml' }
function answer(id: number, text: string, extra: Partial<Card> = {}): Card {
  return { id, text, status: 'ok', answer: `ML answer to ${text}`, understood_as: '', backup_model: '', token_notice: '',
           time_steps: [], sql: 'SELECT 1', sources: [], secs: 2.5, tries: 1, row_count: 1, has_rows: true,
           rows_url: `/api/questions/${id}/rows`, excel_url: `/api/questions/${id}/excel`, created_at: '',
           created_text: '17 Nov 2026 10:00 AM', edited: false, ...extra }
}
const FIRST = answer(41, ASK.forecast, { token_notice: 'This question used 5,000 tokens' })
const SECOND = answer(42, 'And for the next 6 months?')
const ROWS = { headers: [{ name: 'n', num: true }], rows: [[{ text: '1', num: true }]], row_count: 1, truncated: false, rows_error: '' }
const BOX = 'Your question about forecasts and insights'

/** A stream the test feeds line by line, as the server would while the question runs. */
function liveStream() {
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const stream = new ReadableStream<Uint8Array>({ start(c) { controller = c } })
  const encoder = new TextEncoder()
  return {
    reply: { body: stream, headers: { 'Content-Type': 'application/x-ndjson' } },
    send: (event: object) => controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`)),
    end: () => controller.close(),
  }
}

/** A finished stream: the given lines, then the end. */
function streamOf(...events: object[]) {
  const live = liveStream()
  events.forEach((event) => live.send(event))
  live.end()
  return live.reply
}

function mlReplies(extra: Replies = {}): Replies {
  return {
    '/api/questions/41/rows': { body: ROWS },
    '/api/questions/42/rows': { body: ROWS },
    ...extra,
  }
}

const ready = async (name: string) =>
  within(await screen.findByRole('list', { name: 'Ready questions' })).getByRole('button', { name })

describe('ML Insights: its own question box', () => {
  it('shows the box with the ready questions, a link to the ML Dashboard and no result cards', async () => {
    fakeFetch(mlReplies())
    renderAt('/insights', <InsightsPage me={ASHA} />)
    const box = await screen.findByLabelText(BOX)
    expect(box).toHaveAttribute('placeholder', 'Ask about forecasts and insights…')
    expect(within(screen.getByRole('list', { name: 'Ready questions' })).getAllByRole('button').map((b) => b.textContent))
      .toEqual([ASK.forecast, ASK.risk, ASK.segments, ASK.alerts, ASK.pairs, ASK.stock])
    // the link at the top to the ML Dashboard (the 6 result cards are there now)
    const link = screen.getByRole('link', { name: 'Open ML Dashboard' })
    expect(link).toHaveAttribute('href', '/ml-dashboard')
    const chat = screen.getByRole('region', { name: 'Ask about forecasts and insights' })
    expect(link.compareDocumentPosition(chat) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.queryByRole('region', { name: 'Latest results' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Ask about this/ })).not.toBeInTheDocument()
    fireEvent.click(link)
    expect(window.location.pathname).toBe('/ml-dashboard')
    expect(screen.queryByRole('button', { name: /New ML chat/ })).not.toBeInTheDocument()   // the top bar's "New chat" does it
  })

  it('a ready question asks in ML mode: the steps, the streamed answer, then the answer card', async () => {
    const live = liveStream()
    const fetch = fakeFetch(mlReplies({ '/api/ask/stream': live.reply }))
    renderAt('/insights', <InsightsPage me={ASHA} />)
    fireEvent.click(await ready(ASK.forecast))

    live.send({ type: 'step', label: 'Read the ML results' })
    expect(await screen.findByText(/Read the ML results/)).toBeInTheDocument()
    live.send({ type: 'token', text: 'Sales should be about ' })
    await waitFor(() => expect(document.querySelector('.live-answer .answer')).toHaveTextContent('Sales should be about'))
    live.send({ type: 'done', chat: ML_CHAT, card: FIRST })
    live.end()

    expect(await screen.findByText(FIRST.answer)).toBeInTheDocument()
    expect(document.querySelector('.live-answer')).toBeNull()
    expect(screen.getByText('This question used 5,000 tokens')).toBeInTheDocument()
    expect(callsTo(fetch, '/api/ask/stream')).toEqual([{ question: ASK.forecast, chat_id: null, mode: 'ml' }])
    expect(callsTo(fetch, '/api/ask')).toHaveLength(0)
    await waitFor(() => expect(window.location.pathname + window.location.search).toBe('/insights?chat=7'))
    // the answer sits in the conversation part
    expect(within(screen.getByRole('region', { name: 'Ask about forecasts and insights' })).getByText(FIRST.answer)).toBeInTheDocument()
  })

  it('a follow-up continues the same chat (its chat_id); the page has no "New ML chat" button of its own', async () => {
    let asked = 0
    const fetch = fakeFetch(mlReplies({
      '/api/ask/stream': () => {
        asked += 1
        return streamOf({ type: 'done', chat: ML_CHAT, card: asked === 1 ? FIRST : SECOND })
      },
    }))
    renderAt('/insights', <InsightsPage me={ASHA} />)
    fireEvent.change(await screen.findByLabelText(BOX), { target: { value: ASK.forecast } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByText(FIRST.answer)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(BOX), { target: { value: SECOND.text } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByText(SECOND.answer)).toBeInTheDocument()
    expect(screen.getByText(FIRST.answer)).toBeInTheDocument()                          // the whole conversation
    expect(callsTo(fetch, '/api/ask/stream')).toEqual([
      { question: ASK.forecast, chat_id: null, mode: 'ml' },
      { question: SECOND.text, chat_id: 7, mode: 'ml' },
    ])

    // one "New chat" only: the top bar's (see "the top bar's New chat" below)
    expect(screen.queryByRole('button', { name: /New ML chat/ })).not.toBeInTheDocument()
  })

  it('?ask= (a card of the ML Dashboard) asks the question once in a new ML chat; the address then names the chat', async () => {
    let asked = 0
    const fetch = fakeFetch(mlReplies({
      '/api/chats': { body: { chats: [ML_CHAT], removed: [] } },
      '/api/ask/stream': () => {
        asked += 1
        return streamOf({ type: 'done', chat: { ...ML_CHAT, id: 9, title: ASK.risk }, card: answer(41, ASK.risk) })
      },
    }))
    window.history.pushState(null, '', '/ml-dashboard')                                // came from the dashboard
    renderAt(askInMlPath(ASK.risk), <InsightsPage me={ASHA} />)
    const steps = window.history.length

    expect(await screen.findByText(`ML answer to ${ASK.risk}`)).toBeInTheDocument()
    expect(callsTo(fetch, '/api/ask/stream')).toEqual([{ question: ASK.risk, chat_id: null, mode: 'ml' }])
    await waitFor(() => expect(window.location.pathname + window.location.search).toBe('/insights?chat=9'))
    expect(window.history.length).toBe(steps)                                             // replaced: Back goes to the dashboard
    expect(callsTo(fetch, '/api/chats', 'GET')).toHaveLength(0)                         // not the latest ML chat (7)
    expect(screen.getByLabelText(BOX)).toHaveValue('')
    expect(asked).toBe(1)
  })

  it('?ask= leaves the address at once, so a refresh while it runs does not ask again', async () => {
    const live = liveStream()
    const fetch = fakeFetch(mlReplies({ '/api/ask/stream': live.reply }))
    const first = renderAt(askInMlPath(ASK.stock), <InsightsPage me={ASHA} />)
    await waitFor(() => expect(callsTo(fetch, '/api/ask/stream')).toHaveLength(1))
    expect(window.location.pathname + window.location.search).toBe('/insights?new=1')   // ?ask= gone while it runs
    expect(callsTo(fetch, '/api/ask/stream')).toEqual([{ question: ASK.stock, chat_id: null, mode: 'ml' }])

    // a refresh now: the page opens again at the address it shows - an empty new ML chat, nothing asked
    first.unmount()
    renderAt(window.location.pathname + window.location.search, <InsightsPage me={ASHA} />)
    expect(await screen.findByLabelText(BOX)).toHaveValue('')
    expect(callsTo(fetch, '/api/ask/stream')).toHaveLength(1)
    live.end()
  })

  it('asks the plain way in ML mode when the stream cannot be used', async () => {
    const fetch = fakeFetch(mlReplies({
      '/api/ask/stream': { body: new Blob(['<html>Bad gateway</html>']), headers: { 'Content-Type': 'text/html' } },
      '/api/ask': { body: { chat: ML_CHAT, card: FIRST } },
    }))
    renderAt('/insights', <InsightsPage me={ASHA} />)
    fireEvent.click(await ready(ASK.forecast))
    expect(await screen.findByText(FIRST.answer)).toBeInTheDocument()
    expect(callsTo(fetch, '/api/ask')).toEqual([{ question: ASK.forecast, chat_id: null, mode: 'ml' }])
  })

  it('a refused question shows its message and goes back into the box', async () => {
    fakeFetch(mlReplies({ '/api/ask/stream': { status: 400, body: { detail: 'Please keep the question under 1000 characters.' } } }))
    renderAt('/insights', <InsightsPage me={ASHA} />)
    fireEvent.click(await ready(ASK.stock))
    expect(await screen.findByText('Please keep the question under 1000 characters.')).toBeInTheDocument()
    expect(screen.getByLabelText(BOX)).toHaveValue(ASK.stock)
  })

  it('opens an ML chat from its address (/insights?chat=<id>) and a follow-up continues it', async () => {
    const fetch = fakeFetch(mlReplies({
      '/api/chats/7': { body: { chat: ML_CHAT, total: 1, earlier: 0, cards: [FIRST] } },
      '/api/ask/stream': () => streamOf({ type: 'done', chat: ML_CHAT, card: SECOND }),
    }))
    renderAt('/insights?chat=7', <InsightsPage me={ASHA} />)
    expect(await screen.findByText(FIRST.answer)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /New ML chat/ })).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(BOX), { target: { value: SECOND.text } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByText(SECOND.answer)).toBeInTheDocument()
    expect(callsTo(fetch, '/api/ask/stream')).toEqual([{ question: SECOND.text, chat_id: 7, mode: 'ml' }])
  })

  it('the app opens /insights?chat=<id> on ML Insights with that chat', async () => {
    fakeFetch(mlReplies({
      '/api/me': { body: ASHA },
      '/api/chats/7': { body: { chat: ML_CHAT, total: 1, earlier: 0, cards: [FIRST] } },
    }))
    window.history.pushState(null, '', '/insights?chat=7')
    render(<App />)
    expect(await screen.findByText(FIRST.answer, {}, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'ML Insights' })).toBeInTheDocument()
  })
})

describe('ML Insights: back to the latest ML chat, and the top bar\'s New chat (18-Nov)', () => {
  const NORMAL: ChatSummary = { ...ML_CHAT, id: 8, title: 'Net sales by month', mode: '' }
  const OLDER_ML: ChatSummary = { ...ML_CHAT, id: 5, title: 'An older ML chat' }
  const where = () => window.location.pathname + window.location.search

  it('/insights alone reopens the latest ML chat (not an Assistant chat); the address names it without a new Back step', async () => {
    const fetch = fakeFetch(mlReplies({
      '/api/chats': { body: { chats: [NORMAL, ML_CHAT, OLDER_ML], removed: [] } },
      '/api/chats/7': { body: { chat: ML_CHAT, total: 1, earlier: 0, cards: [FIRST] } },
    }))
    renderAt('/insights', <InsightsPage me={ASHA} />)
    const steps = window.history.length
    expect(await screen.findByText(FIRST.answer)).toBeInTheDocument()
    expect(where()).toBe('/insights?chat=7')
    expect(window.history.length).toBe(steps)                                             // replaced, not added
    expect(fetch).not.toHaveBeenCalledWith('/api/chats/8', expect.anything())
    expect(fetch).not.toHaveBeenCalledWith('/api/chats/5', expect.anything())
  })

  it('with no ML chat yet /insights stays the empty box', async () => {
    const fetch = fakeFetch(mlReplies({ '/api/chats': { body: { chats: [NORMAL], removed: [] } } }))
    renderAt('/insights', <InsightsPage me={ASHA} />)
    await waitFor(() => expect(callsTo(fetch, '/api/chats', 'GET')).toHaveLength(1))
    expect(screen.getByLabelText(BOX)).toBeInTheDocument()
    expect(where()).toBe('/insights')
    expect(screen.queryByLabelText('ML chat')).not.toBeInTheDocument()
    expect(screen.getByLabelText(BOX)).toHaveValue('')
    expect(fetch).not.toHaveBeenCalledWith('/api/chats/8', expect.anything())
  })

  it('/insights?new=1 (a new ML chat) stays empty: the latest ML chat is not looked up', async () => {
    const fetch = fakeFetch(mlReplies({ '/api/chats': { body: { chats: [ML_CHAT], removed: [] } } }))
    renderAt('/insights?new=1', <InsightsPage me={ASHA} />)
    expect(await screen.findByLabelText(BOX)).toHaveValue('')
    expect(callsTo(fetch, '/api/chats', 'GET')).toHaveLength(0)
    expect(where()).toBe('/insights?new=1')
    expect(screen.queryByText(FIRST.answer)).not.toBeInTheDocument()
  })

  it('the top bar\'s New chat on ML Insights clears the ML chat and stays there; asking then starts a new ML chat', async () => {
    const NEW_CHAT: ChatSummary = { ...ML_CHAT, id: 9, title: ASK.stock }
    const NEW_CARD = answer(44, ASK.stock)
    const fetch = fakeFetch(mlReplies({
      '/api/me': { body: ASHA },
      '/api/chats': { body: { chats: [ML_CHAT], removed: [] } },
      '/api/chats/7': { body: { chat: ML_CHAT, total: 1, earlier: 0, cards: [FIRST] } },
      '/api/ask/stream': () => streamOf({ type: 'done', chat: NEW_CHAT, card: NEW_CARD }),
      '/api/questions/44/rows': { body: ROWS },
    }))
    window.history.pushState(null, '', '/insights')                                    // e.g. the menu link
    render(<App />)
    expect(await screen.findByText(FIRST.answer, {}, { timeout: 4000 })).toBeInTheDocument()
    expect(where()).toBe('/insights?chat=7')

    fireEvent.change(screen.getByLabelText(BOX), { target: { value: 'half typed' } })
    const newChat = within(screen.getByRole('banner')).getByRole('link', { name: 'New chat' })
    expect(newChat).toHaveAttribute('href', '/insights?new=1')
    fireEvent.click(newChat)
    await waitFor(() => expect(screen.queryByText(FIRST.answer)).not.toBeInTheDocument())
    expect(where()).toBe('/insights?new=1')
    expect(screen.getByLabelText(BOX)).toHaveValue('')
    expect(screen.getByRole('heading', { level: 1, name: 'ML Insights' })).toBeInTheDocument()
    expect(callsTo(fetch, '/api/chats', 'GET')).toHaveLength(1)                         // the old chat is not reopened

    fireEvent.click(await ready(ASK.stock))
    expect(await screen.findByText(NEW_CARD.answer)).toBeInTheDocument()
    expect(callsTo(fetch, '/api/ask/stream')).toEqual([{ question: ASK.stock, chat_id: null, mode: 'ml' }])
    await waitFor(() => expect(where()).toBe('/insights?chat=9'))
    expect(screen.queryByText(FIRST.answer)).not.toBeInTheDocument()
  })
})

describe('ML chats and the Assistant', () => {
  it('an ML chat opened at /c/<id> goes on to ML Insights', async () => {
    fakeFetch({
      '/api/chats': { body: { chats: [ML_CHAT], removed: [] } },
      '/api/chats/7': { body: { chat: ML_CHAT, total: 1, earlier: 0, cards: [FIRST] } },
    })
    renderAt('/c/7', <AskPage me={ASHA} />)
    await waitFor(() => expect(window.location.pathname + window.location.search).toBe('/insights?chat=7'))
  })

  it('/ask opens the latest Assistant chat, not an ML chat', async () => {
    const normal: ChatSummary = { ...ML_CHAT, id: 8, title: 'Net sales by month', mode: '' }
    fakeFetch({
      '/api/chats': { body: { chats: [ML_CHAT, normal], removed: [] } },
      '/api/chats/8': { body: { chat: normal, total: 1, earlier: 0, cards: [answer(43, 'Net sales by month')] } },
      '/api/questions/43/rows': { body: ROWS },
    })
    renderAt('/ask', <AskPage me={ASHA} />)
    await waitFor(() => expect(window.location.pathname).toBe('/c/8'))
  })
})
