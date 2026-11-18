// History: the usage box, the own questions with their columns and status, the pager, "Ask again"
// (it opens the Ask page and asks at once in a new chat) and the Excel link's friendly error.
// 18-Nov: the switch Assistant (first) | ML Insights | All - the server filters (?mode=), the page shows the counts.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from '../App'
import { callsTo, fakeFetch } from '../test/fakeFetch'
import { ASHA, renderAt } from '../test/render'
import type { HistoryPage as Page } from '../types'
import HistoryPage from './HistoryPage'

const USAGE = {
  rows: [
    { model: 'openai/gpt-oss-120b', tokens: '5,000', limit: '200,000', pct: 2, questions_left: 78, rolling: '5,000',
      week_tokens: '5,000', week_questions: 2 },
    { model: 'qwen/qwen3.8-27b', tokens: '0', limit: '200,000', pct: 0, questions_left: 80, rolling: '0',
      week_tokens: '0', week_questions: 0 },
  ],
  period_start: 'Thu 08-Oct 10:05 AM', period_end: 'Fri 09-Oct 10:05 AM',
  week_start: 'Sat 03-Oct 8:20 PM', week_end: 'Sat 10-Oct 8:20 PM',
}

const LINE = {
  id: 5, created_text: '03 Nov 2026 10:15 AM', text: 'and for Sep?', understood_as: 'Top 5 customers in Sep 2026',
  edited: false, answer: 'Aurora Fluid Power Limited had the highest invoice value.', rows_count: 5, secs_text: '1.5',
  tokens_text: '4,517', status: 'ok' as const, model: 'openai/gpt-oss-120b', backup: false,
  ask_again: 'Top 5 customers in Sep 2026', excel_url: '/api/questions/5/excel',
}

const PAGE: Page = {
  questions: [
    LINE,
    { ...LINE, id: 4, text: 'Weather?', understood_as: '', answer: 'Not an SS Manufacturing data question.', rows_count: null,
      secs_text: '0.4', tokens_text: '-', status: 'refused', excel_url: '', ask_again: 'Weather?', edited: true,
      model: 'qwen/qwen3.8-27b', backup: true },
    { ...LINE, id: 3, text: 'What is GST?', understood_as: '', answer: 'GST is the Goods and Services Tax of India.',
      rows_count: null, secs_text: '0.9', tokens_text: '612', status: 'general', excel_url: '', ask_again: 'What is GST?' },
  ],
  page: 1, pages: 2, count: 27, has_previous: false, has_next: true, usage: USAGE,
}

describe('HistoryPage', () => {
  it('shows the usage box, my questions and the pager', async () => {
    fakeFetch({ '/api/history?mode=assistant': { body: PAGE } })

    renderAt('/history?tab=questions', <HistoryPage page={1} />)

    expect(await screen.findByText('AI usage (this app)')).toBeInTheDocument()
    expect(screen.getByText(/Daily period since Thu 08-Oct 10:05 AM - it resets 24 hours/)).toBeInTheDocument()
    expect(screen.getByText('5,000 of 200,000 tokens (2 %)')).toBeInTheDocument()
    expect(screen.getByText('about 78 questions left - resets Fri 09-Oct 10:05 AM')).toBeInTheDocument()
    expect(screen.getByText(/rolling last 24 h, this app\): openai\/gpt-oss-120b 5,000 - qwen\/qwen3.8-27b 0/)).toBeInTheDocument()
    expect(screen.getByText(/This week \(since Sat 03-Oct 8:20 PM\): openai\/gpt-oss-120b 5,000 tokens, 2 questions/)).toBeInTheDocument()

    expect(screen.getByRole('link', { name: 'and for Sep?' })).toHaveAttribute('href', '/q/5')
    expect(screen.getByText('Understood as: Top 5 customers in Sep 2026')).toBeInTheDocument()
    expect(screen.getByText('ANSWERED')).toBeInTheDocument()
    expect(screen.getByText('REFUSED')).toHaveClass('chip', 'skip')
    expect(screen.getByText('GENERAL ANSWER')).toHaveClass('chip', 'info') // a question not about the company
    expect(screen.getByText('edited - replaced by a newer version')).toBeInTheDocument()
    expect(screen.getByText('backup model')).toBeInTheDocument()
    expect(screen.getByText('4,517')).toHaveClass('num')
    expect(screen.getAllByRole('button', { name: 'Ask again' })).toHaveLength(3)
    expect(screen.getAllByRole('link', { name: 'Excel' })).toHaveLength(1)          // only the answered one (not the general one)
    expect(screen.getByText('Page 1 of 2 · 27 questions')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Older →' })).toHaveAttribute('href', '/history?page=2')
    expect(screen.queryByRole('link', { name: '← Newer' })).not.toBeInTheDocument()
  })

  it('says when there are no questions yet', async () => {
    fakeFetch({ '/api/history?mode=assistant': { body: { ...PAGE, questions: [], pages: 1, count: 0, has_next: false,
                                          usage: { ...USAGE, period_start: '', period_end: '' } } } })

    renderAt('/history?tab=questions', <HistoryPage page={1} />)

    expect(await screen.findByText('No questions yet')).toBeInTheDocument()
    expect(screen.getByText('Daily period: starts with your next question.')).toBeInTheDocument()
  })

  it('asks a question again in a new chat on the Ask page', async () => {
    const card = {
      id: 9, text: 'Top 5 customers in Sep 2026', status: 'ok', answer: 'Aurora again.', understood_as: '',
      backup_model: '', token_notice: '', time_steps: [], sql: '', sources: [], secs: 1, tries: 1, row_count: 0,
      has_rows: false, rows_url: '', excel_url: '', created_at: '', created_text: '03 Nov 2026 10:20 AM', edited: false,
    }
    const chat = { id: 3, title: 'Top 5 customers in Sep 2026', archived: false, created_at: '', created_text: '',
                   updated_at: '', updated_text: '' }
    const fetch = fakeFetch({
      '/api/me': { body: ASHA },
      '/api/history?mode=assistant': { body: PAGE },
      '/api/chats': { body: { chats: [], removed: [] } },
      '/api/questions/5/again': { body: { chat, card } },
    })
    window.history.pushState(null, '', '/history?tab=questions')
    render(<App />)

    fireEvent.click((await screen.findAllByRole('button', { name: 'Ask again' }))[0])

    expect(await screen.findByText('Aurora again.')).toBeInTheDocument()
    expect(callsTo(fetch, '/api/questions/5/again')).toHaveLength(1)
    await waitFor(() => expect(window.location.pathname).toBe('/c/3'))
  })

  it('shows why an Excel file cannot be made', async () => {
    fakeFetch({
      '/api/history?mode=assistant': { body: PAGE },
      '/api/questions/5/excel': { status: 503, body: { detail: 'The Excel file could not be made: MySQL is not running' } },
    })

    renderAt('/history?tab=questions', <HistoryPage page={1} />)
    fireEvent.click(await screen.findByRole('link', { name: 'Excel' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('The Excel file could not be made: MySQL is not running')
  })
})

describe('HistoryPage Questions switch: Assistant | ML Insights | All (18-Nov)', () => {
  const COUNTS = { assistant: 27, ml: 1, all: 28 }
  const ML_LINE = { ...LINE, id: 8, text: 'Sales forecast for 3 months?', understood_as: '', mode: 'ml' as const }
  const ASSISTANT = { ...PAGE, counts: COUNTS, questions: PAGE.questions.map((line) => ({ ...line, mode: '' as const })) }
  const ML = { ...PAGE, counts: COUNTS, questions: [ML_LINE], pages: 1, count: 1, has_next: false }
  const ALL = { ...ASSISTANT, questions: [ML_LINE, ...ASSISTANT.questions], count: 28 }
  const BADGE = 'Asked in a chat of ML Insights'
  const replies = () => ({
    '/api/history?mode=assistant': { body: ASSISTANT }, '/api/history?mode=ml': { body: ML }, '/api/history': { body: ALL },
  })

  it('opens on the Assistant with the counts, and each choice asks the server for its questions', async () => {
    const fetch = fakeFetch(replies())
    renderAt('/history?tab=questions', <HistoryPage page={1} />)

    expect(await screen.findByRole('link', { name: 'and for Sep?' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Which questions to show' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Assistant (27)' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'ML Insights (1)' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'All (28)' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.queryByRole('link', { name: 'Sales forecast for 3 months?' })).not.toBeInTheDocument()
    expect(screen.queryByTitle(BADGE)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'ML Insights (1)' }))
    const ml = await screen.findByRole('link', { name: 'Sales forecast for 3 months?' })
    expect(ml).toHaveAttribute('href', '/q/8')                                    // opens as before
    expect(screen.getByTitle(BADGE)).toHaveTextContent('ML Insights question')
    expect(screen.queryByRole('link', { name: 'and for Sep?' })).not.toBeInTheDocument()
    expect(window.localStorage.getItem('mi.historyMode')).toBe('ml')

    fireEvent.click(screen.getByRole('button', { name: 'All (28)' }))
    expect(await screen.findByRole('link', { name: 'and for Sep?' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sales forecast for 3 months?' })).toBeInTheDocument()
    expect(screen.getAllByTitle(BADGE)).toHaveLength(1)                            // only the ML question has the badge
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/history?mode=assistant', '/api/history?mode=ml', '/api/history'])
  })

  it('opens on the last choice of this browser (the Chats tab shares it)', async () => {
    window.localStorage.setItem('mi.historyMode', 'ml')
    const fetch = fakeFetch(replies())
    renderAt('/history?tab=questions', <HistoryPage page={1} />)

    expect(await screen.findByRole('link', { name: 'Sales forecast for 3 months?' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ML Insights (1)' })).toHaveAttribute('aria-pressed', 'true')
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/history?mode=ml'])
  })

  it('another choice on page 2 goes back to page 1', async () => {
    fakeFetch({ ...replies(), '/api/history?page=2&mode=assistant': { body: { ...ASSISTANT, page: 2 } } })
    renderAt('/history?page=2', <HistoryPage page={2} />)

    fireEvent.click(await screen.findByRole('button', { name: 'ML Insights (1)' }))
    expect(window.location.pathname + window.location.search).toBe('/history?tab=questions')
  })

  it('asks an ML question again as before', async () => {
    const fetch = fakeFetch({
      '/api/me': { body: ASHA }, '/api/history?mode=ml': { body: ML }, '/api/chats': { body: { chats: [], removed: [] } },
    })
    window.localStorage.setItem('mi.historyMode', 'ml')
    window.history.pushState(null, '', '/history?tab=questions')
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: 'Ask again' }))
    await waitFor(() => expect(callsTo(fetch, '/api/questions/8/again')).toHaveLength(1))
  })

  it('says so when one side has no questions', async () => {
    fakeFetch({ '/api/history?mode=ml': { body: { ...ML, questions: [], count: 0, counts: { assistant: 3, ml: 0, all: 3 } } } })
    window.localStorage.setItem('mi.historyMode', 'ml')
    renderAt('/history?tab=questions', <HistoryPage page={1} />)

    expect(await screen.findByText('No ML Insights questions yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go to ML Insights' })).toHaveAttribute('href', '/insights')
  })
})
