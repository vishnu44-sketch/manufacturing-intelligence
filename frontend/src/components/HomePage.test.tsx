// Home: the welcome banner (greeting, the clock, NOP month / FY badges, the quick start), the KPI
// cards (icon, counting number, small line of the last months, change badge, a click opens the Ask page), the
// recent questions, the usage bar and its colours, the connections, the tables, how it works; skeletons while it
// loads; MySQL down (only the data parts say so), the whole call failing, and an older server without
// trend / ask / facts / name / recent. The card grids: their columns chosen from the number of cards (8 KPI
// cards: 4 a row, 6: 3 a row), the facts chips where there is no small line, the top customer / product cards.
// Also the small Badge and Progress parts.
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Badge } from './ui/badge'
import { Progress } from './ui/progress'
import { fakeFetch } from '../test/fakeFetch'
import { ASHA, renderAt } from '../test/render'
import type { HomeData } from '../types'
import pageSource from './HomePage.tsx?raw'
import HomePage, { gridClass, greeting, shortTokens, usageColour, wideColumns } from './HomePage'

const TREND = [
  { label: 'May 2026', value: 900000 }, { label: 'Jun 2026', value: 1100000 }, { label: 'Jul 2026', value: 950000 },
  { label: 'Aug 2026', value: 1300000 }, { label: 'Sep 2026', value: 1000000 }, { label: 'Oct 2026', value: 1200000 },
]

const HOME: HomeData = {
  first_name: 'Asha',
  today: '05-Nov-2026',
  calendar: { today: '05-Nov-2026', month: 'Nov 2026', month_from: '21-Oct-2026', month_to: '20-Nov-2026', fy: '2627', fy_label: 'FY 2026-27' },
  kpis: [
    { key: 'month_sales', label: 'Net sales Oct 2026', money: true, value: 1200000, text: 'INR 1,200,000.00',
      note: '21-Sep-2026 to 20-Oct-2026 (last complete NOP sales month)', change: { pct: 20, direction: 'up', text: '20.0% vs Sep 2026' },
      trend: TREND, ask: 'What were the net sales in Oct 2026?' },
    { key: 'fy_sales', label: 'Net sales FY 2026-27 so far', money: true, value: 4360522752.5, text: 'INR 4,360,522,752.50',
      note: '01-Apr-2026 to 05-Nov-2026', change: null, trend: null, ask: 'Net sales in FY 2026-27 so far?' },
    { key: 'customers', label: 'Active customers', money: false, value: 2063, text: '2,063',
      note: 'of 5,000 customers bought in FY 2026-27 so far', change: { pct: -12.5, direction: 'down', text: '12.5% vs the same dates of FY 2025-26' },
      trend: [{ label: 'Oct 2026', value: 400 }], ask: 'How many customers bought in FY 2026-27?' },
    { key: 'products', label: 'Products sold', money: false, value: 3811, text: '3,811', note: 'different products invoiced', change: null },
    { key: 'open_orders', label: 'Open sales orders', money: true, value: 5335415, text: 'INR 5,335,415.00',
      note: '10 orders (14 lines) before GST, as of 05-Nov-2026', change: null, trend: null, ask: '',
      facts: ['10 orders', '14 lines', 'INR 60.6 L incl. GST'] },
    { key: 'stock', label: 'Stock value', money: true, value: 23856971.91, text: 'INR 23,856,971.91',
      note: 'Stock report of 20-Sep-2026 (52 items)', change: null, trend: null, ask: 'What is the stock value?',
      facts: ['52 items', 'Report 20-Sep-2026'] },
    { key: 'top_customer', label: 'Top customer Oct 2026', name: 'Allied Castings Limited', money: true, value: 63648019,
      text: 'INR 63,648,019.00', note: 'Net sales 21-Sep-2026 to 20-Oct-2026', change: null, trend: null,
      ask: 'Top customers by net sales in Oct 2026?', facts: ['2.7% of Oct 2026 sales'] },
    { key: 'top_product', label: 'Top product Oct 2026', name: 'Brake drum BD-220 heavy duty, machined', money: true,
      value: 12450000, text: 'INR 12,450,000.00', note: 'Net sales 21-Sep-2026 to 20-Oct-2026', change: null, trend: null,
      ask: 'Top products by net sales in Oct 2026?', facts: null },
  ],
  kpi_error: '',
  tables: [
    { table: 'fact_invoice_lines', name: 'Sales invoices', note: 'Invoice, credit and debit note lines', rows: 100720,
      rows_text: '100,720', from: '21-Dec-2025', to: '20-Mar-2027', after_today: true },
    { table: 'dim_customers', name: 'Customers', note: 'The customer master', rows: 5001, rows_text: '5,001', from: '', to: '', after_today: false },
  ],
  tables_error: '',
  connections: [
    { key: 'ai_gold', name: 'MySQL ai_gold', what: 'Company data (read-only)', ok: true, note: 'Reachable' },
    { key: 'docs', name: 'Qdrant mi_docs', what: 'SQL notes for the AI (RAG)', ok: false, note: 'Not reachable right now' },
    { key: 'groq', name: 'Groq AI', what: 'openai/gpt-oss-120b', ok: true, note: 'Key set' },
  ],
  connections_error: '',
  usage: { questions_today: 9, my_tokens_today: 90403, my_tokens_text: '90,403', model: 'openai/gpt-oss-120b',
           tokens_24h: '143,064', limit: '200,000', pct: 72, period_tokens: '0', period_pct: 0, questions_left: 19, period_end: '' },
  usage_error: '',
  model: 'openai/gpt-oss-120b',
  recent: [
    { id: 41, text: 'Top 5 customers by invoice value in Oct 2026?', status: 'ok', when: '05-Nov 2:04 PM', url: '/q/41' },
    { id: 40, text: 'What does a credit note mean here?', status: 'docs', when: '05-Nov 1:50 PM', url: '/q/40' },
    { id: 39, text: 'Sales of product X in 2030?', status: 'nodata', when: '04-Nov 6:12 PM', url: '/q/39' },
    { id: 38, text: 'Write me a poem', status: 'refused', when: '04-Nov 6:10 PM', url: '/q/38' },
    { id: 37, text: 'Stock by warehouse?', status: 'error', when: '04-Nov 5:00 PM', url: '/q/37' },
  ],
  recent_error: '',
}

/** What an older server sends: the first 6 KPI cards only, no trend, ask, facts or name, no recent. */
function oldServer(): HomeData {
  const { recent: _recent, recent_error: _error, ...rest } = HOME
  return { ...rest, kpis: HOME.kpis.slice(0, 6).map(({ trend: _trend, ask: _ask, facts: _facts, name: _name, ...kpi }) => kpi) }
}

/** 6 tables, as the server sends them. */
const SIX_TABLES = ['fact_invoice_lines', 'fact_sales_orders', 'dim_customers', 'dim_products', 'fact_stock', 'dim_calendar']
  .map((table, i) => ({ ...HOME.tables[1], table, name: `Table ${i + 1}` }))

const grid = (name: string) => document.querySelector(`[data-grid="${name}"]`) as HTMLElement

const ME = { ...ASHA, examples: ['Top 5 customers?', 'Open orders?', 'Stock value?', 'A fourth one'] }

const kpi = (key: string) => document.querySelector(`[data-kpi="${key}"]`) as HTMLElement
const valueOf = (key: string) => kpi(key).querySelector('[data-slot="kpi-value"]') as HTMLElement

/** Lets the KPI numbers count: the browser allows motion, and the animation frames run when the test says so. */
function controlledMotion() {
  const had = { matchMedia: window.matchMedia, raf: window.requestAnimationFrame, caf: window.cancelAnimationFrame }
  let waiting: FrameRequestCallback[] = []
  window.matchMedia = ((query: string) => ({ matches: !query.includes('reduce') })) as unknown as typeof window.matchMedia
  window.requestAnimationFrame = (cb) => { waiting.push(cb); return waiting.length }
  window.cancelAnimationFrame = () => {}
  return {
    frame(time: number) {
      const now = waiting
      waiting = []
      act(() => { for (const cb of now) cb(time) })
    },
    restore() {
      if (had.matchMedia) window.matchMedia = had.matchMedia
      else delete (window as Partial<Window>).matchMedia
      window.requestAnimationFrame = had.raf
      window.cancelAnimationFrame = had.caf
    },
  }
}

describe('HomePage', () => {
  it('shows the welcome banner: the greeting, the clock, the NOP month / FY badges and the quick start (no buttons)', async () => {
    fakeFetch({ '/api/home': { body: HOME } })

    renderAt('/', <HomePage me={ME} />)

    expect(await screen.findByText('NOP sales month Nov 2026 · 21-Oct-2026 to 20-Nov-2026')).toBeInTheDocument()
    const hero = screen.getByRole('region', { name: 'Welcome' })
    expect(within(hero).getByRole('heading', { name: /^Good (morning|afternoon|evening), Asha/ })).toBeInTheDocument()
    const today = within(hero).getByRole('list', { name: 'Today' })
    expect(within(today).getAllByRole('listitem')).toHaveLength(2)                 // the date is in the clock now
    expect(within(today).getByText('FY 2026-27')).toHaveAttribute('data-slot', 'badge')
    expect(hero.querySelector('[data-slot="hero-clock"]')).toHaveTextContent(/IST$/)   // today's date and time

    expect(within(hero).queryByRole('link', { name: 'Ask AI' })).not.toBeInTheDocument()   // the feature cards have them
    expect(within(hero).queryByRole('link', { name: 'Knowledge graph' })).not.toBeInTheDocument()
    expect(within(hero).getByRole('link', { name: 'Top 5 customers?' })).toHaveAttribute('href', '/new?q=Top%205%20customers%3F')
    expect(screen.queryByRole('link', { name: 'A fourth one' })).not.toBeInTheDocument()   // only 3
    fireEvent.click(within(hero).getByRole('link', { name: 'Open orders?' }))
    expect(window.location.pathname + window.location.search).toBe('/new?q=Open%20orders%3F')   // nothing asked yet
  })

  it('shows the KPI cards: short and full amounts, the change badges, the small line only with a trend', async () => {
    fakeFetch({ '/api/home': { body: HOME } })

    renderAt('/', <HomePage me={ME} />)

    await screen.findByText('2,063')
    expect(document.querySelectorAll('[data-kpi]')).toHaveLength(8)
    const month = kpi('month_sales')
    expect(within(month).getByText('Net sales Oct 2026')).toBeInTheDocument()
    expect(within(month).getByText('INR 12 L')).toBeInTheDocument()                 // short, in Indian units
    expect(within(month).getByText('INR 1,200,000.00')).toBeInTheDocument()         // and in full, as on the Ask page
    const up = month.querySelector('[data-change]') as HTMLElement
    expect(up).toHaveAttribute('data-change', 'up')
    expect(up).toHaveTextContent('▲Up 20.0% vs Sep 2026')
    expect(up.className).toContain('text-white')        // white on glass on the blue main card (HomeKpiCards.tsx)
    const down = kpi('customers').querySelector('[data-change]') as HTMLElement
    expect(down).toHaveTextContent('▼Down 12.5% vs the same dates of FY 2025-26')
    expect(down.className).toMatch(/text-destructive/)    // a fall is red (the Badge's own "destructive" look)

    // the small line: 6 months drawn, hidden from screen readers, said in a sentence instead
    const line = month.querySelector('[data-slot="sparkline"]') as HTMLElement
    expect(line).toBeInTheDocument()
    expect(line.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
    expect(line.querySelector('polyline')?.getAttribute('points')?.split(' ')).toHaveLength(6)
    expect(within(line).getByText(/The last 6 NOP sales months: May 2026: INR 9 L, .*Oct 2026: INR 12 L\./)).toBeInTheDocument()
    expect(kpi('fy_sales').querySelector('[data-slot="sparkline"]')).toBeNull()      // trend null
    expect(kpi('customers').querySelector('[data-slot="sparkline"]')).toBeNull()     // only 1 month
    expect(kpi('products').querySelector('[data-slot="sparkline"]')).toBeNull()      // no trend at all
  })

  it('a KPI card with a question opens the Ask page with it filled in; one without is not a link', async () => {
    fakeFetch({ '/api/home': { body: HOME } })

    renderAt('/', <HomePage me={ME} />)

    await screen.findByText('2,063')
    const month = kpi('month_sales')
    expect(month.tagName).toBe('A')
    expect(month).toHaveAttribute('href', '/new?q=What%20were%20the%20net%20sales%20in%20Oct%202026%3F')
    expect(month).toHaveAccessibleName(/Net sales Oct 2026.*Ask AI about this\s?: What were the net sales in Oct 2026\?/)
    expect(kpi('products').tagName).toBe('DIV')       // no ask
    expect(kpi('open_orders').tagName).toBe('DIV')    // an empty ask

    fireEvent.click(kpi('customers'))
    expect(window.location.pathname + window.location.search).toBe('/new?q=How%20many%20customers%20bought%20in%20FY%202026-27%3F')
  })

  it('the KPI numbers count up and end with exactly the text from the server', async () => {
    const motion = controlledMotion()
    try {
      fakeFetch({ '/api/home': { body: HOME } })

      renderAt('/', <HomePage me={ME} />)

      await screen.findByText('Net sales Oct 2026')
      expect(valueOf('month_sales')).toHaveTextContent('INR 0 L')          // the count starts at 0, in the final's unit
      expect(valueOf('month_sales')).toHaveAttribute('aria-hidden', 'true') // screen readers get the final number
      expect(within(kpi('month_sales')).getByText('INR 12 L')).toHaveClass('sr-only')
      motion.frame(1000)
      motion.frame(1350)
      expect(valueOf('customers').textContent).not.toBe('2,063')            // half way
      motion.frame(1800)
      expect(valueOf('month_sales').textContent).toBe('INR 12 L')
      expect(valueOf('customers').textContent).toBe('2,063')
      expect(valueOf('fy_sales').textContent).toBe('INR 436 Cr')
      expect(valueOf('stock').textContent).toBe('INR 2.4 Cr')
      expect(valueOf('top_customer').textContent).toBe('INR 6.4 Cr')
      expect(valueOf('customers')).not.toHaveAttribute('aria-hidden')
      expect(within(kpi('customers')).queryByText('2,063', { selector: '.sr-only' })).toBeNull()
    } finally {
      motion.restore()
    }
  })

  it('less motion asked for (or a browser that cannot say): the exact numbers at once', async () => {
    window.matchMedia = ((query: string) => ({ matches: query.includes('reduce') })) as unknown as typeof window.matchMedia
    try {
      fakeFetch({ '/api/home': { body: HOME } })

      renderAt('/', <HomePage me={ME} />)

      await screen.findByText('Net sales Oct 2026')
      expect(valueOf('month_sales').textContent).toBe('INR 12 L')
      expect(valueOf('customers').textContent).toBe('2,063')
    } finally {
      delete (window as Partial<Window>).matchMedia
    }
  })

  it('8 KPI cards: 4 a row on a wide screen (2 on a tablet, 1 on a phone); 6 tables: 3 a row', async () => {
    fakeFetch({ '/api/home': { body: { ...HOME, tables: SIX_TABLES } } })

    renderAt('/', <HomePage me={ME} />)

    await screen.findByText('2,063')
    const kpis = grid('kpis')
    expect(kpis).toHaveAttribute('data-columns', '4')
    expect(kpis).toHaveClass('grid', '@min-[440px]:grid-cols-2', '@min-[900px]:grid-cols-4')
    expect(kpis.className).not.toContain('grid-cols-3')
    expect(kpis.className).not.toContain('auto-fill')
    expect(kpis.parentElement).toHaveClass('@container')        // the grid measures its own room, not the window
    const tables = grid('tables')
    expect(tables).toHaveAttribute('data-columns', '3')
    expect(tables).toHaveClass('@min-[440px]:grid-cols-2', '@min-[720px]:grid-cols-3')
    expect(document.querySelectorAll('[data-table]')).toHaveLength(6)
    const connections = grid('connections')                    // 3 connections: 3 a row
    expect(connections).toHaveAttribute('data-columns', '3')
    expect(connections).toHaveAccessibleName('Connections')
  })

  it('6 KPI cards (an older server): 3 a row on a wide screen', async () => {
    fakeFetch({ '/api/home': { body: { ...HOME, kpis: HOME.kpis.slice(0, 6) } } })

    renderAt('/', <HomePage me={ME} />)

    await screen.findByText('2,063')
    expect(grid('kpis')).toHaveAttribute('data-columns', '3')
    expect(grid('kpis')).toHaveClass('@min-[720px]:grid-cols-3')
    expect(grid('kpis').className).not.toContain('grid-cols-4')
  })

  it('5 connections: all 5 in a row on a wide screen, 3 + 2 in between', async () => {
    const five = ['ai_gold', 'app_db', 'docs', 'pdfs', 'groq'].map((key) => ({ ...HOME.connections[0], key, name: key }))
    fakeFetch({ '/api/home': { body: { ...HOME, connections: five } } })

    renderAt('/', <HomePage me={ME} />)

    await screen.findByText('2,063')
    const connections = grid('connections')
    expect(within(connections).getAllByRole('listitem')).toHaveLength(5)
    expect(connections).toHaveAttribute('data-columns', '5')
    expect(connections).toHaveClass('@min-[1100px]:grid-cols-5', '@min-[720px]:grid-cols-6')
  })

  it('shows the Ask AI and Knowledge graph feature cards above the key numbers', async () => {
    fakeFetch({ '/api/home': { body: HOME } })

    renderAt('/', <HomePage me={ME} />)

    const numbers = await screen.findByRole('region', { name: 'Key numbers' })
    const features = screen.getByRole('region', { name: 'Ask AI and the Knowledge graph' })
    expect(features.compareDocumentPosition(numbers) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(within(features).getByRole('link', { name: 'Open Ask AI' })).toHaveAttribute('href', '/ask')
    expect(within(features).getByRole('link', { name: 'Open Knowledge graph' })).toHaveAttribute('href', '/graph')
  })

  it('chooses the columns from the number of cards, so the last row is never half empty', () => {
    expect(wideColumns(8, 4)).toBe(4)
    expect(wideColumns(6, 4)).toBe(3)
    expect(wideColumns(4, 4)).toBe(4)
    expect(wideColumns(7, 4)).toBe(4)     // 4 + 3
    expect(wideColumns(5, 4)).toBe(3)     // 3 + 2
    expect(wideColumns(6, 3)).toBe(3)
    expect(wideColumns(4, 3)).toBe(2)     // 2 + 2
    expect(wideColumns(5, 5)).toBe(5)
    expect(wideColumns(2, 4)).toBe(2)
    expect(wideColumns(1, 4)).toBe(1)
    expect(wideColumns(0, 4)).toBe(1)
    expect(gridClass(1, 4)).toBe('grid')                                             // one card: the whole width
    expect(gridClass(7, 4)).toContain('@min-[440px]:[&>*:last-child]:col-span-2')   // at 2 columns the 7th takes the row
    expect(gridClass(8, 4)).not.toContain('last-child')
  })

  it('cards without a small line show their facts as chips; none when there are no facts', async () => {
    fakeFetch({ '/api/home': { body: HOME } })

    renderAt('/', <HomePage me={ME} />)

    await screen.findByText('2,063')
    const orders = kpi('open_orders').querySelector('[data-slot="kpi-facts"]') as HTMLElement
    expect(within(orders).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['10 orders', '14 lines', 'INR 60.6 L incl. GST'])
    expect(within(orders).getByText('10 orders')).toHaveAttribute('data-slot', 'badge')
    const stock = kpi('stock').querySelector('[data-slot="kpi-facts"]') as HTMLElement
    expect(within(stock).getAllByRole('listitem')).toHaveLength(2)
    expect(kpi('stock')).toHaveAccessibleName(/52 items.*Report 20-Sep-2026/)            // read out with the card
    expect(kpi('top_product').querySelector('[data-slot="kpi-facts"]')).toBeNull()      // facts null
    expect(kpi('products').querySelector('[data-slot="kpi-facts"]')).toBeNull()         // no facts at all
    expect(kpi('month_sales').querySelector('[data-slot="kpi-facts"]')).toBeNull()      // has the small line instead
    // every card fills its row's height, with the note and the link at the bottom, so the bottoms line up
    for (const card of document.querySelectorAll('[data-kpi]')) {
      expect(card).toHaveClass('h-full', 'flex', 'flex-col')
    }
  })

  it('the KPI label is never cut: it wraps, next to the icon', async () => {
    fakeFetch({ '/api/home': { body: HOME } })

    renderAt('/', <HomePage me={ME} />)

    await screen.findByText('2,063')
    const label = kpi('fy_sales').querySelector('[data-slot="kpi-label"]') as HTMLElement
    expect(label).toHaveTextContent('Net sales FY 2026-27 so far')
    expect(label.className).not.toContain('truncate')
    expect(label.className).not.toContain('line-clamp')
    expect(label.className).not.toContain('whitespace-nowrap')
    expect(label.parentElement).toHaveClass('items-start')
  })

  it('the top customer and top product cards: the name, the counting amount, the facts and the Ask link', async () => {
    fakeFetch({ '/api/home': { body: HOME } })

    renderAt('/', <HomePage me={ME} />)

    await screen.findByText('2,063')
    const top = kpi('top_customer')
    expect(within(top).getByText('Top customer Oct 2026')).toBeInTheDocument()
    const name = top.querySelector('[data-slot="kpi-name"]') as HTMLElement
    expect(name).toHaveTextContent('Allied Castings Limited')
    expect(name).toHaveAttribute('title', 'Allied Castings Limited')
    expect(name).toHaveClass('truncate', 'font-semibold')
    expect(valueOf('top_customer')).toHaveTextContent('INR 6.4 Cr')
    expect(within(top).getByText('INR 63,648,019.00')).toBeInTheDocument()
    expect(within(top).getByText('2.7% of Oct 2026 sales')).toHaveAttribute('data-slot', 'badge')
    expect(top.tagName).toBe('A')
    expect(top).toHaveAttribute('href', '/new?q=Top%20customers%20by%20net%20sales%20in%20Oct%202026%3F')
    expect(top.querySelector('svg.lucide-crown')).toBeInTheDocument()

    const product = kpi('top_product')
    expect(product.querySelector('[data-slot="kpi-name"]')).toHaveAttribute('title', 'Brake drum BD-220 heavy duty, machined')
    expect(valueOf('top_product')).toHaveTextContent('INR 1.2 Cr')
    expect(within(product).getByText(/Ask AI about this/)).toBeInTheDocument()
    expect(product.querySelector('svg.lucide-award')).toBeInTheDocument()
  })

  it('a top card with no sales: a dash, no name, no full amount', async () => {
    const none = { ...HOME.kpis[6], name: '', value: 0, text: '-', facts: null }
    fakeFetch({ '/api/home': { body: { ...HOME, kpis: [...HOME.kpis.slice(0, 6), none, HOME.kpis[7]] } } })

    renderAt('/', <HomePage me={ME} />)

    await screen.findByText('2,063')
    expect(valueOf('top_customer').textContent).toBe('-')
    expect(kpi('top_customer').querySelector('[data-slot="kpi-name"]')).toBeNull()
    expect(within(kpi('top_customer')).queryByText(/^INR/)).toBeNull()
  })

  it('shows the usage: questions, tokens short and in full, the bar', async () => {
    fakeFetch({ '/api/home': { body: HOME } })

    renderAt('/', <HomePage me={ME} />)

    const usage = await screen.findByRole('region', { name: 'Your usage' })
    expect(within(usage).getByText('9')).toBeInTheDocument()
    expect(within(usage).getByText('90,403')).toBeInTheDocument()
    expect(usage).toHaveTextContent('143k of 200k tokens')
    expect(within(usage).getByText(/143,064 of 200,000 tokens · openai\/gpt-oss-120b/)).toBeInTheDocument()
    expect(within(usage).getByText('72%')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '72')     // the only progress bar for screen readers
  })

  it.each([[50, 'bg-success'], [75, 'bg-warning'], [95, 'bg-destructive']])('the usage bar at %i%% is %s', async (pct, colour) => {
    fakeFetch({ '/api/home': { body: { ...HOME, usage: { ...HOME.usage, pct } } } })

    renderAt('/', <HomePage me={ME} />)

    const bar = await screen.findByRole('progressbar', { name: 'AI tokens of the daily limit' })
    const fill = bar.querySelector('[data-slot="progress-indicator"]') as HTMLElement
    expect(fill).toHaveClass(colour)
    expect(fill.style.width).toBe(`${pct}%`)
  })

  it('shows the recent questions with their status; a click opens the saved answer', async () => {
    fakeFetch({ '/api/home': { body: HOME } })

    renderAt('/', <HomePage me={ME} />)

    const list = await screen.findByRole('list', { name: 'Your recent questions' })
    const rows = within(list).getAllByRole('link')
    expect(rows).toHaveLength(5)
    expect(rows[0]).toHaveAttribute('href', '/q/41')
    expect(rows[0]).toHaveTextContent('Top 5 customers by invoice value in Oct 2026?')
    expect(rows[0]).toHaveTextContent('05-Nov 2:04 PM')
    expect(rows.map((row) => within(row).getByText(/./, { selector: '[data-slot="badge"]' }).textContent))
      .toEqual(['Answered', 'From documents', 'No data', 'Refused', 'Failed'])
    expect(screen.getByRole('link', { name: 'See all in History' })).toHaveAttribute('href', '/history')

    fireEvent.click(rows[1])
    expect(window.location.pathname).toBe('/q/40')
  })

  it('no questions yet: a friendly line with the example questions', async () => {
    fakeFetch({ '/api/home': { body: { ...HOME, recent: [] } } })

    renderAt('/', <HomePage me={ME} />)

    expect(await screen.findByText('No questions yet - try one of these')).toBeInTheDocument()
    const examples = screen.getByRole('list', { name: 'Example questions' })
    expect(within(examples).getAllByRole('link')).toHaveLength(3)
    expect(within(examples).getByRole('link', { name: 'Stock value?' })).toHaveAttribute('href', '/new?q=Stock%20value%3F')
  })

  it('recent questions that cannot be read: a small message, the rest works', async () => {
    fakeFetch({ '/api/home': { body: { ...HOME, recent: [], recent_error: 'The app database is busy.' } } })

    renderAt('/', <HomePage me={ME} />)

    expect(await screen.findByText(/Your recent questions can't be read right now. The app database is busy./)).toBeInTheDocument()
    expect(screen.getByText('90,403')).toBeInTheDocument()
  })

  it('shows the connections, each with a green (pulsing) or red dot', async () => {
    fakeFetch({ '/api/home': { body: HOME } })

    renderAt('/', <HomePage me={ME} />)

    await screen.findByText('2,063')
    expect(within(screen.getByRole('list', { name: 'Connections' })).getAllByRole('listitem')).toHaveLength(3)
    const gold = document.querySelector('[data-connection="ai_gold"]') as HTMLElement
    expect(gold).toHaveTextContent('Connected: Reachable')
    expect(gold.querySelector('[data-dot]')).toHaveAttribute('data-dot', 'ok')
    expect(gold.querySelector('.animate-ping')).toBeInTheDocument()
    const docs = document.querySelector('[data-connection="docs"]') as HTMLElement
    expect(within(docs).getByText('Not connected:')).toBeInTheDocument()
    expect(within(docs).getByText('Not reachable right now')).toBeInTheDocument()
    // down is real red (destructive), not the blue brand
    expect(docs.querySelector('[data-dot="down"] .bg-destructive')).toBeInTheDocument()
    expect(within(docs).getByText('Not reachable right now')).toHaveClass('text-destructive')
    expect(docs.querySelector('[data-dot]')).toHaveAttribute('data-dot', 'down')
    expect(docs.querySelector('.animate-ping')).toBeNull()
  })

  it('shows the tables with their records, dates, a bar against the biggest and the note on later dates', async () => {
    fakeFetch({ '/api/home': { body: HOME } })

    renderAt('/', <HomePage me={ME} />)

    await screen.findByText('2,063')
    const invoices = document.querySelector('[data-table="fact_invoice_lines"]') as HTMLElement
    expect(within(invoices).getByText('100,720')).toBeInTheDocument()
    expect(within(invoices).getByText('21-Dec-2025 to 20-Mar-2027')).toBeInTheDocument()
    expect(within(invoices).getByText(/Has test rows dated after today/)).toBeInTheDocument()
    expect((invoices.querySelector('[data-slot="progress-indicator"]') as HTMLElement).style.width).toBe('100%')
    const customers = document.querySelector('[data-table="dim_customers"]') as HTMLElement
    expect(customers).not.toHaveTextContent('after today')
    expect(parseFloat((customers.querySelector('[data-slot="progress-indicator"]') as HTMLElement).style.width)).toBeCloseTo(4.97, 1)
  })

  it('shows how it works (6 steps with an explanation each) and what we use', async () => {
    fakeFetch({ '/api/home': { body: HOME } })

    renderAt('/', <HomePage me={ME} />)

    await screen.findByText('2,063')
    const flow = screen.getByRole('list', { name: 'How a question is answered' })
    const steps = within(flow).getAllByRole('listitem')
    expect(steps).toHaveLength(6)
    expect(within(flow).getByText('SQL guard')).toBeInTheDocument()
    for (const step of steps) {
      expect(step.getAttribute('title')).toBeTruthy()                                       // on hover
      expect(step.querySelector('.sr-only')?.textContent).toBe(step.getAttribute('title'))   // and for screen readers
    }
    const stack = screen.getByRole('list', { name: 'What we use' })
    for (const name of ['Django', 'React', 'LangChain', 'LangGraph', 'Qdrant', 'FastEmbed', 'Groq (openai/gpt-oss-120b)',
      'MCP server', 'ECharts', 'Tailwind + shadcn']) {
      expect(within(stack).getByText(name)).toBeInTheDocument()
    }
  })

  it('an older server (no trend, ask or recent): the cards are plain, no small lines, History is pointed to', async () => {
    fakeFetch({ '/api/home': { body: oldServer() } })

    renderAt('/', <HomePage me={ME} />)

    await screen.findByText('2,063')
    expect(document.querySelectorAll('[data-kpi]')).toHaveLength(6)
    expect(document.querySelectorAll('a[data-kpi]')).toHaveLength(0)
    expect(document.querySelectorAll('[data-slot="sparkline"]')).toHaveLength(0)
    expect(document.querySelectorAll('[data-slot="kpi-facts"], [data-slot="kpi-name"]')).toHaveLength(0)
    expect(grid('kpis')).toHaveAttribute('data-columns', '3')      // 6 cards: 3 a row, no gap
    expect(screen.queryAllByText(/Ask AI about this/)).toHaveLength(0)
    const recent = screen.getByRole('region', { name: 'Your recent questions' })
    expect(within(recent).getByRole('link', { name: 'History' })).toHaveAttribute('href', '/history')
    expect(screen.getByText('90,403')).toBeInTheDocument()
  })

  it('shows skeletons while it loads', () => {
    fakeFetch({ '/api/home': () => ({ body: HOME }) })

    renderAt('/', <HomePage me={ME} />)

    expect(document.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(6)
    expect(screen.getByText('How it works')).toBeInTheDocument()   // the parts without data are there at once
    expect(screen.getByRole('region', { name: 'Welcome' })).toBeInTheDocument()
  })

  it('MySQL down: only the data parts say so, the rest of the page works', async () => {
    const down = 'The company data (MySQL) can\'t be read right now - please try again in a minute.'
    fakeFetch({ '/api/home': { body: { ...HOME, calendar: null, kpis: [], kpi_error: down, tables: [], tables_error: down,
      connections: [{ ...HOME.connections[0], ok: false, note: 'Not reachable right now' }, HOME.connections[2]] } } })

    renderAt('/', <HomePage me={ME} />)

    expect(await screen.findByText(/The key numbers can't be read right now/)).toBeInTheDocument()
    expect(screen.getByText(/The tables can't be read right now/)).toBeInTheDocument()
    expect(document.querySelectorAll('[data-kpi]')).toHaveLength(0)
    expect(screen.queryByText(/NOP sales month/)).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /, Asha/ })).toBeInTheDocument()
    expect(screen.getByText('90,403')).toBeInTheDocument()                                    // the usage still shows
    expect(screen.getAllByRole('link', { name: /Top 5 customers by invoice value/ })).toHaveLength(1)   // and the recent questions
    expect(document.querySelector('[data-connection="ai_gold"]')).toHaveTextContent('Not connected: Not reachable right now')
    expect(screen.getByRole('region', { name: 'Welcome' })).toBeInTheDocument()
  })

  it('the whole call failing: a small message, the welcome and how it works still there', async () => {
    fakeFetch({ '/api/home': { status: 500, body: { detail: 'The server had a problem.' } } })

    renderAt('/', <HomePage me={ME} />)

    expect(await screen.findByText('The server had a problem.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /, Asha/ })).toBeInTheDocument()             // the name from /api/me
    expect(screen.getByRole('list', { name: 'How a question is answered' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Welcome' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Top 5 customers?' })).toBeInTheDocument()       // the quick start
    expect(screen.queryByText('Key numbers')).not.toBeInTheDocument()
  })

  it('says good morning, afternoon or evening by the hour', () => {
    expect(greeting(6)).toBe('Good morning')
    expect(greeting(11)).toBe('Good morning')
    expect(greeting(12)).toBe('Good afternoon')
    expect(greeting(16)).toBe('Good afternoon')
    expect(greeting(17)).toBe('Good evening')
    expect(greeting(23)).toBe('Good evening')
  })

  it('writes token counts short and picks the bar colour', () => {
    expect(shortTokens('143,064')).toBe('143k')
    expect(shortTokens('200,000')).toBe('200k')
    expect(shortTokens('1,500')).toBe('1.5k')
    expect(shortTokens('1,250,000')).toBe('1.3M')
    expect(shortTokens('950')).toBe('950')
    expect(shortTokens('-')).toBe('-')
    expect(usageColour(70)).toBe('bg-success')
    expect(usageColour(71)).toBe('bg-warning')
    expect(usageColour(90)).toBe('bg-warning')
    expect(usageColour(91)).toBe('bg-destructive')
  })
})

describe('Badge and Progress', () => {
  it('a badge takes its variant colours', () => {
    render(<><Badge variant="success">Answered</Badge><Badge variant="destructive">Failed</Badge><Badge>New</Badge></>)
    expect(screen.getByText('Answered')).toHaveClass('bg-success-soft', 'text-success')
    expect(screen.getByText('Failed').className).toMatch(/text-destructive/)
    expect(screen.getByText('New')).toHaveClass('bg-primary')
  })

  it('a progress bar says its value and keeps it between 0 and 100', () => {
    render(<><Progress value={42.4} aria-label="a" /><Progress value={140} aria-label="b" /><Progress value={-5} aria-label="c" /></>)
    expect(screen.getByRole('progressbar', { name: 'a' })).toHaveAttribute('aria-valuenow', '42')
    expect(screen.getByRole('progressbar', { name: 'a' })).toHaveAttribute('aria-valuemax', '100')
    expect(screen.getByRole('progressbar', { name: 'b' })).toHaveAttribute('aria-valuenow', '100')
    expect(screen.getByRole('progressbar', { name: 'c' })).toHaveAttribute('aria-valuenow', '0')
  })
})

const SOURCES: [string, string][] = [['HomePage.tsx', pageSource]]

describe('Home page colours (light and dark)', () => {
  it.each(SOURCES)('%s has no bg-white and no fixed #hex text colour', (_name, source) => {
    expect(source).not.toMatch(/\bbg-white(?![/\w-])/)       // bg-white/15 (glass on the blue banner / card) is fine
    expect(source).not.toMatch(/\btext-\[#/)
    expect(source).not.toMatch(/var\(--(red2?|red-bg|charcoal|purple|purple-bg)\)/)   // the old brand variables
    expect(source).not.toContain('danger-soft')              // red is only for errors now: destructive
  })
})
