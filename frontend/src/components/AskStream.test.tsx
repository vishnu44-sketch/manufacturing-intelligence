// Asking with the streamed answer (/api/ask/stream): the steps show as they run, the answer grows piece by
// piece, the finished card takes its place; when the stream cannot be used, the plain /api/ask is asked.
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { callsTo, fakeFetch } from '../test/fakeFetch'
import { ASHA, renderAt } from '../test/render'
import type { Card, ChatSummary } from '../types'
import AskPage from './AskPage'

const QUESTION = 'Top 3 export customers in FY 2025-26?'
const CHAT: ChatSummary = { id: 7, title: QUESTION, archived: false, created_at: '', created_text: '03 Nov 2026 09:00 AM',
                            updated_at: '', updated_text: '03 Nov, 09:00 AM', group: 'Today', questions: 1 }
const CARD: Card = {
  id: 41, text: QUESTION, status: 'ok', answer: 'Neptune Tech Industries Ltd had the highest export sales.',
  understood_as: '', backup_model: '', token_notice: 'This question used 6,000 tokens', time_steps: [], sql: 'SELECT 1',
  sources: [], secs: 9.5, tries: 1, row_count: 3, has_rows: true, rows_url: '/api/questions/41/rows',
  excel_url: '/api/questions/41/excel', created_at: '', created_text: '03 Nov 2026 09:00 AM', edited: false,
}
const ROWS = { headers: [{ name: 'n', num: true }], rows: [[{ text: '1', num: true }]], row_count: 1, truncated: false, rows_error: '' }

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

function replies(extra = {}) {
  return {
    '/api/chats': { body: { chats: [], removed: [] } },
    '/api/chats/7': { body: { chat: CHAT, total: 1, earlier: 0, cards: [CARD] } },
    '/api/questions/41/rows': { body: ROWS },
    ...extra,
  }
}

async function ask(text = QUESTION) {
  fireEvent.change(await screen.findByLabelText('Your question'), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: /Ask/ }))
}

describe('AskPage streamed answer', () => {
  it('shows the steps, then the answer growing, then the finished card in its place', async () => {
    const live = liveStream()
    const fetch = fakeFetch(replies({ '/api/ask/stream': live.reply }))

    renderAt('/new', <AskPage me={ASHA} />)
    await ask()

    live.send({ type: 'step', label: 'Search the notes in Qdrant' })
    expect(await screen.findByText(/Search the notes in Qdrant/)).toBeInTheDocument()
    live.send({ type: 'step', label: 'Write the SQL (AI)' })
    live.send({ type: 'step', label: 'Run the SQL on MySQL' })
    expect(await screen.findByText(/Run the SQL on MySQL/)).toBeInTheDocument()
    const steps = screen.getByRole('list', { name: 'Steps' })
    expect([...steps.querySelectorAll('li')].map((li) => li.className)).toEqual(['done', 'done', 'now'])

    live.send({ type: 'token', text: 'Neptune Tech ' })
    expect(await screen.findByText('Neptune Tech', { exact: false, selector: '.live-answer .answer' })).toBeInTheDocument()
    live.send({ type: 'token', text: 'Industries Ltd had' })
    await waitFor(() => expect(document.querySelector('.live-answer .answer')).toHaveTextContent('Neptune Tech Industries Ltd had'))
    expect(screen.queryByRole('list', { name: 'Steps' })).not.toBeInTheDocument()   // the answer took over

    live.send({ type: 'done', chat: CHAT, card: CARD })
    live.end()
    expect(await screen.findByText(CARD.answer)).toBeInTheDocument()
    expect(document.querySelector('.live-answer')).toBeNull()                        // the card took its place
    expect(screen.getByText('This question used 6,000 tokens')).toBeInTheDocument()
    await waitFor(() => expect(window.location.pathname).toBe('/c/7'))
    expect(callsTo(fetch, '/api/ask/stream')).toEqual([{ question: QUESTION, chat_id: null }])
    expect(callsTo(fetch, '/api/ask')).toHaveLength(0)
  })

  it('asks the plain way when the stream cannot be used (e.g. a proxy page instead)', async () => {
    const fetch = fakeFetch(replies({
      '/api/ask/stream': { body: new Blob(['<html>Bad gateway</html>']), headers: { 'Content-Type': 'text/html' } },
      '/api/ask': { body: { chat: CHAT, card: CARD } },
    }))

    renderAt('/new', <AskPage me={ASHA} />)
    await ask()

    expect(await screen.findByText(CARD.answer)).toBeInTheDocument()
    expect(callsTo(fetch, '/api/ask/stream')).toHaveLength(1)
    expect(callsTo(fetch, '/api/ask')).toEqual([{ question: QUESTION, chat_id: null }])
  })

  it('asks the plain way when the stream ends before anything came', async () => {
    const live = liveStream()
    const fetch = fakeFetch(replies({ '/api/ask/stream': live.reply, '/api/ask': { body: { chat: CHAT, card: CARD } } }))

    renderAt('/new', <AskPage me={ASHA} />)
    await ask()
    live.end()

    expect(await screen.findByText(CARD.answer)).toBeInTheDocument()
    expect(callsTo(fetch, '/api/ask')).toHaveLength(1)
  })

  it('shows a refused question as it is and does not ask it again', async () => {
    const fetch = fakeFetch(replies({
      '/api/ask/stream': { status: 400, body: { detail: 'Please keep the question under 1000 characters.' } },
    }))

    renderAt('/new', <AskPage me={ASHA} />)
    await ask()

    expect(await screen.findByRole('alert')).toHaveTextContent('Please keep the question under 1000 characters.')
    expect(callsTo(fetch, '/api/ask')).toHaveLength(0)
    expect(screen.getByLabelText('Your question')).toHaveValue(QUESTION)               // what was typed is kept
  })

  it('shows the message of an error line and does not ask again', async () => {
    const live = liveStream()
    const fetch = fakeFetch(replies({ '/api/ask/stream': live.reply }))

    renderAt('/new', <AskPage me={ASHA} />)
    await ask()
    live.send({ type: 'step', label: 'Search the PDFs' })
    live.send({ type: 'error', message: 'Something went wrong while answering. Please try again.' })
    live.end()

    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong while answering.')
    expect(callsTo(fetch, '/api/ask')).toHaveLength(0)
  })
})
