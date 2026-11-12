// History: the usage box, the own questions with their columns and status, the pager, "Ask again"
// (it opens the Ask page and asks at once in a new chat) and the Excel link's friendly error.
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
    { ...LINE, id: 4, text: 'Weather?', understood_as: '', answer: 'Not a NOP data question.', rows_count: null,
      secs_text: '0.4', tokens_text: '-', status: 'refused', excel_url: '', ask_again: 'Weather?', edited: true,
      model: 'qwen/qwen3.8-27b', backup: true },
  ],
  page: 1, pages: 2, count: 27, has_previous: false, has_next: true, usage: USAGE,
}

describe('HistoryPage', () => {
  it('shows the usage box, my questions and the pager', async () => {
    fakeFetch({ '/api/history': { body: PAGE } })

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
    expect(screen.getByText('REFUSED')).toBeInTheDocument()
    expect(screen.getByText('edited - replaced by a newer version')).toBeInTheDocument()
    expect(screen.getByText('backup model')).toBeInTheDocument()
    expect(screen.getByText('4,517')).toHaveClass('num')
    expect(screen.getAllByRole('button', { name: 'Ask again' })).toHaveLength(2)
    expect(screen.getAllByRole('link', { name: 'Excel' })).toHaveLength(1)          // only the answered one
    expect(screen.getByText('Page 1 of 2 · 27 questions')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Older →' })).toHaveAttribute('href', '/history?page=2')
    expect(screen.queryByRole('link', { name: '← Newer' })).not.toBeInTheDocument()
  })

  it('says when there are no questions yet', async () => {
    fakeFetch({ '/api/history': { body: { ...PAGE, questions: [], pages: 1, count: 0, has_next: false,
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
      '/api/history': { body: PAGE },
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
      '/api/history': { body: PAGE },
      '/api/questions/5/excel': { status: 503, body: { detail: 'The Excel file could not be made: MySQL is not running' } },
    })

    renderAt('/history?tab=questions', <HistoryPage page={1} />)
    fireEvent.click(await screen.findByRole('link', { name: 'Excel' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('The Excel file could not be made: MySQL is not running')
  })
})
