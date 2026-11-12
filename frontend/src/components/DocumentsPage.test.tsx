// Documents: the file counts, every piece, the test search with its scores and tables line, the
// filter going into the address, the empty / down store messages, and "no access" on a 403.
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { fakeFetch } from '../test/fakeFetch'
import { renderAt } from '../test/render'
import type { DocumentsData } from '../types'
import DocumentsPage from './DocumentsPage'

const DATA: DocumentsData = {
  total: 3, vector_db: 'Qdrant - http://127.0.0.1:6333', store_error: '', search_error: '',
  store_empty: 'The document store is empty - run: python manage.py ingest_docs',
  counts: [{ source: 'business_rules.md', count: 2 }, { source: 'sql_examples.md', count: 1 }],
  pieces: [
    { no: 1, id: 'br-1', source: 'business_rules.md', kind: 'rule', heading: 'Financial year (FY)', text: 'FY text' },
    { no: 2, id: 'br-2', source: 'business_rules.md', kind: 'rule', heading: 'Stock value on a date', text: 'Never SUM every row.' },
    { no: 3, id: 'ex-1', source: 'sql_examples.md', kind: 'example', heading: 'Q: Current stock value?', text: 'SELECT 1' },
  ],
  hits: [], tables: null, source: '', find: '', question: '',
}

const SEARCHED: DocumentsData = {
  ...DATA, question: 'stock value',
  hits: [{ kind: 'example', score: 0.9123, heading: 'Hit number 1', source: 'sql_examples.md', text: 'text 1' },
         { kind: 'rule', score: 0.655, heading: 'Hit number 2', source: 'business_rules.md', text: 'text 2' }],
  tables: { all: false, names: ['dim_calendar', 'fact_stock_ledger'] },
}

describe('DocumentsPage', () => {
  it('shows the counts and every piece', async () => {
    fakeFetch({ '/api/documents': { body: DATA } })

    renderAt('/documents', <DocumentsPage source="" find="" q="" />)

    expect(await screen.findByText('All files · 3 pieces')).toBeInTheDocument()
    expect(screen.getByText('Qdrant - http://127.0.0.1:6333')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'business_rules.md · 2' })).toHaveAttribute('href', '/documents?source=business_rules.md')
    expect(screen.getByText('Showing 3 of 3 pieces. Click a piece to read its full text.')).toBeInTheDocument()
    expect(screen.getByText('Never SUM every row.')).toBeInTheDocument()            // the full text, folded
    expect(screen.getAllByText('RULE')).toHaveLength(2)
  })

  it('shows the test search hits best first with their scores', async () => {
    const fetch = fakeFetch({ '/api/documents?q=stock+value': { body: SEARCHED } })

    renderAt('/documents?q=stock+value', <DocumentsPage source="" find="" q="stock value" />)

    expect(await screen.findByText('Hit number 1')).toBeInTheDocument()
    expect(screen.getByText('score 0.91')).toBeInTheDocument()
    expect(screen.getByText('score 0.66')).toBeInTheDocument()
    expect(screen.getByText(/The SQL step would show the columns of: dim_calendar, fact_stock_ledger/)).toBeInTheDocument()
    expect(fetch.mock.calls[0][0]).toBe('/api/documents?q=stock+value')
  })

  it('puts the search and the filter into the address', async () => {
    fakeFetch({ '/api/documents': { body: DATA }, '/api/documents?q=open+orders': { body: SEARCHED },
                '/api/documents?source=sql_examples.md&find=stock': { body: DATA } })

    renderAt('/documents', <DocumentsPage source="" find="" q="" />)
    fireEvent.change(await screen.findByLabelText('Question'), { target: { value: 'open orders' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(window.location.search).toBe('?q=open+orders'))

    fireEvent.change(screen.getByLabelText('File'), { target: { value: 'sql_examples.md' } })
    fireEvent.change(screen.getByLabelText('Find'), { target: { value: 'stock' } })
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    await waitFor(() => expect(window.location.search).toBe('?source=sql_examples.md&find=stock'))
  })

  it('says how to build an empty store and shows a down store', async () => {
    fakeFetch({ '/api/documents': { body: { ...DATA, total: 0, counts: [], pieces: [] } } })
    const { unmount } = renderAt('/documents', <DocumentsPage source="" find="" q="" />)
    expect(await screen.findByText(/run: python manage.py ingest_docs/)).toHaveClass('errbox')
    expect(screen.queryByText('Test search')).not.toBeInTheDocument()
    unmount()

    fakeFetch({ '/api/documents': { body: { ...DATA, total: 0, pieces: [], store_error: 'The vector database (Qdrant) is not reachable - an admin must start it.' } } })
    renderAt('/documents', <DocumentsPage source="" find="" q="" />)
    expect(await screen.findByText(/Qdrant\) is not reachable/)).toHaveClass('errbox')
  })

  it('says "no access" when the API answers 403', async () => {
    fakeFetch({ '/api/documents': { status: 403, body: { detail: 'Only administrators can open this page.' } } })

    renderAt('/documents', <DocumentsPage source="" find="" q="" />)

    expect(await screen.findByText('You do not have access to this page')).toBeInTheDocument()
  })
})
