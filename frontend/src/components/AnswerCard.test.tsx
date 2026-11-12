// The answer card: an answered data question shows its SQL (folded), its rows and the Excel link;
// a documents answer shows its PDF pages (📄) and no SQL, rows or Excel; a saved memory shows its chip only.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { CATEGORY_SALE_TYPE } from '../charts/testRows'
import { charts, lastChart } from '../test/fakeEcharts'
import { callsTo, fakeFetch } from '../test/fakeFetch'
import { renderAt } from '../test/render'
import type { Card } from '../types'
import AnswerCard from './AnswerCard'

// jsdom has no canvas: ECharts is a fake that keeps the option it would draw
vi.mock('../charts/echarts', () => import('../test/fakeEcharts'))
vi.mock('../charts/echartsAi', () => ({}))
afterEach(() => { charts.length = 0 })

const SQL = 'SELECT customer_name, SUM(net_taxable_value) AS invoice_value_inr FROM fact_invoice_lines GROUP BY 1'

const OK: Card = {
  id: 7, text: 'Top 5 customers by invoice value?', status: 'ok',
  answer: 'Aurora Fluid Power Limited had the highest invoice value.',
  understood_as: '', backup_model: '', token_notice: '',
  time_steps: [{ label: 'Write the SQL (AI)', secs: 1.234, note: '' }, { label: 'Run the SQL on MySQL', secs: 0.05, note: '' }],
  sql: SQL, sources: [{ kind: 'example', heading: 'Q: Top customers' }, { kind: 'rule', heading: 'NOP sales month' }],
  secs: 1.5, tries: 1, row_count: 2, has_rows: true,
  rows_url: '/api/questions/7/rows', excel_url: '/api/questions/7/excel',
  created_at: '2026-11-03T10:15:00+05:30', created_text: '03 Nov 2026 10:15 AM', edited: false,
}

const DOCS: Card = {
  ...OK, id: 8, text: 'What does the quality manual say about audits?', status: 'docs',
  answer: 'Audits are made twice a year.', sql: '', has_rows: false, rows_url: '', excel_url: '', row_count: null,
  sources: [{ kind: 'pdf', heading: 'Quality manual, page 4' }],
}

const MEMORY: Card = {
  ...OK, id: 9, text: 'Remember that I only work with export sales', status: 'memory',
  answer: 'Memory updated - I will remember: "I only work with export sales". You can see or delete it on the Memory page.',
  sql: '', has_rows: false, rows_url: '', excel_url: '', row_count: null, sources: [], time_steps: [], tries: 0, secs: 0.02,
}

const ROWS = {
  headers: [{ name: 'customer_name', num: false }, { name: 'invoice_value_inr', num: true }],
  rows: [[{ text: 'Aurora Fluid Power Limited', num: false }, { text: '1,730,000.00', num: true }],
         [{ text: 'Meridian Hydraulics Limited', num: false }, { text: '747,750.00', num: true }]],
  row_count: 2, truncated: false, rows_error: '',
}

describe('AnswerCard', () => {
  // the chart is lazy-loaded: load it once up front, so the first chart test does not time out on it
  beforeAll(async () => { await import('../charts/AnswerChart') }, 30_000)

  it('shows an answered card with its SQL toggle, rows table and Excel link', async () => {
    const fetch = fakeFetch({ '/api/questions/7/rows': { body: ROWS } })

    const { container } = render(<AnswerCard card={OK} autoRows />)

    expect(screen.getByText('ANSWERED')).toBeInTheDocument()
    expect(screen.getByText(OK.answer)).toBeInTheDocument()
    const sqlToggle = screen.getByText('Show SQL')
    expect(sqlToggle.tagName).toBe('SUMMARY')                       // folded
    expect(container.querySelector('pre.sql')).toHaveTextContent('FROM fact_invoice_lines')
    expect(screen.getByText('Time taken: 1.5 s')).toBeInTheDocument()
    expect(screen.getByText('Sources used (2)')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download Excel' })).toHaveAttribute('href', '/api/questions/7/excel')

    // names + amounts fit a chart: the chart comes first (0 AI tokens), the table is one click away
    expect(await screen.findByRole('img', { name: /bar chart/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Table' }))
    expect(await screen.findByText('1,730,000.00')).toHaveClass('num') // rows from the API, right-aligned
    expect(screen.getByText('Meridian Hydraulics Limited')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show chart' }))  // and back to the chart
    expect(await screen.findByRole('img', { name: /bar chart/i })).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledTimes(1)                             // the rows are loaded once
    expect(fetch.mock.calls[0][0]).toBe('/api/questions/7/rows')
    expect(fetch.mock.calls[0][1]).toMatchObject({ credentials: 'include' })
  })

  it('loads the rows of an older answer only on "Show rows"', async () => {
    const fetch = fakeFetch({ '/api/questions/7/rows': { body: ROWS } })

    render(<AnswerCard card={OK} />)

    expect(fetch).not.toHaveBeenCalled()
    expect(screen.getByText(/2 rows/)).toBeInTheDocument()            // the saved row count
    fireEvent.click(screen.getByRole('button', { name: 'Show rows' }))
    expect(await screen.findByRole('img', { name: /bar chart/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Table' }))
    expect(await screen.findByText('Aurora Fluid Power Limited')).toBeInTheDocument()
  })

  it('shows the table straight away when the rows do not fit a chart', async () => {
    const ONE_ROW = { ...ROWS, rows: ROWS.rows.slice(0, 1), row_count: 1 }   // one number: no chart
    fakeFetch({ '/api/questions/7/rows': { body: ONE_ROW } })

    render(<AnswerCard card={OK} autoRows />)

    expect(await screen.findByText('1,730,000.00')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: /chart/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show chart' })).not.toBeInTheDocument()
  })

  it('draws monthly sales as a line chart', async () => {
    const MONTHS = {
      headers: [{ name: 'nop_sales_month', num: false }, { name: 'net_sales_inr', num: true }],
      rows: [['Jan 2026', '13,356,235.00'], ['Feb 2026', '9,032,845.00'], ['Mar 2026', '8,938,405.00']]
        .map(([month, value]) => [{ text: month, num: false }, { text: value, num: true }]),
      row_count: 3, truncated: false, rows_error: '',
    }
    fakeFetch({ '/api/questions/7/rows': { body: MONTHS } })

    render(<AnswerCard card={OK} autoRows />)

    expect(await screen.findByRole('img', { name: /line chart/i })).toBeInTheDocument()
  })

  it('shows a documents card with its PDF pages and no SQL, rows or Excel', () => {
    const fetch = fakeFetch({})

    render(<AnswerCard card={DOCS} autoRows />)

    expect(screen.getByText('FROM DOCUMENTS')).toBeInTheDocument()
    expect(screen.getByText(/📄 Quality manual, page 4/)).toBeInTheDocument()
    expect(screen.queryByText('Show SQL')).not.toBeInTheDocument()
    expect(screen.queryByText('Download Excel')).not.toBeInTheDocument()
    expect(screen.queryByText('Show rows')).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('shows a saved memory with its chip and a link to the Memory page, and no SQL, rows or Excel', () => {
    const fetch = fakeFetch({})

    renderAt('/c/3', <AnswerCard card={MEMORY} autoRows />)

    expect(screen.getByText('MEMORY UPDATED')).toHaveClass('chip', 'ok')
    expect(screen.getByText(MEMORY.answer)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the Memory page' })).toHaveAttribute('href', '/memory')
    expect(screen.queryByText('Show SQL')).not.toBeInTheDocument()
    expect(screen.queryByText('Download Excel')).not.toBeInTheDocument()
    expect(screen.queryByText('Show rows')).not.toBeInTheDocument()
    expect(screen.queryByText(/Time taken/)).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('shows the backup-model note and the friendly rows error', async () => {
    fakeFetch({ '/api/questions/7/rows': { body: { ...ROWS, rows: [], rows_error: 'The rows could not be loaded again: MySQL is down' } } })

    render(<AnswerCard card={{ ...OK, backup_model: 'qwen/qwen3.8-27b' }} autoRows />)

    expect(screen.getByText(/Answered by the backup model \(qwen\/qwen3.8-27b\)/)).toBeInTheDocument()
    expect(await screen.findByText(/could not be loaded again/)).toHaveClass('errbox')
  })
})

describe('AnswerCard chart wish', () => {
  beforeAll(async () => { await import('../charts/AnswerChart') }, 30_000)

  it('draws the kind the question asks for ("give me that bar chart")', async () => {
    const MONTHS = {
      headers: [{ name: 'nop_sales_month', num: false }, { name: 'net_sales_inr', num: true }],
      rows: [['Jan 2026', '13,356,235.00'], ['Feb 2026', '9,032,845.00'], ['Mar 2026', '8,938,405.00']]
        .map(([month, value]) => [{ text: month, num: false }, { text: value, num: true }]),
      row_count: 3, truncated: false, rows_error: '',
    }
    fakeFetch({ '/api/questions/7/rows': { body: MONTHS } })

    render(<AnswerCard card={{ ...OK, text: 'above questions give me that bar chart now',
      understood_as: 'Show a bar chart of sales amount for each month.' }} autoRows />)

    expect(await screen.findByRole('img', { name: /^Bar chart/ })).toBeInTheDocument()   // not the line
    expect(screen.queryByText(/no chart can be drawn|can't be drawn as a chart/)).not.toBeInTheDocument()
  })

  // 05-Nov: "for that above answer create one line chart" got 1 row - the chart was silently missing
  it('says why there is no chart when a chart was asked for and only 1 row came back', async () => {
    const ONE_ROW = { ...ROWS, rows: ROWS.rows.slice(0, 1), row_count: 1 }
    fakeFetch({ '/api/questions/7/rows': { body: ONE_ROW } })

    render(<AnswerCard card={{ ...OK, text: 'for that above answer create one line chart' }} autoRows />)

    expect(await screen.findByText('Only 1 row, so no chart can be drawn.')).toHaveClass('text-muted-foreground')
    expect(screen.getByText('1,730,000.00')).toBeInTheDocument()                   // the table is still there
    expect(screen.queryByRole('img', { name: /chart/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show chart' })).not.toBeInTheDocument()
  })

  it('says the answer cannot be drawn when its rows fit no chart', async () => {
    const NAMES = {
      headers: [{ name: 'customer_name', num: false }, { name: 'city', num: false }],
      rows: [['Aurora Fluid Power Limited', 'Pune'], ['Meridian Hydraulics Limited', 'Chennai']]
        .map((row) => row.map((text) => ({ text, num: false }))),
      row_count: 2, truncated: false, rows_error: '',
    }
    fakeFetch({ '/api/questions/7/rows': { body: NAMES } })

    render(<AnswerCard card={{ ...OK, text: 'customers and their cities', understood_as: 'Customers and cities as a bar chart' }}
      autoRows />)

    expect(await screen.findByText("This answer can't be drawn as a chart.")).toBeInTheDocument()
    expect(screen.getByText('Pune')).toBeInTheDocument()
  })

  it('adds no note when no chart was asked for, or when the AI can draw the chart', async () => {
    const ONE_ROW = { ...ROWS, rows: ROWS.rows.slice(0, 1), row_count: 1 }
    fakeFetch({ '/api/questions/7/rows': { body: ONE_ROW } })

    const { unmount } = render(<AnswerCard card={{ ...OK, text: 'Invoice value of Aurora in Oct 2026' }} autoRows />)
    expect(await screen.findByText('1,730,000.00')).toBeInTheDocument()
    expect(screen.queryByText(/no chart can be drawn|can't be drawn as a chart/)).not.toBeInTheDocument()
    unmount()

    render(<AnswerCard card={{ ...OK, text: 'Invoice value as a gauge chart' }} autoRows />)
    expect(await screen.findByRole('button', { name: 'Make this chart with AI' })).toBeInTheDocument()
    expect(screen.queryByText(/no chart can be drawn|can't be drawn as a chart/)).not.toBeInTheDocument()
  })
})

// the real answer "net sales by product category and sale type": 2 labels + an amount
const PIVOT_ROWS = { ...CATEGORY_SALE_TYPE, row_count: 17, truncated: false, rows_error: '' }
const PIVOT: Card = { ...OK, text: 'Net sales by product category and sale type', understood_as: '' }

describe('AnswerCard pivot', () => {
  beforeAll(async () => { await import('../charts/AnswerChart') }, 30_000)

  it('draws the 2-label rows as stacked bars, one series per sale type', async () => {
    fakeFetch({ '/api/questions/7/rows': { body: PIVOT_ROWS } })

    render(<AnswerCard card={PIVOT} autoRows />)

    expect(await screen.findByRole('img', { name: /^Stacked bar chart of net_sales_inr by product_category and sale_type/ }))
      .toBeInTheDocument()
    expect(lastChart().types()).toEqual(['bar', 'bar']) // Domestic, Export: Service was only in Not classified
    expect(screen.queryByRole('button', { name: 'Make this chart with AI' })).not.toBeInTheDocument() // no AI needed
    // Not classified is hidden from the chart only: the answer and the table keep it
    expect(screen.getByText(/Not classified \(398 Cr, 97% of the total\) is hidden so the other categories can be compared/))
      .toBeInTheDocument()
    expect(screen.getByText(PIVOT.answer)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Table' }))
    expect(await screen.findByText('3,314,096,846.50')).toBeInTheDocument()
    expect(screen.getAllByRole('cell', { name: 'Not classified' })).toHaveLength(3) // Domestic, Export, Service
    expect(screen.getByText('871,750.00')).toBeInTheDocument()
  })

  it('"as a treemap" draws a treemap', async () => {
    fakeFetch({ '/api/questions/7/rows': { body: PIVOT_ROWS } })

    render(<AnswerCard card={{ ...PIVOT, text: 'Show net sales by product category and sale type as a Treemap' }} autoRows />)

    expect(await screen.findByRole('img', { name: /^Treemap of net_sales_inr by product_category and sale_type, 7 boxes/ }))
      .toBeInTheDocument()
    await waitFor(() => expect(lastChart()?.types()).toEqual(['treemap'])) // the lazy chart may draw a moment later
  })
})

const SANKEY_OPTION = {
  series: [{ type: 'sankey', data: [{ name: 'Domestic' }, { name: 'GCI' }],
    links: [{ source: 'Domestic', target: 'GCI', value: 14952355 }] }],
  tooltip: { trigger: 'item' },
}

describe('AnswerCard AI chart', () => {
  beforeAll(async () => { await import('../charts/AnswerChart'); await import('../charts/AiChart') }, 30_000)

  it('offers "Make this chart with AI" for a chart the app cannot draw, and draws the AI\'s option', async () => {
    const fetch = fakeFetch({
      '/api/questions/7/rows': { body: PIVOT_ROWS },
      '/api/questions/7/chart': { body: { option: SANKEY_OPTION, tokens: 1234, model: 'openai/gpt-oss-120b', recorded: true } },
    })

    render(<AnswerCard card={{ ...PIVOT, text: 'Net sales from sale type to product category as a sankey' }} autoRows />)

    // the built-in chart is drawn too (0 tokens); the AI is asked only on a click
    expect(await screen.findByRole('img', { name: /^Stacked bar chart/ })).toBeInTheDocument()
    expect(screen.getByText(/A sankey diagram is not one of the built-in charts/)).toBeInTheDocument()
    expect(callsTo(fetch, '/api/questions/7/chart')).toEqual([])
    fireEvent.click(screen.getByRole('button', { name: 'Make this chart with AI' }))

    expect(await screen.findByRole('img', { name: "A sankey diagram made by the AI from the answer's rows." })).toBeInTheDocument()
    expect(callsTo(fetch, '/api/questions/7/chart')).toEqual([{ kind: 'sankey diagram' }])
    const call = fetch.mock.calls.find(([url]) => url === '/api/questions/7/chart')
    expect(call?.[1]).toMatchObject({ method: 'POST', credentials: 'include' })
    expect((call?.[1]?.headers as Record<string, string>)['X-CSRFToken']).toBeDefined()
    const ai = charts.find((chart) => chart.types().includes('sankey'))
    expect(ai?.option?.tooltip).toMatchObject({ trigger: 'item', renderMode: 'richText', confine: true }) // plus the theme's colours
    expect(screen.getByText(/1,234 AI tokens \(added to this question's tokens\)/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Make this chart with AI' })).not.toBeInTheDocument()
  })

  it('shows a friendly message when the AI chart cannot be made, and the rows stay', async () => {
    fakeFetch({
      '/api/questions/7/rows': { body: ROWS },
      '/api/questions/7/chart': { status: 503, body: { detail: 'The AI service is busy right now (rate limit). Please wait a minute and ask again.' } },
    })

    render(<AnswerCard card={{ ...OK, text: 'Top customers as a box plot' }} autoRows />)

    fireEvent.click(await screen.findByRole('button', { name: 'Make this chart with AI' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The AI service is busy right now')
    expect(screen.getByRole('button', { name: 'Make this chart with AI' })).toBeInTheDocument() // try again
    expect(screen.getByRole('img', { name: /bar chart/i })).toBeInTheDocument()                // the chart and the
    fireEvent.click(screen.getByRole('button', { name: 'Table' }))                               // table stay
    expect(await screen.findByText('Aurora Fluid Power Limited')).toBeInTheDocument()
  })

  it('offers the AI button even when the rows fit no built-in chart', async () => {
    const ONE_ROW = { ...ROWS, rows: ROWS.rows.slice(0, 1), row_count: 1 }
    fakeFetch({ '/api/questions/7/rows': { body: ONE_ROW } })

    render(<AnswerCard card={{ ...OK, text: 'Invoice value as a gauge chart' }} autoRows />)

    expect(await screen.findByRole('button', { name: 'Make this chart with AI' })).toBeInTheDocument()
    expect(screen.getByText('1,730,000.00')).toBeInTheDocument()
    await waitFor(() => expect(charts).toHaveLength(0))
  })
})
