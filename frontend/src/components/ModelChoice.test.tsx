// The administrators' model choice in the question box (18-Nov): the small model pill on the Assistant (start
// screen and under a conversation) and on ML Insights, with the models of /api/models; the chosen model goes
// with the question as "model" (none for Auto) and is kept in this browser. Other users see no pill and the
// models list is never asked for. fetch is a fake.
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { callsTo, fakeFetch, type Replies } from '../test/fakeFetch'
import { ASHA, BOSS, renderAt } from '../test/render'
import type { Card, ChatSummary } from '../types'
import AskPage from './AskPage'
import InsightsPage from './InsightsPage'

vi.mock('../charts/echarts', () => import('../test/fakeEcharts'))

const QUESTION = 'Top 3 customers in Aug?'
const CHAT: ChatSummary = { id: 7, title: QUESTION, archived: false, created_at: '', created_text: '18 Nov 2026 09:00 AM',
                            updated_at: '', updated_text: '18 Nov, 09:00 AM', group: 'Today', questions: 1 }
const CARD: Card = {
  id: 41, text: QUESTION, status: 'ok', answer: 'Aurora had the most.', understood_as: '', backup_model: '',
  token_notice: '', time_steps: [], sql: 'SELECT 1', sources: [], secs: 2, tries: 1, row_count: 1, has_rows: false,
  rows_url: '/api/questions/41/rows', excel_url: '/api/questions/41/excel', created_at: '',
  created_text: '18 Nov 2026 09:00 AM', edited: false,
}
const MODELS = {
  models: [
    { id: 'auto', label: 'Auto (recommended)', available: true },
    { id: 'groq-main', label: 'Groq gpt-oss-120b', available: true },
    { id: 'groq-main-2', label: 'Groq gpt-oss-120b (2nd key)', available: false, note: 'no API key set' },
    { id: 'groq-backup', label: 'Groq backup', available: true },
  ],
}

/** The finished stream of one answer. */
function done() {
  const line = new TextEncoder().encode(`${JSON.stringify({ type: 'done', chat: CHAT, card: CARD })}\n`)
  const body = new ReadableStream<Uint8Array>({ start(c) { c.enqueue(line); c.close() } })
  return { body, headers: { 'Content-Type': 'application/x-ndjson' } }
}

function replies(extra: Replies = {}): Replies {
  return {
    '/api/models': { body: MODELS },
    '/api/chats': { body: { chats: [], removed: [] } },
    '/api/chats/7': { body: { chat: CHAT, total: 1, earlier: 0, cards: [CARD] } },
    '/api/ask/stream': () => done(),
    ...extra,
  }
}

// 20-Nov: the company's own model on a CPU server ("local"): never in Auto, only when an administrator picks it
const HINT = "Runs on the company's CPU server - an answer can take a few minutes"
const LOCAL = { id: 'local', label: 'Local (llama3.1:8b)', available: true, hint: HINT }
const WITH_LOCAL = { models: [...MODELS.models, LOCAL] }
const LOCAL_OFF = { models: [...MODELS.models,
  { id: 'local', label: 'Local (llama3.1:8b)', available: false, note: 'LOCAL_LLM_URL / LOCAL_LLM_MODEL not set in .env', hint: HINT }] }

/** A stream the test feeds line by line (it stays open until end()). */
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

/** The line under "Thinking…" / the steps that names the slow model and its hint. */
const slowNote = () => screen.findByText((_, el) => el?.hasAttribute('data-slow-model') ?? false)

const picker = () => screen.findByRole('combobox', { name: 'AI model' })

async function ask(label = 'Your question', text = QUESTION) {
  fireEvent.change(await screen.findByLabelText(label), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
}

describe('the model pill (administrators)', () => {
  it('shows the fetched models in the start screen box, Auto first; an unavailable one greyed out with its note', async () => {
    const fetch = fakeFetch(replies())
    renderAt('/new', <AskPage me={BOSS} />)
    const select = await picker()
    expect(select.closest('[data-question-box]')).not.toBeNull()     // inside the question box
    expect(select).toHaveValue('auto')
    expect(select.closest('label')).toHaveTextContent('Auto')
    const options = within(select).getAllByRole('option') as HTMLOptionElement[]
    expect(options.map((o) => o.textContent)).toEqual(
      ['Auto (recommended)', 'Groq gpt-oss-120b', 'Groq gpt-oss-120b (2nd key) - no API key set', 'Groq backup'])
    expect(options.map((o) => o.disabled)).toEqual([false, false, true, false])
    expect(options[2]).toHaveAttribute('title', 'no API key set')
    expect(fetch.mock.calls.filter(([url]) => url === '/api/models')).toHaveLength(1)
  })

  it('Auto sends no "model"; a chosen model goes with the question, shows on the pill and is kept', async () => {
    const fetch = fakeFetch(replies())
    renderAt('/new', <AskPage me={BOSS} />)
    await picker()
    await ask()
    expect(await screen.findByText(CARD.answer)).toBeInTheDocument()
    expect(callsTo(fetch, '/api/ask/stream')).toEqual([{ question: QUESTION, chat_id: null }])

    // under the conversation now: the same pill in the bottom box
    fireEvent.change(await picker(), { target: { value: 'groq-backup' } })
    expect((await picker()).closest('label')).toHaveTextContent('Groq backup')
    expect(window.localStorage.getItem('askModel')).toBe('groq-backup')
    await ask('Your question', 'And for Sep?')
    await waitFor(() => expect(callsTo(fetch, '/api/ask/stream')).toHaveLength(2))
    expect(callsTo(fetch, '/api/ask/stream')[1]).toEqual({ question: 'And for Sep?', chat_id: 7, model: 'groq-backup' })

    // back to Auto: forgotten, no "model" again
    fireEvent.change(await picker(), { target: { value: 'auto' } })
    expect(window.localStorage.getItem('askModel')).toBeNull()
  })

  it('the kept choice is there on the next visit and is used; a kept model that is unavailable today asks with Auto', async () => {
    window.localStorage.setItem('askModel', 'groq-backup')
    const fetch = fakeFetch(replies())
    const { unmount } = renderAt('/new', <AskPage me={BOSS} />)
    expect(await picker()).toHaveValue('groq-backup')
    await ask()
    await waitFor(() => expect(callsTo(fetch, '/api/ask/stream')).toEqual([{ question: QUESTION, chat_id: null, model: 'groq-backup' }]))
    unmount()

    window.localStorage.setItem('askModel', 'groq-main-2')   // unavailable in the list
    const fetch2 = fakeFetch(replies())
    renderAt('/new', <AskPage me={BOSS} />)
    expect(await picker()).toHaveValue('auto')
    await ask()
    await waitFor(() => expect(callsTo(fetch2, '/api/ask/stream')).toEqual([{ question: QUESTION, chat_id: null }]))
  })

  it('the plain /api/ask (no stream) gets the chosen model too', async () => {
    window.localStorage.setItem('askModel', 'groq-main')
    const fetch = fakeFetch(replies({
      '/api/ask/stream': { status: 404, body: { detail: 'Not found.' } },
      '/api/ask': { body: { chat: CHAT, card: CARD } },
    }))
    renderAt('/new', <AskPage me={BOSS} />)
    await picker()
    await ask()
    expect(await screen.findByText(CARD.answer)).toBeInTheDocument()
    expect(callsTo(fetch, '/api/ask')).toEqual([{ question: QUESTION, chat_id: null, model: 'groq-main' }])
  })

  it('on ML Insights too: the chosen model goes with the ML question', async () => {
    window.localStorage.setItem('askModel', 'groq-backup')
    const fetch = fakeFetch(replies({ '/api/ask/stream': () => done() }))
    renderAt('/insights', <InsightsPage me={BOSS} />)
    expect(await picker()).toHaveValue('groq-backup')
    await ask('Your question about forecasts and insights')
    await waitFor(() => expect(callsTo(fetch, '/api/ask/stream')).toEqual(
      [{ question: QUESTION, chat_id: null, mode: 'ml', model: 'groq-backup' }]))
  })

  it('no pill and Auto when the models list cannot be read', async () => {
    window.localStorage.setItem('askModel', 'groq-main')
    const fetch = fakeFetch(replies({ '/api/models': { status: 500, body: { detail: 'Boom' } } }))
    renderAt('/new', <AskPage me={BOSS} />)
    await waitFor(() => expect(fetch.mock.calls.map(([url]) => url)).toContain('/api/models'))
    await ask()
    await waitFor(() => expect(callsTo(fetch, '/api/ask/stream')).toEqual([{ question: QUESTION, chat_id: null }]))
    expect(screen.queryByRole('combobox', { name: 'AI model' })).not.toBeInTheDocument()
  })
})

describe('the model pill (other users)', () => {
  it('is not there and the models list is never asked for (Assistant and ML Insights)', async () => {
    window.localStorage.setItem('askModel', 'groq-main')   // e.g. left by an administrator on this browser
    const fetch = fakeFetch(replies())
    const { unmount } = renderAt('/new', <AskPage me={ASHA} />)
    await ask()
    expect(await screen.findByText(CARD.answer)).toBeInTheDocument()
    expect(callsTo(fetch, '/api/ask/stream')).toEqual([{ question: QUESTION, chat_id: null }])
    expect(screen.queryByRole('combobox', { name: 'AI model' })).not.toBeInTheDocument()
    unmount()

    renderAt('/insights', <InsightsPage me={ASHA} />)
    expect(await screen.findByLabelText('Your question about forecasts and insights')).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'AI model' })).not.toBeInTheDocument()
    expect(fetch.mock.calls.map(([url]) => url)).not.toContain('/api/models')
  })
})

describe('the local model (company CPU server, 20-Nov)', () => {
  it('is listed with its hint after the name (and as the tooltip); picking it sends model "local"', async () => {
    const fetch = fakeFetch(replies({ '/api/models': { body: WITH_LOCAL } }))
    renderAt('/new', <AskPage me={BOSS} />)
    const select = await picker()
    const local = within(select).getByRole('option', { name: `Local (llama3.1:8b) - ${HINT}` }) as HTMLOptionElement
    expect(local.disabled).toBe(false)
    expect(local).toHaveAttribute('title', HINT)
    // a model without a hint: only its name, as before
    expect(within(select).getByRole('option', { name: 'Groq backup' })).not.toHaveAttribute('title')

    fireEvent.change(select, { target: { value: 'local' } })
    const pill = (await picker()).closest('label')!
    expect(pill).toHaveTextContent('Local (llama3.1:8b)')
    expect(pill).toHaveAttribute('title', `Local (llama3.1:8b): ${HINT}`)
    await ask()
    expect(await screen.findByText(CARD.answer)).toBeInTheDocument()
    expect(callsTo(fetch, '/api/ask/stream')).toEqual([{ question: QUESTION, chat_id: null, model: 'local' }])
  })

  it('not set up: greyed out with the note (not the hint) and a kept "local" asks with Auto', async () => {
    window.localStorage.setItem('askModel', 'local')
    const fetch = fakeFetch(replies({ '/api/models': { body: LOCAL_OFF } }))
    renderAt('/new', <AskPage me={BOSS} />)
    const select = await picker()
    const local = within(select).getByRole('option',
      { name: 'Local (llama3.1:8b) - LOCAL_LLM_URL / LOCAL_LLM_MODEL not set in .env' }) as HTMLOptionElement
    expect(local.disabled).toBe(true)
    expect(local).toHaveAttribute('title', 'LOCAL_LLM_URL / LOCAL_LLM_MODEL not set in .env')
    expect(select).toHaveValue('auto')
    await ask()
    await waitFor(() => expect(callsTo(fetch, '/api/ask/stream')).toEqual([{ question: QUESTION, chat_id: null }]))
  })

  it('while its answer is awaited the wait says the model is slow; 5 minutes of waiting are not cut by the browser', async () => {
    // fake timers that also move with real time (so findBy works): the 20 s / 60 s texts and 5 minutes at once
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'], shouldAdvanceTime: true })
    try {
      window.localStorage.setItem('askModel', 'local')
      const live = liveStream()
      const fetch = fakeFetch(replies({ '/api/models': { body: WITH_LOCAL }, '/api/ask/stream': live.reply }))
      renderAt('/new', <AskPage me={BOSS} />)
      expect(await picker()).toHaveValue('local')
      await ask()

      // before the first step: "Thinking…" with the model's hint under it
      const note = await slowNote()
      expect(note).toHaveTextContent(`Local (llama3.1:8b): ${HINT}…`)
      expect(note.closest('[role="status"]')).toHaveTextContent('Thinking…')

      // a step came: the hint stays, under the steps
      live.send({ type: 'step', label: 'Write the SQL (AI)' })
      const steps = await screen.findByRole('list', { name: 'Steps' })
      expect(steps.closest('[role="status"]')).toHaveTextContent(HINT)

      // 5 minutes later: still waiting - no "up to a minute" (wrong for this model), the History line, no new call
      act(() => { vi.advanceTimersByTime(5 * 60 * 1000) })
      const status = screen.getByRole('list', { name: 'Steps' }).closest('[role="status"]')!
      expect(status).toHaveTextContent(HINT)
      expect(status).toHaveTextContent('you can also find it in History')
      expect(screen.queryByText(/up to a minute/)).not.toBeInTheDocument()
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
      expect(callsTo(fetch, '/api/ask/stream')).toHaveLength(1)
      expect(callsTo(fetch, '/api/ask')).toHaveLength(0)                    // not given up and asked the plain way

      // the answer still arrives and is shown
      live.send({ type: 'done', chat: CHAT, card: CARD })
      live.end()
      expect(await screen.findByText(CARD.answer)).toBeInTheDocument()
      expect(document.querySelector('[data-slow-model]')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('the plain /api/ask (no stream) shows the hint too while it waits', async () => {
    window.localStorage.setItem('askModel', 'local')
    let answer!: () => void
    const waited = new Promise<void>((done) => { answer = done })
    const fake = fakeFetch(replies({
      '/api/models': { body: WITH_LOCAL },
      '/api/ask/stream': { status: 404, body: { detail: 'Not found.' } },
      '/api/ask': { body: { chat: CHAT, card: CARD } },
    }))
    // the plain answer comes only when the test says so
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const reply = await fake(url, init)
      if (url === '/api/ask') await waited
      return reply
    }))
    renderAt('/new', <AskPage me={BOSS} />)
    expect(await picker()).toHaveValue('local')
    await ask()
    await waitFor(() => expect(callsTo(fake, '/api/ask')).toEqual([{ question: QUESTION, chat_id: null, model: 'local' }]))
    const note = await slowNote()
    expect(note).toHaveTextContent(`Local (llama3.1:8b): ${HINT}…`)
    expect(note.closest('[role="status"]')).toHaveTextContent('Thinking…')
    answer()
    expect(await screen.findByText(CARD.answer)).toBeInTheDocument()
  })

  it('Auto shows the plain "Thinking…" with no model line', async () => {
    const live = liveStream()
    fakeFetch(replies({ '/api/models': { body: WITH_LOCAL }, '/api/ask/stream': live.reply }))
    renderAt('/new', <AskPage me={BOSS} />)
    await picker()
    await ask()
    expect(await screen.findByRole('status')).toHaveTextContent('Thinking…')
    expect(document.querySelector('[data-slow-model]')).toBeNull()
    live.send({ type: 'done', chat: CHAT, card: CARD })
    live.end()
    expect(await screen.findByText(CARD.answer)).toBeInTheDocument()
  })
})
