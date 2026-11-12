// Data: the records of every table with its kind, the total and the dates; MySQL down; no access.
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { fakeFetch } from '../test/fakeFetch'
import { renderAt } from '../test/render'
import type { DataTables } from '../types'
import DataPage from './DataPage'

const DATA: DataTables = {
  database: 'ai_gold', mysql_error: '', table_count: 3, total: '206,000',
  invoices_from: '21 Dec 2025', invoices_to: '20 Mar 2027', last_load: '06 Oct 2026 07:10 PM',
  tables: [
    { name: 'fact_invoice_lines', note: 'Invoice lines and credit / debit note lines (sales)', kind: 'Main data', rows: 100720, rows_text: '100,720' },
    { name: 'fact_new_table', note: '', kind: 'Main data', rows: 105262, rows_text: '105,262' },
    { name: 'load_log', note: 'Load history: one row per table for each data load', kind: 'Load history', rows: 18, rows_text: '18' },
  ],
}

describe('DataPage', () => {
  it('shows the records of every table, the total and the dates', async () => {
    fakeFetch({ '/api/data': { body: DATA } })

    renderAt('/data', <DataPage />)

    expect(await screen.findByText('206,000 records in 3 tables')).toBeInTheDocument()
    expect(screen.getByText('Invoices: 21 Dec 2025 to 20 Mar 2027')).toBeInTheDocument()
    expect(screen.getByText('Last data load: 06 Oct 2026 07:10 PM')).toBeInTheDocument()
    expect(screen.getByText('fact_invoice_lines').tagName).toBe('CODE')
    expect(screen.getByText('100,720')).toHaveClass('num')
    expect(screen.getAllByText('MAIN DATA')).toHaveLength(2)
    expect(screen.getByText('LOAD HISTORY')).toBeInTheDocument()
    expect(screen.getByText('-')).toBeInTheDocument()                                // a table without a note
    expect(screen.getByText('Total')).toBeInTheDocument()
    expect(screen.getByText(/MySQL ai_gold/)).toBeInTheDocument()
  })

  it('says clearly when MySQL cannot be read', async () => {
    fakeFetch({ '/api/data': { body: { ...DATA, tables: [], table_count: 0, mysql_error: 'Cannot connect: (2003) refused' } } })

    renderAt('/data', <DataPage />)

    expect(await screen.findByText('The NOP data (MySQL) cannot be read right now: Cannot connect: (2003) refused')).toHaveClass('errbox')
    expect(screen.queryByText(/records in/)).not.toBeInTheDocument()
  })

  it('says "no access" when the API answers 403', async () => {
    fakeFetch({ '/api/data': { status: 403, body: { detail: 'Only administrators can open this page.' } } })

    renderAt('/data', <DataPage />)

    expect(await screen.findByText('You do not have access to this page')).toBeInTheDocument()
  })
})
