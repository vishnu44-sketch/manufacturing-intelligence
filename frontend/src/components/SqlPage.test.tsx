// SQL (staff): the menu item and the page for staff only, the table tree from the schema (search, a click puts
// the name into the editor, the play icon runs SELECT * ... LIMIT 100), Run (button and Ctrl+Enter, only the
// selection when there is one) with the grid and the status line, the API's message in a red box, "first 500
// rows", Excel (a POST download), Recent, and the text kept over a reload. The CodeMirror editor is a plain
// text box here (SqlEditor.test.tsx tests the real one).
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, onTestFinished, vi } from 'vitest'
import App from '../App'
import { callsTo, fakeFetch } from '../test/fakeFetch'
import { ASHA, BOSS, renderAt } from '../test/render'
import type { SqlResult, SqlSchema } from '../types'
import SqlPage, { filterTables, numericColumns, withRecent } from './SqlPage'

vi.mock('./SqlEditor', async () => {
  const { useImperativeHandle, useRef } = await import('react')
  type Props = import('./SqlEditor').SqlEditorProps
  function FakeEditor({ initialText, onChange, onRun, ref }: Props) {
    const box = useRef<HTMLTextAreaElement>(null)
    const put = (text: string) => {
      box.current!.value = text
      onChange(text)
    }
    useImperativeHandle(ref, () => ({
      insert(text: string) {
        const el = box.current!
        put(el.value.slice(0, el.selectionStart) + text + el.value.slice(el.selectionEnd))
      },
      setText: put,
      runText() {
        const el = box.current!
        return el.selectionStart === el.selectionEnd ? el.value : el.value.slice(el.selectionStart, el.selectionEnd)
      },
      focus: () => box.current!.focus(),
    }), [])
    return (
      <textarea ref={box} aria-label="SQL editor" defaultValue={initialText} onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') onRun() }} />
    )
  }
  return { default: FakeEditor }
})

const SCHEMA: SqlSchema = {
  database: 'ai_gold',
  tables: [
    { name: 'dim_customers', rows: 5001, columns: [{ name: 'customer_id', type: 'int' }, { name: 'customer_name', type: 'varchar(200)' }] },
    { name: 'fact_invoice_lines', rows: 100720, columns: [{ name: 'invoice_no', type: 'varchar(30)' }, { name: 'net_amount', type: 'decimal(18,2)' }] },
  ],
}

const RESULT: SqlResult = {
  sql: 'SELECT customer_id, customer_name, credit FROM dim_customers',
  columns: ['customer_id', 'customer_name', 'credit'],
  rows: [[1, 'Asha Traders', '1250.50'], [2, 'Bala Mills', null]],
  row_count: 2, truncated: false, secs: 0.123,
}

afterEach(() => {
  window.sessionStorage.clear()
})

function page(replies: Parameters<typeof fakeFetch>[0] = {}) {
  const fetch = fakeFetch({ '/api/sql/schema': { body: SCHEMA }, ...replies })
  renderAt('/sql', <SqlPage />)
  return fetch
}

const textBox = () => screen.findByRole('textbox', { name: 'SQL editor' }) as Promise<HTMLTextAreaElement>
const tree = () => within(screen.getByRole('complementary', { name: 'Tables' }))

function type(box: HTMLTextAreaElement, text: string) {
  fireEvent.change(box, { target: { value: text } })
}

describe('SqlPage: the menu and the address', () => {
  it('staff see SQL under Administration and the page opens at /sql', async () => {
    fakeFetch({ '/api/me': { body: BOSS }, '/api/sql/schema': { body: SCHEMA } })
    window.history.pushState(null, '', '/sql')
    render(<App />)

    const link = await screen.findByRole('link', { name: 'SQL' })
    expect(link).toHaveAttribute('href', '/sql')
    expect(link).toHaveAttribute('aria-current', 'page')
    const admin = within(screen.getByRole('group', { name: 'Administration' })).getAllByRole('link').map((a) => a.textContent)
    expect(admin).toEqual(['Users', 'Documents', 'Data', 'SQL', 'Audit'])
    expect(await screen.findByText('dim_customers')).toBeInTheDocument()
    expect(document.title).toBe('SQL · Manufacturing Intelligence')
    expect(screen.getByText(/Read-only: SELECT queries on ai_gold, max 500 rows, 30 s limit\. Every query is in the Audit log\./))
      .toBeInTheDocument()
  })

  it('a normal user has no SQL item and /sql says "no access" without asking the API', async () => {
    const fetch = fakeFetch({ '/api/me': { body: ASHA } })
    window.history.pushState(null, '', '/sql')
    render(<App />)

    expect(await screen.findByText('You do not have access to this page')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'SQL' })).not.toBeInTheDocument()
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/me'])
  })

  it('says "no access" when the API answers 403', async () => {
    page({ '/api/sql/schema': { status: 403, body: { detail: 'Only administrators can open this page.' } } })
    expect(await screen.findByText('You do not have access to this page')).toBeInTheDocument()
  })
})

describe('SqlPage: the table tree', () => {
  it('shows the tables with their row counts, and the columns with their types when opened', async () => {
    page()
    expect(await screen.findByText('dim_customers')).toBeInTheDocument()
    expect(tree().getByText('ai_gold')).toBeInTheDocument()
    expect(tree().getByText('2 tables')).toBeInTheDocument()
    expect(tree().getByText('5,001')).toBeInTheDocument()
    expect(tree().getByText('100,720')).toBeInTheDocument()
    expect(tree().queryByText('customer_id')).not.toBeInTheDocument()

    fireEvent.click(tree().getByRole('button', { name: 'Show the columns of dim_customers' }))
    expect(tree().getByText('customer_id')).toBeInTheDocument()
    expect(tree().getByText('varchar(200)')).toBeInTheDocument()

    fireEvent.click(tree().getByRole('button', { name: 'Hide the columns of dim_customers' }))
    expect(tree().queryByText('customer_id')).not.toBeInTheDocument()
  })

  it('the search keeps the tables and columns that match', async () => {
    page()
    await screen.findByText('dim_customers')
    const find = tree().getByRole('textbox', { name: 'Find a table or column' })

    fireEvent.change(find, { target: { value: 'invoice' } })
    expect(tree().getByText('fact_invoice_lines')).toBeInTheDocument()
    expect(tree().queryByText('dim_customers')).not.toBeInTheDocument()

    fireEvent.change(find, { target: { value: 'NAME' } })                      // a column: its table opens with it
    expect(tree().getByText('dim_customers')).toBeInTheDocument()
    expect(tree().getByText('customer_name')).toBeInTheDocument()
    expect(tree().queryByText('customer_id')).not.toBeInTheDocument()
    expect(tree().queryByText('fact_invoice_lines')).not.toBeInTheDocument()

    fireEvent.change(find, { target: { value: 'nothing like it' } })
    expect(tree().getByText('Nothing matches.')).toBeInTheDocument()
  })

  it('a click on a table or a column puts its name into the editor at the cursor', async () => {
    page()
    const box = await textBox()
    type(box, 'SELECT  FROM ')
    box.setSelectionRange(7, 7)
    fireEvent.click(tree().getByRole('button', { name: 'Show the columns of dim_customers' }))
    fireEvent.click(tree().getByRole('button', { name: /^customer_id/ }))
    expect(box.value).toBe('SELECT customer_id FROM ')

    box.setSelectionRange(box.value.length, box.value.length)
    fireEvent.click(tree().getByRole('button', { name: 'dim_customers' }))
    expect(box.value).toBe('SELECT customer_id FROM dim_customers')
    expect(window.sessionStorage.getItem('mi.sqlText')).toBe('SELECT customer_id FROM dim_customers')
  })

  it('the play icon runs SELECT * ... LIMIT 100 of the table', async () => {
    const fetch = page({ '/api/sql': { body: { ...RESULT, sql: 'SELECT * FROM dim_customers LIMIT 100;' } } })
    const box = await textBox()
    fireEvent.click(tree().getByRole('button', { name: 'Run SELECT * FROM dim_customers LIMIT 100' }))
    expect(box.value).toBe('SELECT * FROM dim_customers LIMIT 100;')
    await waitFor(() => expect(callsTo(fetch, '/api/sql')).toEqual([{ sql: 'SELECT * FROM dim_customers LIMIT 100;' }]))
    expect(await screen.findByRole('table', { name: 'Query result' })).toBeInTheDocument()
  })

  it('shows the API message when the tables cannot be loaded', async () => {
    page({ '/api/sql/schema': { status: 503, body: { detail: 'The NOP data (MySQL) cannot be reached.' } } })
    expect(await screen.findByText('The NOP data (MySQL) cannot be reached.')).toHaveAttribute('role', 'alert')
    expect(await textBox()).toBeInTheDocument()                                    // the editor still works
  })
})

describe('SqlPage: running a query', () => {
  it('Run posts the SQL and shows the grid and the status line', async () => {
    const fetch = page({ '/api/sql': { body: RESULT } })
    type(await textBox(), '  SELECT customer_id, customer_name, credit FROM dim_customers \n')
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))

    const grid = await screen.findByRole('table', { name: 'Query result' })
    expect(callsTo(fetch, '/api/sql')).toEqual([{ sql: 'SELECT customer_id, customer_name, credit FROM dim_customers' }])
    expect(screen.getByText('2 rows · 0.12 s')).toBeInTheDocument()
    const cells = within(grid)
    expect(cells.getAllByRole('columnheader').map((th) => th.textContent)).toEqual(['#', 'customer_id', 'customer_name', 'credit'])
    expect(cells.getByText('Asha Traders')).not.toHaveClass('text-right')
    expect(cells.getByText('1250.50')).toHaveClass('text-right')                   // numbers are right-aligned
    expect(cells.getByRole('columnheader', { name: 'credit' })).toHaveClass('text-right')
    expect(cells.getByText('NULL')).toHaveClass('text-muted-foreground')          // NULL is muted
    expect(screen.getByRole('button', { name: 'Excel' })).toBeEnabled()
  })

  it('Ctrl+Enter runs, and only the selected text when there is a selection', async () => {
    const fetch = page({ '/api/sql': { body: RESULT } })
    const box = await textBox()
    type(box, 'SELECT 1;\nSELECT 2;')
    box.setSelectionRange(10, 19)
    fireEvent.keyDown(box, { key: 'Enter', ctrlKey: true })

    await waitFor(() => expect(callsTo(fetch, '/api/sql')).toEqual([{ sql: 'SELECT 2;' }]))
    expect(await screen.findByText('2 rows · 0.12 s')).toBeInTheDocument()
  })

  it('shows the API message of a refused query in a red box', async () => {
    page({ '/api/sql': { status: 400, body: { detail: 'Only SELECT queries can be run here.' } } })
    type(await textBox(), 'DELETE FROM dim_customers')
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))

    const message = await screen.findByText('Only SELECT queries can be run here.')
    expect(message).toHaveAttribute('role', 'alert')
    expect(message).toHaveClass('text-destructive')
    expect(screen.queryByRole('table', { name: 'Query result' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Excel' })).toBeDisabled()
  })

  it('an empty editor asks for a query and calls nothing', async () => {
    const fetch = page()
    await textBox()
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    expect(screen.getByText('Type a SELECT query first.')).toBeInTheDocument()
    expect(callsTo(fetch, '/api/sql')).toEqual([])
  })

  it('says "first 500 rows" when the answer was cut at the limit', async () => {
    const rows = Array.from({ length: 500 }, (_, i) => [i + 1, `Customer ${i + 1}`, null])
    page({ '/api/sql': { body: { ...RESULT, rows, row_count: 500, truncated: true, secs: 1.5 } } })
    type(await textBox(), 'SELECT * FROM dim_customers')
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    expect(await screen.findByText('first 500 rows · 1.50 s')).toBeInTheDocument()
  })

  it('Excel posts the query of the shown rows and saves the file', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    // jsdom has no object URLs: a stand-in for this test (taken away again at the end)
    const created = vi.fn(() => 'blob:sql')
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() })
    onTestFinished(() => {
      delete (URL as Partial<typeof URL>).createObjectURL
      delete (URL as Partial<typeof URL>).revokeObjectURL
    })
    const fetch = page({
      '/api/sql': { body: RESULT },
      // the file as bytes (jsdom's Blob cannot be the body of a Response)
      '/api/sql/excel': { body: new Response('xlsx').body, headers: { 'Content-Type': 'application/vnd.ms-excel', 'Content-Disposition': 'attachment; filename="sql_result.xlsx"' } },
    })
    type(await textBox(), RESULT.sql)
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    await screen.findByRole('table', { name: 'Query result' })

    fireEvent.click(screen.getByRole('button', { name: 'Excel' }))
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1))
    expect(callsTo(fetch, '/api/sql/excel')).toEqual([{ sql: RESULT.sql }])
    const [, init] = fetch.mock.calls.find(([url]) => url === '/api/sql/excel')!
    expect((init?.headers as Record<string, string>)['X-CSRFToken']).toBeDefined()
    expect(created).toHaveBeenCalledTimes(1)
    expect(click.mock.contexts[0]).toHaveProperty('download', 'sql_result.xlsx')
  })

  it('shows the API message when the Excel file cannot be made', async () => {
    page({ '/api/sql': { body: RESULT }, '/api/sql/excel': { status: 503, body: { detail: 'MySQL is not reachable now.' } } })
    type(await textBox(), RESULT.sql)
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    await screen.findByRole('table', { name: 'Query result' })
    fireEvent.click(screen.getByRole('button', { name: 'Excel' }))
    expect(await screen.findByText('MySQL is not reachable now.')).toHaveAttribute('role', 'alert')
    expect(screen.getByRole('table', { name: 'Query result' })).toBeInTheDocument()   // the rows stay
  })
})

describe('SqlPage: Recent and the kept text', () => {
  it('keeps the queries run, newest first; a click puts one back', async () => {
    page({ '/api/sql': { body: RESULT } })
    const box = await textBox()
    expect(screen.getByRole('button', { name: 'Recent' })).toBeDisabled()
    for (const sql of ['SELECT 1', 'SELECT 2']) {
      type(box, sql)
      fireEvent.click(screen.getByRole('button', { name: 'Run' }))
      await screen.findByText('2 rows · 0.12 s')
    }
    expect(JSON.parse(window.localStorage.getItem('mi.sqlRecent')!)).toEqual(['SELECT 2', 'SELECT 1'])

    fireEvent.click(screen.getByRole('button', { name: 'Recent' }))
    const list = within(await screen.findByRole('list', { name: 'Recent queries' }))
    fireEvent.click(list.getByRole('button', { name: 'SELECT 1' }))
    expect(box.value).toBe('SELECT 1')
  })

  it('starts with the text kept in this tab', async () => {
    window.sessionStorage.setItem('mi.sqlText', 'SELECT COUNT(*) FROM dim_customers')
    page()
    expect((await textBox()).value).toBe('SELECT COUNT(*) FROM dim_customers')
  })

  it('Clear empties the editor', async () => {
    page()
    const box = await textBox()
    type(box, 'SELECT 1')
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(box.value).toBe('')
    expect(window.sessionStorage.getItem('mi.sqlText')).toBeNull()
  })
})

describe('SqlPage: the small helpers', () => {
  it('withRecent puts the query on top once and keeps 10', () => {
    const ten = Array.from({ length: 10 }, (_, i) => `SELECT ${i}`)
    expect(withRecent(['a', 'b', 'c'], 'b')).toEqual(['b', 'a', 'c'])
    expect(withRecent(ten, 'new')).toHaveLength(10)
    expect(withRecent(ten, 'new')[0]).toBe('new')
  })

  it('filterTables and numericColumns', () => {
    expect(filterTables(SCHEMA.tables, '').map((s) => s.table.name)).toEqual(['dim_customers', 'fact_invoice_lines'])
    expect(filterTables(SCHEMA.tables, 'amount')).toEqual([{ table: SCHEMA.tables[1], columns: [SCHEMA.tables[1].columns[1]], byColumn: true }])
    expect(numericColumns(RESULT)).toEqual([true, false, true])
    expect(numericColumns({ ...RESULT, rows: [[null, null, null]] })).toEqual([false, false, false])
  })
})
