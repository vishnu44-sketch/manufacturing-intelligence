// The KPI cards of the Home page, each with its own look: the blue main card (month_sales), the teal filled area
// (fy_sales), the green ring of active of all customers (customers, only with "total"), the amber bars
// (products), the violet / slate cards with chips and a faint icon (open_orders, stock), and the top customer /
// product with a round avatar and a small tag. Every card still counts up to exactly the server's text and opens
// the Ask page with its question; an older server's card (no trend, facts, total or name) falls back to the plain look.
import { act, fireEvent, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderAt } from '../test/render'
import cardsSource from './HomeKpiCards.tsx?raw'
import { initials, KpiCard, type KpiData, share, shareText } from './HomeKpiCards'

const TREND = [
  { label: 'May 2026', value: 900000 }, { label: 'Jun 2026', value: 1100000 }, { label: 'Jul 2026', value: 950000 },
  { label: 'Aug 2026', value: 1300000 }, { label: 'Sep 2026', value: 1000000 }, { label: 'Oct 2026', value: 1200000 },
]
const COUNTS = TREND.map((p, i) => ({ label: p.label, value: [410, 380, 0, 455, 402, 433][i] }))

const KPIS: KpiData[] = [
  { key: 'month_sales', label: 'Net sales Oct 2026', money: true, value: 1200000, text: 'INR 1,200,000.00',
    note: '21-Sep-2026 to 20-Oct-2026 (last complete NOP sales month)', change: { pct: 20, direction: 'up', text: '20.0% vs Sep 2026' },
    trend: TREND, ask: 'Net sales of the last 6 NOP months as a line chart', facts: null },
  { key: 'fy_sales', label: 'Net sales FY 2026-27 so far', money: true, value: 4360522752.5, text: 'INR 4,360,522,752.50',
    note: '01-Apr-2026 to 05-Nov-2026', change: null,
    trend: [{ label: 'Apr 2026', value: 300000000 }, { label: 'May 2026', value: 900000000 }, { label: 'Jun 2026', value: 1500000000 }],
    ask: 'Net sales by NOP month of FY 2026-27 so far as a line chart', facts: null },
  { key: 'customers', label: 'Active customers', money: false, value: 2090, text: '2,090', total: 5000,
    note: 'of 5,000 customers bought in FY 2026-27 so far', change: { pct: -12.5, direction: 'down', text: '12.5% vs the same dates of FY 2025-26' },
    trend: COUNTS, ask: 'Active customers in each of the last 6 NOP months', facts: null },
  { key: 'products', label: 'Products sold', money: false, value: 3811, text: '3,811', note: 'different products invoiced',
    change: null, trend: COUNTS, ask: 'Number of products sold in each of the last 6 NOP months', facts: null },
  { key: 'open_orders', label: 'Open sales orders', money: true, value: 5335415, text: 'INR 5,335,415.00',
    note: '10 orders (14 lines) before GST, as of 05-Nov-2026', change: null, trend: null,
    ask: 'List the open sales orders up to today', facts: ['10 orders', '14 lines', 'INR 60.6 L incl. GST'] },
  { key: 'stock', label: 'Stock value', money: true, value: 23856971.91, text: 'INR 23,856,971.91',
    note: 'Stock report of 20-Sep-2026 (52 items)', change: null, trend: null,
    ask: 'Stock value by item group on the latest stock report', facts: ['52 items', 'Report 20-Sep-2026'] },
  { key: 'top_customer', label: 'Top customer Oct 2026', name: 'Allied Castings Limited', money: true, value: 32400,
    text: 'INR 32,400.00', note: '21-Sep-2026 to 20-Oct-2026 (last complete NOP sales month)', change: null, trend: null,
    ask: 'Top 10 customers of the last NOP month by net sales', facts: ['2.7% of Oct 2026 sales'] },
  { key: 'top_product', label: 'Top product Oct 2026', name: 'Coolant pump HM-445-1B', money: true, value: 18000,
    text: 'INR 18,000.00', note: '21-Sep-2026 to 20-Oct-2026 (last complete NOP sales month)', change: null, trend: null,
    ask: 'Top 10 products of the last NOP month by net sales', facts: ['1.5% of Oct 2026 sales'] },
]
const byKey = (key: string) => KPIS.find((k) => k.key === key) as KpiData

const card = (key: string) => document.querySelector(`[data-kpi="${key}"]`) as HTMLElement
const valueOf = (key: string) => card(key).querySelector('[data-slot="kpi-value"]') as HTMLElement

function showAll(kpis: KpiData[] = KPIS) {
  return renderAt('/', <div className="ui-scope">{kpis.map((kpi) => <KpiCard key={kpi.key} kpi={kpi} />)}</div>)
}

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

describe('HomeKpiCards', () => {
  it('month_sales is the blue main card: gradient, white text, a white small line and a glass change badge', () => {
    showAll()
    const hero = card('month_sales')
    expect(hero).toHaveAttribute('data-look', 'month_sales')
    expect(hero.className).toContain('bg-[linear-gradient(')
    expect(hero.className).toContain('#0B5FB3')                       // the blue brand, not the old red
    expect(hero.className).not.toContain('var(--red)')
    expect(hero).toHaveClass('text-white!')
    const line = hero.querySelector('[data-slot="sparkline"]') as HTMLElement
    expect(line).toHaveClass('text-white')
    expect(line.querySelector('polyline')?.getAttribute('points')?.split(' ')).toHaveLength(6)
    const change = hero.querySelector('[data-change]') as HTMLElement
    expect(change).toHaveClass('bg-white/15', 'text-white')
    expect(change).toHaveTextContent('▲Up 20.0% vs Sep 2026')
    // only the main card has the gradient
    for (const key of ['fy_sales', 'customers', 'products', 'open_orders', 'stock', 'top_customer', 'top_product']) {
      expect(card(key).className).not.toContain('linear-gradient')
    }
  })

  it('fy_sales has a teal stripe (not the main card\'s blue) and a filled area of the running total', () => {
    showAll()
    const fy = card('fy_sales')
    expect(fy.querySelector('span.bg-teal-600.h-1')).toBeInTheDocument()
    const area = fy.querySelector('[data-slot="kpi-area"]') as HTMLElement
    expect(area).toHaveClass('text-teal-600', 'dark:text-teal-400')
    const path = area.querySelector('path[data-slot="area"]') as SVGPathElement
    expect(path.getAttribute('d')).toMatch(/^M0,44 L.* Z$/)            // closed down to the bottom: a filled area
    expect(path.getAttribute('fill')).toMatch(/^url\(#kpi-area-/)
    expect(area.querySelector(`linearGradient#${path.getAttribute('fill')!.slice(5, -1)}`)).toBeInTheDocument()
    expect(within(area).getByText(/The FY running total at the end of the last 3 NOP sales months: Apr 2026: INR 30 Cr/)).toHaveClass('sr-only')
    expect(fy.querySelector('[data-slot="sparkline"]')).toBeNull()
  })

  it('customers with a total: a green ring with the share in the middle', () => {
    showAll()
    const customers = card('customers')
    const ring = customers.querySelector('[data-slot="kpi-ring"]') as HTMLElement
    expect(ring).toHaveClass('text-success')
    expect(within(ring).getByText('42%')).toHaveAttribute('aria-hidden', 'true')     // 2,090 of 5,000
    expect(within(ring).getByText('2,090 of 5,000 customers (42%)')).toHaveClass('sr-only')
    expect(ring.querySelector('[data-slot="ring-fill"]')?.getAttribute('stroke-dasharray')).toMatch(/^68\.2\d 163\.36$/)  // 41.8% of the ring
    expect(customers.querySelector('[data-slot="sparkline"]')).toBeNull()             // the ring instead of the line
    expect(customers.querySelector('[data-change="down"]')).toBeInTheDocument()
  })

  it('customers without a total (an older server): the plain card with its small line', () => {
    const { total: _total, ...old } = byKey('customers')
    showAll([old])
    const customers = card('customers')
    expect(customers.querySelector('[data-slot="kpi-ring"]')).toBeNull()
    expect(customers.querySelector('[data-slot="sparkline"]')).toBeInTheDocument()
    expect(customers).toHaveAttribute('data-look', 'customers')                       // still green
  })

  it('a card this page does not know: the plain look', () => {
    showAll([{ ...byKey('customers'), key: 'returns', total: 0 }])
    expect(card('returns')).toHaveAttribute('data-look', 'plain')
    expect(card('returns').querySelector('[data-slot="sparkline"]')).toBeInTheDocument()
  })

  it('products: amber bars, one per month, the newest one strong', () => {
    showAll()
    const bars = card('products').querySelector('[data-slot="kpi-bars"]') as HTMLElement
    expect(bars).toHaveClass('text-warning')
    const rects = bars.querySelectorAll('rect')
    expect(rects).toHaveLength(6)
    expect(rects[5]).toHaveAttribute('data-last', 'true')
    expect(rects[5]).toHaveAttribute('opacity', '1')
    expect(rects[0]).toHaveAttribute('opacity', '0.3')
    expect(Number(rects[2].getAttribute('height'))).toBeGreaterThan(0)             // a month with none: a thin stub
    expect(within(bars).getByText('May 2026')).toBeInTheDocument()
    expect(within(bars).getByText(/The last 6 NOP sales months: May 2026: 410, .*Oct 2026: 433\./)).toHaveClass('sr-only')
  })

  it('products with fewer than 2 months: no bars and no line', () => {
    showAll([{ ...byKey('products'), trend: [{ label: 'Oct 2026', value: 9 }] }])
    expect(card('products').querySelector('[data-slot="kpi-bars"], [data-slot="sparkline"]')).toBeNull()
    expect(card('products')).toHaveAttribute('data-look', 'products')
  })

  it('open orders and stock: tinted cards with the facts as chips and a faint icon behind', () => {
    showAll()
    const orders = card('open_orders')
    expect(orders).toHaveClass('bg-violet-50', 'dark:bg-violet-400/10')   // a soft tint in light, see-through in dark
    expect(orders).toHaveClass('isolate')
    const chips = orders.querySelector('[data-slot="kpi-facts"]') as HTMLElement
    expect(within(chips).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['10 orders', '14 lines', 'INR 60.6 L incl. GST'])
    expect(within(chips).getByText('14 lines')).toHaveAttribute('data-slot', 'badge')
    const mark = orders.querySelector('svg.lucide-clipboard-list.-z-10') as SVGElement
    expect(mark).toHaveAttribute('aria-hidden', 'true')
    const stock = card('stock')
    expect(stock).toHaveClass('bg-slate-100', 'dark:bg-slate-400/10')
    expect(stock.querySelector('svg.lucide-warehouse.-z-10')).toBeInTheDocument()
    expect(within(stock.querySelector('[data-slot="kpi-facts"]') as HTMLElement).getAllByRole('listitem')).toHaveLength(2)
    expect(stock).toHaveAccessibleName(/52 items.*Report 20-Sep-2026/)
  })

  it('the top customer: a green avatar with the initials, a "No. 1" tag, the name, the amount and the share chip', () => {
    showAll()
    const top = card('top_customer')
    const avatar = top.querySelector('[data-slot="kpi-avatar"]') as HTMLElement
    expect(avatar).toHaveTextContent(/^AC$/)
    expect(avatar).toHaveClass('rounded-full', 'bg-success-soft', 'text-success')
    expect(avatar).toHaveAttribute('aria-hidden', 'true')
    expect(top.querySelector('svg.lucide-crown')).toBeInTheDocument()
    expect(top.querySelector('[data-slot="kpi-tag"]')).toHaveTextContent('🏆No. 1')
    expect(top.querySelector('[data-slot="kpi-name"]')).toHaveAttribute('title', 'Allied Castings Limited')
    expect(valueOf('top_customer')).toHaveTextContent('INR 32.4 K')
    expect(within(top).getByText('INR 32,400.00')).toBeInTheDocument()
    expect(within(top).getByText('2.7% of Oct 2026 sales')).toHaveAttribute('data-slot', 'badge')

    const product = card('top_product')
    const box = product.querySelector('[data-slot="kpi-avatar"]') as HTMLElement
    expect(box).toHaveClass('bg-warning-soft')
    expect(box.querySelector('svg.lucide-award')).toBeInTheDocument()
    expect(product.querySelector('[data-slot="kpi-tag"]')).toHaveTextContent('⭐Top product')
    expect(product.querySelector('[data-slot="kpi-name"]')).toHaveTextContent('Coolant pump HM-445-1B')
  })

  it('a top card with no sales: no tag, no name, the icon in the avatar', () => {
    showAll([{ ...byKey('top_customer'), name: '', value: 0, text: '-', facts: null }])
    const top = card('top_customer')
    expect(top.querySelector('[data-slot="kpi-tag"]')).toBeNull()
    expect(top.querySelector('[data-slot="kpi-name"]')).toBeNull()
    expect(top.querySelector('[data-slot="kpi-avatar"] svg.lucide-crown')).toBeInTheDocument()
    expect(valueOf('top_customer').textContent).toBe('-')
  })

  it('every card opens the Ask page with its question, fills its row and keeps the hover lift and focus ring', () => {
    showAll()
    for (const kpi of KPIS) {
      const el = card(kpi.key)
      expect(el.tagName).toBe('A')
      expect(el).toHaveAttribute('href', `/new?q=${encodeURIComponent(kpi.ask!)}`)
      expect(el).toHaveClass('h-full', 'flex', 'flex-col', 'hover:-translate-y-0.5', 'focus-visible:ring-3')
      expect(el).toHaveAccessibleName(new RegExp(`Ask the Assistant about this\\s?: ${kpi.ask!.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`))
    }
    fireEvent.click(card('stock'))
    expect(window.location.pathname + window.location.search).toBe('/new?q=Stock%20value%20by%20item%20group%20on%20the%20latest%20stock%20report')
  })

  it('a card without a question is not a link', () => {
    showAll([{ ...byKey('open_orders'), ask: '' }])
    expect(card('open_orders').tagName).toBe('DIV')
    expect(card('open_orders')).toHaveClass('h-full')
  })

  it('an older server (no trend, facts, total or name): every card still shows, plainly', () => {
    showAll(KPIS.map(({ trend: _t, facts: _f, total: _n, name: _m, ask: _a, ...kpi }) => kpi))
    expect(document.querySelectorAll('[data-kpi]')).toHaveLength(8)
    expect(document.querySelectorAll('[data-slot="sparkline"], [data-slot="kpi-area"], [data-slot="kpi-bars"], [data-slot="kpi-ring"]')).toHaveLength(0)
    expect(document.querySelectorAll('[data-slot="kpi-facts"], [data-slot="kpi-name"], [data-slot="kpi-tag"]')).toHaveLength(0)
    expect(card('month_sales').className).toContain('linear-gradient')               // the look stays, only the parts go
    expect(screen.getByText('INR 12 L')).toBeInTheDocument()
  })

  it('the numbers count up and end with exactly the text from the server', () => {
    const motion = controlledMotion()
    try {
      showAll()
      expect(valueOf('month_sales')).toHaveTextContent('INR 0 L')
      expect(valueOf('customers')).toHaveAttribute('aria-hidden', 'true')
      motion.frame(1000)
      motion.frame(1350)
      expect(valueOf('customers').textContent).not.toBe('2,090')
      motion.frame(1800)
      expect(valueOf('month_sales').textContent).toBe('INR 12 L')
      expect(valueOf('fy_sales').textContent).toBe('INR 436 Cr')
      expect(valueOf('customers').textContent).toBe('2,090')
      expect(valueOf('products').textContent).toBe('3,811')
      expect(valueOf('open_orders').textContent).toBe('INR 53.4 L')
      expect(valueOf('stock').textContent).toBe('INR 2.4 Cr')
      expect(valueOf('top_customer').textContent).toBe('INR 32.4 K')
      expect(valueOf('top_product').textContent).toBe('INR 18 K')
      expect(valueOf('customers')).not.toHaveAttribute('aria-hidden')
    } finally {
      motion.restore()
    }
  })

  it('initials and shares', () => {
    expect(initials('Allied Castings Limited')).toBe('AC')
    expect(initials('M/s. Sharma Traders Pvt Ltd')).toBe('ST')
    expect(initials('Siemens')).toBe('S')
    expect(initials('The Limited')).toBe('TL')       // only "nothing" words: use them anyway
    expect(share(2090, 5000)).toBeCloseTo(0.418)
    expect(share(9, 0)).toBe(0)
    expect(share(7000, 5000)).toBe(1)
    expect(shareText(0.418)).toBe('42%')
    expect(shareText(0.002)).toBe('<1%')
    expect(shareText(0)).toBe('0%')
  })
})

const SOURCES: [string, string][] = [['HomeKpiCards.tsx', cardsSource]]

describe('KPI card colours (light and dark)', () => {
  it.each(SOURCES)('%s has no bg-white and no fixed #hex text colour', (_name, source) => {
    expect(source).not.toMatch(/\bbg-white(?![/\w-])/)       // bg-white/15 (glass on the blue banner / card) is fine
    expect(source).not.toMatch(/\btext-\[#/)
    expect(source).not.toMatch(/var\(--(red2?|red-bg|charcoal|purple|purple-bg)\)/)   // the old brand variables
    expect(source).not.toContain('danger-soft')              // red is only for errors now: destructive
  })
})
