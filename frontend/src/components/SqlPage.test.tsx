// SQL (staff): the menu item and the page for staff only, the table tree from the schema (search, a click puts
// the name into the editor, the play icon runs SELECT * ... LIMIT 100), Run (button and Ctrl+Enter, only the
// selection when there is one) with the grid and the status line, the API's message in a red box, "first 500
// rows", Excel (a POST download), Recent; the editor tabs (each with its own text and result, kept over a
// reload), saving (Save / Ctrl+S / Save as, someone else's query), the saved queries list and its "..." menu,
// and .sql files. The CodeMirror editor is a plain text box here (SqlEditor.test.tsx tests the real one); a
// hidden tab's text box is not found by role, so textBox() is always the shown tab's.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, onTestFinished, vi } from 'vitest'
import App from '../App'
import { callsTo, fakeFetch } from '../test/fakeFetch'
import { ASHA, BOSS, renderAt } from '../test/render'
import type { SqlResult, SqlSavedQuery, SqlSchema } from '../types'
import SqlPage, { filterTables, numericColumns, withRecent } from './SqlPage'
import { filterSaved } from './SqlSaved'
import { nextTitle, readTabs, sqlFileName } from './sqlTabModel'

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

const SAVED_AT = { updated_at: '2026-11-16T09:00:00Z', updated_text: '2 hours ago', owner: 'boss', owner_name: 'Boss', mine: true }
const MINE: SqlSavedQuery = { id: 7, name: 'Open orders', sql: 'SELECT * FROM fact_orders', shared: false, ...SAVED_AT }
const MINE_SHARED: SqlSavedQuery = { id: 8, name: 'Top customers', sql: 'SELECT customer_name FROM dim_customers', shared: true, ...SAVED_AT }
const THEIRS: SqlSavedQuery = {
  ...SAVED_AT, id: 9, name: 'Late invoices', sql: 'SELECT invoice_no FROM fact_invoice_lines', shared: true,
  owner: 'ravi', owner_name: 'Ravi Kumar', mine: false,
}
const LIST = { mine: [MINE, MINE_SHARED], shared: [THEIRS] }

afterEach(() => {
  window.sessionStorage.clear()
})

function page(replies: Parameters<typeof fakeFetch>[0] = {}) {
  const fetch = fakeFetch({ '/api/sql/schema': { body: SCHEMA }, '/api/sql/saved': { body: { mine: [], shared: [] } }, ...replies })
  renderAt('/sql', <SqlPage />)
  return fetch
}

/** The saved list (GET) and the replies to a new saved query (POST: its id 21, or `made`). */
function savedReplies(made: Partial<SqlSavedQuery> = {}): Parameters<typeof fakeFetch>[0] {
  return {
    '/api/sql/saved': (init) => (init?.method === 'POST'
      ? { status: 201, body: { query: { ...MINE, id: 21, shared: false, ...JSON.parse(String(init.body)), ...made } } }
      : { body: LIST }),
  }
}

/** The replies to the changes of one saved query: each time the query with all the fields sent so far. */
function changed(query: SqlSavedQuery) {
  let now = query
  return (init?: RequestInit) => {
    now = { ...now, ...JSON.parse(String(init?.body)) }
    return { body: { query: now } }
  }
}

const textBox = () => screen.findByRole('textbox', { name: 'SQL editor' }) as Promise<HTMLTextAreaElement>
const tree = () => within(screen.getByRole('region', { name: 'Tables' }))
const savedPanel = () => within(screen.getByRole('region', { name: 'Saved queries' }))
// hidden: true - an open dialog hides the page from the role queries
const tabNames = () => screen.getAllByRole('tab', { hidden: true }).map((tab) => tab.textContent)
const keptTabs = () => JSON.parse(window.localStorage.getItem('mi.sqlTabs')!) as { tabs: { title: string; text: string; savedId: number | null }[] }

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
    expect(keptTabs().tabs[0].text).toBe('SELECT customer_id FROM dim_customers')   // the tab is kept in this browser
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

  it('the old single editor text becomes the first tab (once)', async () => {
    window.sessionStorage.setItem('mi.sqlText', 'SELECT COUNT(*) FROM dim_customers')
    page()
    expect((await textBox()).value).toBe('SELECT COUNT(*) FROM dim_customers')
    expect(tabNames()).toEqual(['Query 1● (unsaved changes)'])                         // not saved yet
    expect(window.sessionStorage.getItem('mi.sqlText')).toBeNull()                    // moved, not copied
    expect(keptTabs().tabs.map((t) => t.text)).toEqual(['SELECT COUNT(*) FROM dim_customers'])
  })

  it('Clear empties the editor', async () => {
    page()
    const box = await textBox()
    type(box, 'SELECT 1')
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(box.value).toBe('')
    expect(keptTabs().tabs[0].text).toBe('')
  })
})

describe('SqlPage: the editor tabs', () => {
  it('"+" opens Query 2; each tab keeps its own text and its own result', async () => {
    const fetch = page({
      '/api/sql': (init) => (JSON.parse(String(init?.body)).sql === 'SELECT 1'
        ? { body: RESULT }
        : { body: { ...RESULT, rows: [[3, 'Chola Steel', null]], row_count: 1 } }),
    })
    expect(await textBox()).toBeInTheDocument()
    expect(tabNames()).toEqual(['Query 1'])
    type(await textBox(), 'SELECT 1')
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    expect(await screen.findByText('2 rows · 0.12 s')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'New tab' }))
    expect(screen.getByRole('tab', { name: 'Query 2' })).toHaveAttribute('aria-selected', 'true')
    expect((await textBox()).value).toBe('')
    expect(screen.queryByRole('table', { name: 'Query result' })).not.toBeInTheDocument()   // its own (empty) result
    type(await textBox(), 'SELECT 2')
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    expect(await screen.findByText('1 row · 0.12 s')).toBeInTheDocument()
    expect(screen.getByText('Chola Steel')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: /^Query 1/ }))
    expect((await textBox()).value).toBe('SELECT 1')
    expect(screen.getByText('2 rows · 0.12 s')).toBeInTheDocument()
    expect(screen.getByText('Asha Traders')).toBeInTheDocument()
    expect(callsTo(fetch, '/api/sql')).toEqual([{ sql: 'SELECT 1' }, { sql: 'SELECT 2' }])

    // Ctrl+Enter runs the shown tab
    type(await textBox(), 'SELECT 2')
    fireEvent.keyDown(await textBox(), { key: 'Enter', ctrlKey: true })
    expect(await screen.findByText('1 row · 0.12 s')).toBeInTheDocument()
  })

  it('a tab with unsaved changes asks "Close without saving?"; an empty one closes at once', async () => {
    page()
    type(await textBox(), 'SELECT 1')
    expect(screen.getByRole('tab', { name: 'Query 1 (unsaved changes)' })).toHaveTextContent('●')
    fireEvent.click(screen.getByRole('button', { name: 'New tab' }))
    fireEvent.click(screen.getByRole('button', { name: 'Close Query 2' }))           // empty: no question
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(tabNames()).toEqual(['Query 1● (unsaved changes)'])

    fireEvent.click(screen.getByRole('button', { name: 'Close Query 1' }))
    let dialog = within(await screen.findByRole('alertdialog', { name: 'Close without saving?' }))
    fireEvent.click(dialog.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect((await textBox()).value).toBe('SELECT 1')

    fireEvent.click(screen.getByRole('button', { name: 'Close Query 1' }))
    dialog = within(await screen.findByRole('alertdialog', { name: 'Close without saving?' }))
    fireEvent.click(dialog.getByRole('button', { name: 'Close without saving' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(tabNames()).toEqual(['Query 1'])                                               // the last tab: a fresh one
    expect((await textBox()).value).toBe('')
  })

  it('a reload brings the open tabs back (text, title, saved query - not the results)', async () => {
    page({ ...savedReplies(), '/api/sql': { body: RESULT } })
    type(await textBox(), 'SELECT 1')
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    await screen.findByText('2 rows · 0.12 s')
    fireEvent.click(await savedPanel().findByRole('button', { name: /^Late invoices/ }))
    expect(tabNames()).toEqual(['Query 1● (unsaved changes)', 'Late invoices'])

    cleanup()                                                                             // the page is loaded again
    renderAt('/sql', <SqlPage />)
    expect((await textBox()).value).toBe(THEIRS.sql)
    expect(tabNames()).toEqual(['Query 1● (unsaved changes)', 'Late invoices'])
    expect(screen.getByRole('tab', { name: 'Late invoices' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()                 // still someone else's
    fireEvent.click(screen.getByRole('tab', { name: /^Query 1/ }))
    expect((await textBox()).value).toBe('SELECT 1')
    expect(screen.queryByRole('table', { name: 'Query result' })).not.toBeInTheDocument()
  })
})

describe('SqlPage: saving', () => {
  it('the first Save of a new tab asks a name and posts; after that Save updates the saved query', async () => {
    const fetch = page({ ...savedReplies(), '/api/sql/saved/21': changed({ ...MINE, id: 21, name: 'My orders', sql: 'SELECT 1', shared: true }) })
    type(await textBox(), 'SELECT 1')
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    const dialog = within(await screen.findByRole('alertdialog', { name: 'Save query' }))
    const name = dialog.getByRole('textbox', { name: 'Name of the query' })
    expect(name).toHaveValue('Query 1')
    fireEvent.change(name, { target: { value: 'My orders' } })
    const share = dialog.getByRole('switch', { name: 'Share with all admins' })
    expect(share).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(share)
    fireEvent.click(dialog.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(callsTo(fetch, '/api/sql/saved')).toEqual([{ name: 'My orders', sql: 'SELECT 1', shared: true }])
    expect(tabNames()).toEqual(['My orders'])                                             // no dot: saved
    expect(within(savedPanel().getByRole('list', { name: 'My queries' })).getByText('My orders')).toBeInTheDocument()

    type(await textBox(), 'SELECT 1 LIMIT 5')
    expect(tabNames()).toEqual(['My orders● (unsaved changes)'])
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(callsTo(fetch, '/api/sql/saved/21')).toEqual([{ sql: 'SELECT 1 LIMIT 5' }]))
    await waitFor(() => expect(tabNames()).toEqual(['My orders']))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()                    // no name asked again
    expect(callsTo(fetch, '/api/sql/saved')).toHaveLength(1)
  })

  it('Ctrl+S saves and does not reach the browser; on a new tab it asks the name', async () => {
    const fetch = page({ ...savedReplies(), '/api/sql/saved/7': changed(MINE) })
    fireEvent.click(await savedPanel().findByRole('button', { name: /^Open orders/ }))
    const box = await textBox()
    expect(box.value).toBe(MINE.sql)
    type(box, 'SELECT * FROM fact_orders LIMIT 9')

    expect(fireEvent.keyDown(box, { key: 's', ctrlKey: true })).toBe(false)              // the browser's own save is stopped
    await waitFor(() => expect(callsTo(fetch, '/api/sql/saved/7')).toEqual([{ sql: 'SELECT * FROM fact_orders LIMIT 9' }]))
    await waitFor(() => expect(tabNames()).toEqual(['Open orders']))

    fireEvent.click(screen.getByRole('button', { name: 'New tab' }))
    expect(fireEvent.keyDown(await textBox(), { key: 'S', metaKey: true })).toBe(false)
    expect(await screen.findByRole('alertdialog', { name: 'Save query' })).toBeInTheDocument()
  })

  it('Save as always asks a name and makes a new saved query; the tab then points to it', async () => {
    const fetch = page({ ...savedReplies({ id: 30 }), '/api/sql/saved/30': changed({ ...MINE, id: 30, name: 'Open orders (copy)' }) })
    fireEvent.click(await savedPanel().findByRole('button', { name: /^Open orders/ }))
    await textBox()
    fireEvent.click(screen.getByRole('button', { name: 'Save as…' }))

    const dialog = within(await screen.findByRole('alertdialog', { name: 'Save as' }))
    expect(dialog.getByRole('textbox', { name: 'Name of the query' })).toHaveValue('Open orders (copy)')
    fireEvent.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(callsTo(fetch, '/api/sql/saved')).toEqual([{ name: 'Open orders (copy)', sql: MINE.sql, shared: false }]))
    await waitFor(() => expect(tabNames()).toEqual(['Open orders (copy)']))

    type(await textBox(), 'SELECT 2')
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(callsTo(fetch, '/api/sql/saved/30')).toEqual([{ sql: 'SELECT 2' }]))
    expect(callsTo(fetch, '/api/sql/saved/7')).toEqual([])                                 // the first one is not changed
  })

  it("someone else's shared query: Save is off with the owner's note, Save as works", async () => {
    const fetch = page(savedReplies())
    fireEvent.click(await savedPanel().findByRole('button', { name: /^Late invoices/ }))
    type(await textBox(), 'SELECT 1')
    const note = 'Only Ravi Kumar can change this query - use Save as to keep your own copy'
    const save = screen.getByRole('button', { name: 'Save' })
    expect(save).toBeDisabled()
    expect(save).toHaveAttribute('title', note)

    expect(fireEvent.keyDown(await textBox(), { key: 's', ctrlKey: true })).toBe(false)
    expect(await screen.findByText(note)).toBeInTheDocument()                             // a toast says why
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Save as…' }))
    const dialog = within(await screen.findByRole('alertdialog', { name: 'Save as' }))
    fireEvent.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(callsTo(fetch, '/api/sql/saved')).toEqual([{ name: 'Late invoices (copy)', sql: 'SELECT 1', shared: false }]))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled())   // now my own copy
  })

  it("shows the API's message in the dialog (a name taken) and keeps it open", async () => {
    page({ '/api/sql/saved': (init) => (init?.method === 'POST'
      ? { status: 400, body: { detail: 'You already have a saved query called "Open orders".' } }
      : { body: LIST }) })
    type(await textBox(), 'SELECT 1')
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    const dialog = within(await screen.findByRole('alertdialog', { name: 'Save query' }))
    fireEvent.change(dialog.getByRole('textbox', { name: 'Name of the query' }), { target: { value: 'Open orders' } })
    fireEvent.click(dialog.getByRole('button', { name: 'Save' }))
    expect(await dialog.findByText('You already have a saved query called "Open orders".')).toHaveAttribute('role', 'alert')
    expect(screen.getByRole('alertdialog', { name: 'Save query' })).toBeInTheDocument()
    expect(tabNames()).toEqual(['Query 1● (unsaved changes)'])
  })
})

describe('SqlPage: the saved queries list', () => {
  it('shows my queries (private / shared) and the ones others shared, with the owner; the search filters', async () => {
    page(savedReplies())
    const mine = within(await savedPanel().findByRole('list', { name: 'My queries' }))
    expect(mine.getAllByRole('listitem').map((li) => li.textContent))
      .toEqual(['Open orders (private)', 'Top customers (shared with all admins)'])     // a lock / a globe icon
    expect(mine.getByRole('button', { name: 'Open orders (private)' })).toHaveAttribute('title', 'Open orders\nChanged 2 hours ago')
    const theirs = within(savedPanel().getByRole('list', { name: 'Shared by others' }))
    expect(theirs.getByText('Late invoices')).toBeInTheDocument()
    expect(theirs.getByText('Ravi Kumar')).toBeInTheDocument()
    expect(theirs.getByRole('button', { name: /^Late invoices/ })).toHaveAttribute('title', 'Late invoices\nChanged 2 hours ago · by Ravi Kumar')

    const find = savedPanel().getByRole('textbox', { name: 'Find a saved query' })
    fireEvent.change(find, { target: { value: 'TOP' } })
    expect(mine.queryByText('Open orders')).not.toBeInTheDocument()
    expect(mine.getByText('Top customers')).toBeInTheDocument()
    expect(theirs.getByText('Nothing matches.')).toBeInTheDocument()
    fireEvent.change(find, { target: { value: 'ravi' } })                                // the owner's name
    expect(theirs.getByText('Late invoices')).toBeInTheDocument()
  })

  it('a click opens a query in a tab (the empty tab first), or shows the tab that has it', async () => {
    page(savedReplies())
    fireEvent.click(await savedPanel().findByRole('button', { name: /^Open orders/ }))
    expect(tabNames()).toEqual(['Open orders'])                                           // the empty "Query 1" was used
    expect((await textBox()).value).toBe(MINE.sql)

    fireEvent.click(savedPanel().getByRole('button', { name: /^Top customers/ }))
    expect(tabNames()).toEqual(['Open orders', 'Top customers'])
    expect((await textBox()).value).toBe(MINE_SHARED.sql)

    type(await textBox(), 'SELECT 3')
    fireEvent.click(savedPanel().getByRole('button', { name: /^Open orders/ }))
    expect(tabNames()).toEqual(['Open orders', 'Top customers● (unsaved changes)'])     // no second tab
    expect(screen.getByRole('tab', { name: 'Open orders' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(savedPanel().getByRole('button', { name: /^Top customers/ }))
    expect((await textBox()).value).toBe('SELECT 3')                                     // the changes are still there
  })

  it('rename, duplicate, the share switch and delete (asked first) call the API', async () => {
    const fetch = page({
      ...savedReplies({ id: 40 }),
      '/api/sql/saved/7': changed(MINE),
      '/api/sql/saved/7/delete': { body: { deleted: 7 } },
    })
    fireEvent.click(await savedPanel().findByRole('button', { name: /^Open orders/ }))    // open in a tab too
    const menu = async (name: string) => {
      fireEvent.click(savedPanel().getByRole('button', { name: `More for ${name}` }))
      return within(await screen.findByRole('dialog'))
    }

    let items = await menu('Open orders')
    fireEvent.change(items.getByRole('textbox', { name: 'New name for Open orders' }), { target: { value: 'Open orders 2026' } })
    fireEvent.click(items.getByRole('button', { name: 'Rename' }))
    await waitFor(() => expect(callsTo(fetch, '/api/sql/saved/7')).toEqual([{ name: 'Open orders 2026' }]))
    expect(await savedPanel().findByRole('button', { name: 'Open orders 2026 (private)' })).toBeInTheDocument()
    expect(tabNames()).toEqual(['Open orders 2026'])                                      // the open tab follows
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    items = await menu('Open orders 2026')
    fireEvent.click(items.getByRole('switch', { name: 'Share with all admins' }))
    await waitFor(() => expect(callsTo(fetch, '/api/sql/saved/7')).toEqual([{ name: 'Open orders 2026' }, { shared: true }]))
    await waitFor(() => expect(items.getByRole('switch', { name: 'Share with all admins' })).toHaveAttribute('aria-checked', 'true'))

    fireEvent.click(items.getByRole('button', { name: 'Duplicate' }))
    await waitFor(() => expect(callsTo(fetch, '/api/sql/saved')).toEqual([{ name: 'Open orders 2026 (copy)', sql: MINE.sql, shared: false }]))
    expect(await screen.findByText('Saved a copy: "Open orders 2026 (copy)".')).toBeInTheDocument()

    items = await menu('Open orders 2026')
    fireEvent.click(items.getByRole('button', { name: 'Delete' }))
    const dialog = within(await screen.findByRole('alertdialog', { name: 'Delete Open orders 2026?' }))
    fireEvent.click(dialog.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(callsTo(fetch, '/api/sql/saved/7/delete')).toEqual([{}]))
    await waitFor(() => expect(savedPanel().queryByRole('button', { name: 'More for Open orders 2026' })).not.toBeInTheDocument())
    expect(savedPanel().getByRole('button', { name: 'More for Open orders 2026 (copy)' })).toBeInTheDocument()
    expect(tabNames()).toEqual(['Open orders 2026● (unsaved changes)'])                   // its text is not saved any more
  })

  it("someone else's query has only Open and Duplicate; a refused change shows the API's message", async () => {
    page({ ...savedReplies(), '/api/sql/saved/7': { status: 400, body: { detail: 'The name can be at most 200 characters.' } } })
    fireEvent.click(await savedPanel().findByRole('button', { name: 'More for Late invoices' }))
    let items = within(await screen.findByRole('dialog'))
    expect(items.getAllByRole('button').map((b) => b.textContent?.trim())).toEqual(['Open', 'Duplicate'])
    expect(items.queryByRole('switch')).not.toBeInTheDocument()
    fireEvent.click(items.getByRole('button', { name: 'Open' }))
    expect(await screen.findByRole('tab', { name: 'Late invoices' })).toBeInTheDocument()

    fireEvent.click(savedPanel().getByRole('button', { name: 'More for Open orders' }))
    items = within(await screen.findByRole('dialog'))
    fireEvent.change(items.getByRole('textbox', { name: 'New name for Open orders' }), { target: { value: 'x'.repeat(20) } })
    fireEvent.click(items.getByRole('button', { name: 'Rename' }))
    expect(await items.findByText('The name can be at most 200 characters.')).toHaveAttribute('role', 'alert')
    fireEvent.click(items.getByRole('switch', { name: 'Share with all admins' }))
    await waitFor(() => expect(screen.getAllByText('The name can be at most 200 characters.')).toHaveLength(2))   // and a toast
  })

  it("shows the API's message when the list cannot be loaded (the tables still work)", async () => {
    page({ '/api/sql/saved': { status: 503, body: { detail: 'The database cannot be reached.' } } })
    expect(await savedPanel().findByText('The database cannot be reached.')).toHaveAttribute('role', 'alert')
    expect(await tree().findByText('dim_customers')).toBeInTheDocument()
  })
})

describe('SqlPage: .sql files', () => {
  it('Open .sql file opens it in a new tab titled by the file name, not saved', async () => {
    page()
    type(await textBox(), 'SELECT 1')
    const file = new File(['SELECT 42 FROM dim_customers;'], 'monthly report.sql', { type: 'application/sql' })
    fireEvent.change(screen.getByTestId('sql-file'), { target: { files: [file] } })
    await waitFor(() => expect(tabNames()).toEqual(['Query 1● (unsaved changes)', 'monthly report● (unsaved changes)']))
    expect((await textBox()).value).toBe('SELECT 42 FROM dim_customers;')

    const big = new File(['x'.repeat(201 * 1024)], 'huge.sql')
    fireEvent.change(screen.getByTestId('sql-file'), { target: { files: [big] } })
    expect(await screen.findByText('huge.sql is too big - a .sql file can be at most 200 KB.')).toBeInTheDocument()
    expect(screen.getAllByRole('tab')).toHaveLength(2)
  })

  it("Download .sql gives the shown tab's text as <title>.sql", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const blobs: Blob[] = []
    Object.assign(URL, { createObjectURL: vi.fn((blob: Blob) => { blobs.push(blob); return 'blob:sql' }), revokeObjectURL: vi.fn() })
    onTestFinished(() => {
      delete (URL as Partial<typeof URL>).createObjectURL
      delete (URL as Partial<typeof URL>).revokeObjectURL
    })
    page()
    await textBox()
    expect(screen.getByRole('button', { name: 'Download .sql' })).toBeDisabled()         // nothing to download yet
    type(await textBox(), 'SELECT 1;\n')
    fireEvent.click(screen.getByRole('button', { name: 'Download .sql' }))
    expect(click).toHaveBeenCalledTimes(1)
    expect(click.mock.contexts[0]).toHaveProperty('download', 'Query 1.sql')
    expect(await blobs[0].text()).toBe('SELECT 1;\n')
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

  it('filterSaved, nextTitle, sqlFileName and a broken kept value', () => {
    expect(filterSaved([MINE_SHARED, MINE, THEIRS], '').map((q) => q.name)).toEqual(['Late invoices', 'Open orders', 'Top customers'])
    expect(filterSaved([MINE, THEIRS], 'kumar').map((q) => q.name)).toEqual(['Late invoices'])
    expect(filterSaved([MINE], 'boss')).toEqual([])                                        // my own: by name only
    const tab = (title: string) => ({ id: title, title, text: '', base: '', savedId: null, mine: true, ownerName: '' })
    expect(nextTitle([tab('Query 1'), tab('Query 3')])).toBe('Query 2')
    expect(sqlFileName('Sales: Q3/Q4?')).toBe('Sales_ Q3_Q4_.sql')
    expect(sqlFileName('report.sql')).toBe('report.sql')
    expect(sqlFileName('  ')).toBe('query.sql')
    window.localStorage.setItem('mi.sqlTabs', '{broken')
    expect(readTabs().tabs.map((t) => t.title)).toEqual(['Query 1'])
  })
})
