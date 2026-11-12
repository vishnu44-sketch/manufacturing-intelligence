// Audit log: the lines with their user, action in words, target, short details and IP; a click shows the
// details and the question links; the filters go into the address; paging; "no access" on a 403.
import { fireEvent, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { fakeFetch } from '../test/fakeFetch'
import { renderAt } from '../test/render'
import type { AuditData, AuditLine } from '../types'
import AuditPage from './AuditPage'

const LINE: AuditLine = {
  id: 7, created_at: '2026-11-03T10:15:07+05:30', created_text: '03 Nov 2026 10:15:07 AM', username: 'asha', user_id: 2,
  action: 'chat_deleted', action_text: 'Chat deleted', target: 'chat 12',
  details: { title: 'Sales Aug', questions: 2, question_ids: [31, 32] }, summary: 'title: Sales Aug; questions: 2; question ids: 31, 32',
  questions: [31, 32], ip: '127.0.0.1', user_agent: 'Firefox/140',
}
const MCP: AuditLine = {
  ...LINE, id: 6, username: '', user_id: null, action: 'mcp_run_sql', action_text: 'MCP: SQL run', target: 'mcp',
  details: { sql: 'SELECT 1', row_count: 1 }, summary: 'sql: SELECT 1; row count: 1', questions: [], ip: '',
}
const DATA: AuditData = {
  lines: [LINE, MCP], page: 1, pages: 1, count: 2, has_previous: false, has_next: false,
  actions: [{ code: 'login_ok', text: 'Signed in' }, { code: 'chat_deleted', text: 'Chat deleted' }],
  filters: { user: '', action: '', from: '', to: '', q: '' },
}
const NO_FILTERS = { user: '', action: '', from: '', to: '', q: '' }

describe('AuditPage', () => {
  it('shows each line with its user, action in words, target, details and IP', async () => {
    fakeFetch({ '/api/audit': { body: DATA } })

    renderAt('/audit', <AuditPage page={1} {...NO_FILTERS} />)

    const row = (await screen.findByText('Chat deleted', { selector: '.chip' })).closest('tr')!
    expect(within(row).getByText('03 Nov 2026 10:15:07 AM')).toBeInTheDocument()
    expect(within(row).getByText('asha')).toBeInTheDocument()
    expect(within(row).getByText('chat 12')).toBeInTheDocument()
    expect(within(row).getByText('title: Sales Aug; questions: 2; question ids: 31, 32')).toBeInTheDocument()
    expect(within(row).getByText('127.0.0.1')).toBeInTheDocument()
    expect(screen.getByText('MCP caller')).toBeInTheDocument()                     // an MCP call has no user
    expect(screen.getByText('2 lines - click a line for its details.')).toBeInTheDocument()
    expect(screen.queryByText('Firefox/140', { exact: false })).not.toBeInTheDocument()
  })

  it('opens the details of a line on a click, with links to its questions', async () => {
    fakeFetch({ '/api/audit': { body: DATA } })
    renderAt('/audit', <AuditPage page={1} {...NO_FILTERS} />)
    const row = (await screen.findByText('Chat deleted', { selector: '.chip' })).closest('tr')!

    fireEvent.click(row)

    expect(row).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: '#31' })).toHaveAttribute('href', '/q/31')
    expect(screen.getByRole('link', { name: '#32' })).toHaveAttribute('href', '/q/32')
    expect(screen.getByText(/"title": "Sales Aug"/)).toBeInTheDocument()
    expect(screen.getByText('Browser: Firefox/140')).toBeInTheDocument()

    fireEvent.click(row)
    expect(screen.queryByRole('link', { name: '#31' })).not.toBeInTheDocument()
  })

  it('sends the filters from the address and puts new ones into it', async () => {
    const fetch = fakeFetch({
      '/api/audit?user=asha&action=chat_deleted&from=2026-11-01&to=2026-11-03': { body: { ...DATA, lines: [LINE], count: 1 } },
      '/api/audit?action=login_ok&q=10.0.0.5': { body: { ...DATA, lines: [], count: 0 } },
    })

    renderAt('/audit?user=asha&action=chat_deleted&from=2026-11-01&to=2026-11-03',
      <AuditPage page={1} user="asha" action="chat_deleted" from="2026-11-01" to="2026-11-03" q="" />)

    expect(await screen.findByText('1 line matches the filters - click a line for its details.')).toBeInTheDocument()
    expect(screen.getByLabelText('User')).toHaveValue('asha')
    expect(screen.getByLabelText('Action')).toHaveValue('chat_deleted')
    expect(screen.getByLabelText('From')).toHaveValue('2026-11-01')
    expect(screen.getByRole('link', { name: 'Clear' })).toHaveAttribute('href', '/audit')

    fireEvent.change(screen.getByLabelText('User'), { target: { value: '  ' } })
    fireEvent.change(screen.getByLabelText('Action'), { target: { value: 'login_ok' } })
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Search'), { target: { value: ' 10.0.0.5 ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))

    expect(window.location.pathname + window.location.search).toBe('/audit?action=login_ok&q=10.0.0.5')
    expect(fetch.mock.calls[0][0]).toBe('/api/audit?user=asha&action=chat_deleted&from=2026-11-01&to=2026-11-03')
  })

  it('pages through the log, keeping the filters', async () => {
    fakeFetch({
      '/api/audit?page=2&action=login_ok': {
        body: { ...DATA, page: 2, pages: 3, count: 120, has_previous: true, has_next: true },
      },
    })

    renderAt('/audit?page=2&action=login_ok', <AuditPage page={2} {...NO_FILTERS} action="login_ok" />)

    expect(await screen.findByText('Page 2 of 3')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '← Newer' })).toHaveAttribute('href', '/audit?action=login_ok')
    expect(screen.getByRole('link', { name: 'Older →' })).toHaveAttribute('href', '/audit?action=login_ok&page=3')
  })

  it('says when nothing matches', async () => {
    fakeFetch({ '/api/audit?q=nobody': { body: { ...DATA, lines: [], count: 0 } } })

    renderAt('/audit?q=nobody', <AuditPage page={1} {...NO_FILTERS} q="nobody" />)

    expect(await screen.findByText('No audit lines match these filters.')).toBeInTheDocument()
  })

  it('says "no access" when the API answers 403', async () => {
    fakeFetch({ '/api/audit': { status: 403, body: { detail: 'Only administrators can open this page.' } } })

    renderAt('/audit', <AuditPage page={1} {...NO_FILTERS} />)

    expect(await screen.findByText('You do not have access to this page')).toBeInTheDocument()
  })
})
