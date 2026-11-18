// ML Dashboard (/ml-dashboard, every user): the 6 machine-learning results from /api/insights - the sales forecast (a
// chart of 12 actual months, then 3 forecast months over a low-high band), customers at risk, customer groups,
// unusual invoices, products bought together and stock running out; the calm note before the models have run, the
// red box when the call fails, the menu item, the tab title and the top bar's "New chat". 18-Nov: the cards moved here
// from ML Insights; a card's "Ask about this" opens ML Insights and asks its question there in a new ML chat
// (/insights?new=1&ask=<question>). ECharts and fetch are fakes.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { forecastOption, forecastSeries, segmentsOption } from '../charts/insightsOption'
import { readColours } from '../charts/chartOption'
import { askInMlPath, parseRoute } from '../router'
import { charts } from '../test/fakeEcharts'
import { fakeFetch } from '../test/fakeFetch'
import { ASHA, renderAt } from '../test/render'
import type { InsightsData } from '../types'
import MlDashboard, { ASK, crore, dayText, inr, runText, soonest } from './MlDashboard'

vi.mock('../charts/echarts', () => import('../test/fakeEcharts'))

afterEach(() => {
  charts.length = 0
})

type Option = Record<string, any>

const MONTHS = ['Nov 2025', 'Dec 2025', 'Jan 2026', 'Feb 2026', 'Mar 2026', 'Apr 2026', 'May 2026', 'Jun 2026', 'Jul 2026',
  'Aug 2026', 'Sep 2026', 'Oct 2026']

const FULL: InsightsData = {
  ready: true,
  run_at: '2026-11-17T16:00:00',
  data_to: '2026-10-31',
  forecast: {
    model: 'Holt-Winters (additive)',
    mape_pct: 8.43,
    history: MONTHS.map((month, i) => ({ month, actual: 50_000_000 + i * 1_000_000 })),
    months: [
      { month: 'Nov 2026', period_start: '2026-10-21', period_end: '2026-11-20', forecast: 63_648_019, low: 55_000_000, high: 72_000_000 },
      { month: 'Dec 2026', period_start: '2026-11-21', period_end: '2026-12-20', forecast: 65_100_000, low: 56_000_000, high: 74_500_000 },
      { month: 'Jan 2027', period_start: '2026-12-21', period_end: '2027-01-20', forecast: 61_000_000, low: 51_200_000, high: 70_800_000 },
    ],
    products: [
      { product_code: 'HM-346', product_description: 'Hydraulic motor HM-346-1B', month: 'Nov 2026', forecast: 9_000_000, low: 7_000_000, high: 11_000_000 },
      { product_code: 'HM-346', product_description: 'Hydraulic motor HM-346-1B', month: 'Dec 2026', forecast: 9_500_000, low: 7_500_000, high: 11_500_000 },
      { product_code: 'GP-120', product_description: 'Gear pump GP-120', month: 'Nov 2026', forecast: 2_462_000, low: 2_000_000, high: 2_900_000 },
    ],
  },
  risk: {
    counts: { High: 12, Medium: 30, Low: 410 },
    customers: [
      { customer_name: 'Aurora Hydraulics Private Limited', risk_score: 87, risk_level: 'High', reason: 'No invoice for 96 days; sales down 62%',
        last_invoice_date: '2026-07-27', sales_last_3m: 1_200_000, sales_prev_3m: 3_160_000, change_pct: -62.0 },
      { customer_name: 'Northern Tech Works', risk_score: 54, risk_level: 'Medium', reason: 'Orders less often than before',
        last_invoice_date: '2026-09-02', sales_last_3m: 850_000, sales_prev_3m: 1_000_000, change_pct: -15 },
    ],
  },
  segments: [
    { segment_name: 'Loyal big buyers', customers: 48, sales_inr: 412_000_000, avg_recency_days: 12, avg_invoices: 41.2 },
    { segment_name: 'Regular', customers: 160, sales_inr: 150_000_000, avg_recency_days: 34, avg_invoices: 9.4 },
    { segment_name: 'Sleeping', customers: 92, sales_inr: 8_000_000, avg_recency_days: 210, avg_invoices: 2.1 },
  ],
  alerts: {
    counts: { 'Unusual price': 7, 'Unusual quantity': 4, 'Large credit note': 2 },
    items: [
      { alert_type: 'Unusual price', invoice_number: 'INV/26/0412', invoice_date: '2026-10-05', customer_name: 'Northern Tech Works',
        product_code: 'GP-120', value_inr: 420_000, typical_inr: 110_000, reason: 'Price 3.8x the usual for this product' },
      { alert_type: 'Large credit note', invoice_number: 'CN/26/0033', invoice_date: '2026-09-18', customer_name: 'Aurora Hydraulics Private Limited',
        product_code: '', value_inr: -1_850_000, typical_inr: null, reason: 'The largest credit note this year' },
    ],
  },
  pairs: [
    { product_a_code: 'HM-346', product_a_description: 'Hydraulic motor HM-346-1B', product_b_code: 'SK-12', product_b_description: 'Seal kit SK-12',
      orders_together: 64, confidence_pct: 71, lift: 4.26 },
  ],
  stockout: {
    counts: { 'Out of stock': 3, 'Under 30 days': 9, 'Under 90 days': 21, OK: 300, 'No recent sales': 55 },
    items: [
      { product_code: 'GP-120', product_description: 'Gear pump GP-120', stock_qty: 140, avg_daily_sales_qty: 6.25, days_left: 22,
        runout_date: '2026-11-22', status: 'Under 30 days' },
      { product_code: 'VL-9', product_description: 'Valve VL-9', stock_qty: 0, avg_daily_sales_qty: 3, days_left: 0,
        runout_date: '2026-10-31', status: 'Out of stock' },
    ],
  },
}

const card = (name: string) => within(screen.getByRole('region', { name }))
/** The page's results (the 6 cards). */
const results = () => within(screen.getByRole('region', { name: 'ML results' }))
const where = () => window.location.pathname + window.location.search

async function openPage(body: unknown = FULL, status = 200) {
  const fetch = fakeFetch({ '/api/insights': { status, body } })
  renderAt('/ml-dashboard', <MlDashboard />)
  return fetch
}

describe('ML Dashboard: the formats', () => {
  it('writes dates, the run time and money the app\'s way', () => {
    expect(dayText('2026-10-31')).toBe('31-Oct-2026')
    expect(dayText(null)).toBe('-')
    expect(runText('2026-11-17T16:00:00')).toBe('17-Nov-2026, 4:00 PM')
    expect(runText('2026-11-17T09:05:00')).toBe('17-Nov-2026, 9:05 AM')
    expect(inr(63_648_019)).toBe('INR 6.36 Cr')
    expect(inr(2_462_000)).toBe('INR 24.6 L')
    expect(crore(63_648_019)).toBe('6.36')
  })

  it('lists the stock that runs out first at the top', () => {
    expect(soonest(FULL.stockout!.items).map((s) => s.product_code)).toEqual(['VL-9', 'GP-120'])
  })
})

describe('MlDashboard', () => {
  it('shows all 6 cards with their numbers and counts', async () => {
    const fetch = await openPage()
    expect(await screen.findByText(/Estimates by machine-learning models on the data up to 31-Oct-2026 · last run 17-Nov-2026, 4:00 PM/))
      .toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith('/api/insights', expect.objectContaining({ method: 'GET' }))
    expect(results().getAllByRole('region').map((r) => r.getAttribute('aria-label'))).toEqual([
      'Sales forecast', 'Customers at risk', 'Customer groups', 'Bought together', 'Unusual invoices', 'Stock running out',
    ])

    // 1. the forecast: the 3 months in Cr with their range and dates, the accuracy, the products on a click
    const forecast = card('Sales forecast')
    const nov = within(forecast.getByRole('list', { name: 'The next 3 sales months' })).getAllByRole('listitem')[0]
    expect(nov).toHaveTextContent('Nov 2026')
    expect(nov).toHaveTextContent('21-Oct-2026 to 20-Nov-2026')
    expect(nov).toHaveTextContent('INR 6.36 Cr')
    expect(nov).toHaveTextContent('Likely 5.50 – 7.20 Cr')
    expect(forecast.getByText('Model accuracy: about 8.4% error (MAPE) on the last 6 months')).toBeInTheDocument()
    expect(forecast.queryByRole('table')).not.toBeInTheDocument()
    fireEvent.click(forecast.getByRole('button', { name: 'Show the top 2 product forecasts' }))
    const products = forecast.getByRole('table', { name: 'Top product forecasts' })
    const rows = within(products).getAllByRole('row')
    expect(rows[0]).toHaveTextContent('ProductNov 2026Dec 2026')
    expect(rows[1]).toHaveTextContent('Hydraulic motor HM-346-1B')            // the biggest total first
    expect(rows[1]).toHaveTextContent('INR 90 L')
    expect(rows[2]).toHaveTextContent('INR 24.6 L')
    expect(rows[2]).toHaveTextContent('-')                                     // no Dec forecast for this one

    // 2. customers at risk
    const risk = card('Customers at risk')
    expect(within(risk.getByRole('list', { name: 'Customers by risk' })).getAllByRole('listitem').map((li) => li.textContent))
      .toEqual(['High12', 'Medium30', 'Low410'])
    const aurora = risk.getByRole('row', { name: /Aurora Hydraulics/ })
    expect(aurora).toHaveTextContent('87of 100, High')
    expect(aurora).toHaveTextContent('27-Jul-2026')
    expect(aurora).toHaveTextContent('INR 12 L')
    expect(aurora).toHaveTextContent('INR 31.6 L')
    expect(aurora).toHaveTextContent('-62%')

    // 3. customer groups: the donut and a line per group
    const groups = card('Customer groups')
    expect(within(groups.getByRole('list', { name: 'Customer groups' })).getAllByRole('listitem')).toHaveLength(3)
    expect(groups.getByText('Loyal big buyers').closest('li')).toHaveTextContent('INR 41.2 Cr')
    expect(groups.getByText('Loyal big buyers').closest('li'))
      .toHaveTextContent('48 customers (16%) · last bought about 12 days ago · 41.2 invoices each on average')

    // 4. unusual invoices
    const alerts = card('Unusual invoices')
    expect(within(alerts.getByRole('list', { name: 'Unusual invoices by type' })).getAllByRole('listitem').map((li) => li.textContent))
      .toEqual(['Unusual price7', 'Unusual quantity4', 'Large credit note2'])
    const price = alerts.getByRole('row', { name: /INV\/26\/0412/ })
    expect(price).toHaveTextContent('Unusual price')
    expect(price).toHaveTextContent('05-Oct-2026')
    expect(price).toHaveTextContent('INR 4.2 L')
    expect(price).toHaveTextContent('typical INR 1.1 L')
    expect(alerts.getByRole('row', { name: /CN\/26\/0033/ })).toHaveTextContent('INR -18.5 L')

    // 5. bought together
    const pair = card('Bought together').getByRole('row', { name: /Seal kit/ })
    expect(pair).toHaveTextContent('Hydraulic motor HM-346-1B')
    expect(pair).toHaveTextContent('6471%4.3×')

    // 6. stock running out: the counts, the soonest first
    const stock = card('Stock running out')
    expect(within(stock.getByRole('list', { name: 'Items by stock status' })).getAllByRole('listitem').map((li) => li.textContent))
      .toEqual(['Out of stock3', 'Under 30 days9', 'Under 90 days21', 'OK300', 'No recent sales55'])
    const stockRows = within(stock.getByRole('table')).getAllByRole('row')
    expect(stockRows[1]).toHaveTextContent('Valve VL-9')
    expect(stockRows[2]).toHaveTextContent('Gear pump GP-120')
    expect(stockRows[2]).toHaveTextContent('1406.32222-Nov-2026Under 30 days')
  })

  it('draws the forecast: 12 actual months, then 3 forecast months over the low-high band', async () => {
    await openPage()
    await waitFor(() => expect(charts.some((c) => c.option?.series?.some((s: Option) => s.name === 'Forecast'))).toBe(true))
    const chart = charts.find((c) => c.option?.series?.some((s: Option) => s.name === 'Forecast'))!
    const option = chart.option as Option
    const byName = (name: string) => option.series.find((s: Option) => s.name === name)
    expect(option.xAxis.data).toEqual([...MONTHS, 'Nov 2026', 'Dec 2026', 'Jan 2027'])
    const actual = byName('Actual').data as (number | null)[]
    expect(actual.filter((v) => v !== null)).toHaveLength(12)
    expect(actual.slice(12)).toEqual([null, null, null])
    const ahead = byName('Forecast')
    expect(ahead.lineStyle.type).toBe('dashed')
    expect(ahead.data.slice(12)).toEqual([63_648_019, 65_100_000, 61_000_000])
    expect(ahead.data[11]).toBe(actual[11])                                   // joins the last actual month
    expect(ahead.data.slice(0, 11).every((v: unknown) => v === null)).toBe(true)
    // the band: an invisible line up to "low", and "high - low" stacked on it, filled
    expect(byName('Low').stack).toBe('band')
    expect(byName('Low').data.slice(12)).toEqual([55_000_000, 56_000_000, 51_200_000])
    expect(byName('Likely range').stack).toBe('band')
    expect(byName('Likely range').data.slice(12)).toEqual([17_000_000, 18_500_000, 19_600_000])
    expect(byName('Likely range').areaStyle).toBeTruthy()
    expect(option.tooltip.formatter([{ dataIndex: 12 }])).toContain('INR 6.36 Cr')
    expect(option.tooltip.formatter([{ dataIndex: 12 }])).toContain('5.5 Cr – 7.2 Cr')
    expect(screen.getByRole('img', { name: /Nov 2026 INR 6.36 Cr \(between 5.50 and 7.20 Cr\)/ })).toBeInTheDocument()

    // the donut of the customer groups
    const donut = charts.find((c) => c.types().includes('pie'))!
    expect(donut.option!.series[0].data).toEqual([
      { name: 'Loyal big buyers', value: 48 }, { name: 'Regular', value: 160 }, { name: 'Sleeping', value: 92 },
    ])
  })

  it('builds the options in the theme\'s colours, light and dark', () => {
    const light = forecastOption(FULL.forecast!, readColours('light'), false, false) as Option
    const dark = forecastOption(FULL.forecast!, readColours('dark'), false, false) as Option
    expect(light.series[2].lineStyle.color).not.toBe(dark.series[2].lineStyle.color)
    expect(forecastSeries(FULL.forecast!).band.slice(11)).toEqual([0, 17_000_000, 18_500_000, 19_600_000])
    const pie = segmentsOption(FULL.segments!, readColours('light'), false, false) as Option
    expect(pie.tooltip.formatter({ dataIndex: 0, color: '#000000' })).toContain('INR 41.2 Cr')
  })

  it('each card has an "Ask about this" button with its question; a click opens ML Insights to ask it in a new ML chat', async () => {
    const fetch = await openPage()
    await screen.findByRole('region', { name: 'Sales forecast' })
    const buttons = results().getAllByRole('button', { name: /^Ask about this/ })
    expect(buttons.map((b) => b.getAttribute('title'))).toEqual([
      ASK.forecast, ASK.risk, ASK.segments, ASK.pairs, ASK.alerts, ASK.stock,
    ].map((q) => `Ask: ${q}`))
    expect(ASK).toEqual({
      forecast: 'What will our sales be in the next 3 months?', risk: 'Which customers might stop buying?',
      segments: 'What customer groups do we have?', alerts: 'Show the unusual invoices',
      pairs: 'Which products are bought together?', stock: 'Which items will run out of stock soon?',
    })
    expect(askInMlPath(ASK.risk)).toBe('/insights?new=1&ask=Which%20customers%20might%20stop%20buying%3F')

    fireEvent.click(card('Customers at risk').getByRole('button', { name: 'Ask about this: Which customers might stop buying?' }))
    expect(where()).toBe('/insights?new=1&ask=Which%20customers%20might%20stop%20buying%3F')
    expect(parseRoute(window.location.pathname, window.location.search))
      .toEqual({ kind: 'insights', chat: null, fresh: true, ask: ASK.risk })
    // nothing is asked on this page itself
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/insights'])
  })


  it('shows "Show all" when a table has more rows than it shows first', async () => {
    const many = Array.from({ length: 11 }, (_, i) => ({ ...FULL.pairs![0], product_b_code: `SK-${i}`, product_b_description: `Seal kit ${i}` }))
    await openPage({ ...FULL, pairs: many })
    const pairs = within(await screen.findByRole('region', { name: 'Bought together' }))
    expect(within(pairs.getByRole('table')).getAllByRole('row')).toHaveLength(1 + 8)
    fireEvent.click(pairs.getByRole('button', { name: 'Show all 11' }))
    expect(within(pairs.getByRole('table')).getAllByRole('row')).toHaveLength(1 + 11)
    expect(pairs.getByRole('button', { name: 'Show fewer' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('a card without results says so, the others still show', async () => {
    await openPage({ ...FULL, pairs: [], forecast: null })
    expect(within(await screen.findByRole('region', { name: 'Bought together' })).getByText('No results from this model yet.')).toBeInTheDocument()
    expect(card('Sales forecast').getByText('No results from this model yet.')).toBeInTheDocument()
    expect(card('Customers at risk').getByRole('table')).toBeInTheDocument()
  })

  it('before the models have run: a calm note, no error, no cards', async () => {
    await openPage({ ready: false, run_at: null, data_to: null })
    expect(await screen.findByText('The ML results are not ready yet - an admin runs run_ml after each data load.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Sales forecast' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Estimates by machine-learning models/)).not.toBeInTheDocument()
  })

  it('a failed call shows the error box', async () => {
    await openPage({ detail: 'The insights tables cannot be read.' }, 500)
    expect(await screen.findByRole('alert')).toHaveTextContent('The insights tables cannot be read.')
    expect(screen.queryByRole('region', { name: 'Sales forecast' })).not.toBeInTheDocument()
  })
})

describe('ML Dashboard in the app', () => {
  it('is in the menu (Intelligence, after ML Insights) for a normal user, lit on its page, with its titles', async () => {
    expect(parseRoute('/ml-dashboard')).toEqual({ kind: 'mldashboard' })
    expect(parseRoute('/ml-dashboard/')).toEqual({ kind: 'mldashboard' })
    fakeFetch({ '/api/me': { body: ASHA }, '/api/insights': { body: FULL } })
    window.history.pushState(null, '', '/ml-dashboard')
    render(<App />)
    const link = await screen.findByRole('link', { name: 'ML Dashboard' }, { timeout: 4000 })
    expect(link).toHaveAttribute('href', '/ml-dashboard')
    expect(link).toHaveAttribute('aria-current', 'page')
    const group = screen.getByRole('group', { name: 'Intelligence' })
    expect(within(group).getAllByRole('link').map((a) => a.textContent)).toEqual(['Knowledge graph', 'ML Insights', 'ML Dashboard'])
    expect(within(group).getByRole('link', { name: 'ML Insights' })).not.toHaveAttribute('aria-current')
    await waitFor(() => expect(document.title).toBe('ML Dashboard · SS Manufacturing'))
    expect(screen.getByRole('heading', { level: 1, name: 'ML Dashboard' })).toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Stock running out' })).toBeInTheDocument()
    // no ML chat on this page
    expect(screen.queryByLabelText('Your question about forecasts and insights')).not.toBeInTheDocument()
  })

  it("the top bar's New chat here starts a new ML chat on ML Insights", async () => {
    fakeFetch({ '/api/me': { body: ASHA }, '/api/insights': { body: FULL } })
    window.history.pushState(null, '', '/ml-dashboard')
    render(<App />)
    await screen.findByRole('region', { name: 'Stock running out' }, { timeout: 4000 })
    const newChat = within(screen.getByRole('banner')).getByRole('link', { name: 'New chat' })
    expect(newChat).toHaveAttribute('href', '/insights?new=1')
    fireEvent.click(newChat)
    expect(where()).toBe('/insights?new=1')
    expect(await screen.findByLabelText('Your question about forecasts and insights')).toHaveValue('')
    expect(screen.getByRole('heading', { level: 1, name: 'ML Insights' })).toBeInTheDocument()
  })
})

// 18-Nov: the forecast goes 12 sales months ahead - 3 tiles, all 12 in a table behind a button
describe('ML Dashboard: a 12-month forecast', () => {
  it('shows the next 3 months as tiles and all 12 in the table', async () => {
    const names = ['Nov 2026', 'Dec 2026', 'Jan 2027', 'Feb 2027', 'Mar 2027', 'Apr 2027', 'May 2027', 'Jun 2027',
      'Jul 2027', 'Aug 2027', 'Sep 2027', 'Oct 2027']
    const months = names.map((month, i) => ({
      month, period_start: '2026-10-21', period_end: '2026-11-20',
      forecast: 50_000_000 + i * 1_000_000, low: 45_000_000 + i * 500_000, high: 55_000_000 + i * 1_500_000,
    }))
    await openPage({ ...FULL, forecast: { ...FULL.forecast!, months } })

    const tiles = await screen.findByRole('list', { name: 'The next 3 sales months' })
    expect(within(tiles).getAllByRole('listitem')).toHaveLength(3)
    fireEvent.click(screen.getByRole('button', { name: /Show all 12 forecast months/ }))
    const rows = document.querySelectorAll('[data-all-month]')
    expect(rows).toHaveLength(12)
    expect(rows[11]).toHaveTextContent('Oct 2027')
  })

  it('has no extra table for 3 months', async () => {
    await openPage()
    await screen.findByRole('list', { name: 'The next 3 sales months' })
    expect(screen.queryByRole('button', { name: /forecast months/ })).not.toBeInTheDocument()
  })
})
