// Knowledge graph: a search hit draws its neighbourhood (ECharts is a fake - jsdom has no canvas - so the tests
// check the option it gets), a click fills the side panel, a double-click merges the node's neighbours in, Similar
// customers, the FY filter asks again, Reset, the 150-node cap, the option itself, and friendly errors.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { readColours } from '../charts/chartOption'
import { buildGraphOption, edgeWidth, MAX_SIZE, MIN_SIZE, nodeSize } from '../charts/graphOption'
import { parseRoute } from '../router'
import { charts, lastChart } from '../test/fakeEcharts'
import { fakeFetch } from '../test/fakeFetch'
import { ASHA, renderAt } from '../test/render'
import type { GraphEdge, GraphNode, GraphNodeReply, GraphSimilarReply } from '../types'
import GraphPage, { AT_MAX, MAX_HITS, SEARCH_HINT } from './GraphPage'
import { EMPTY_GRAPH, mergeGraph } from './graphData'

vi.mock('../charts/echarts', () => import('../test/fakeEcharts'))
vi.mock('../charts/echartsGraph', () => ({}))

afterEach(() => { charts.length = 0 })

function node(type: GraphNode['type'], key: string, label: string, amount: number | null, extra: Partial<GraphNode> = {}): GraphNode {
  const names = { customer: 'Customer', product: 'Product', category: 'Category', sales_person: 'Sales person',
    state: 'State / country', sale_type: 'Sale type', document: 'Document' }
  return { id: `${type}:${key}`, type, type_name: names[type], key, label, sub: '', amount,
    amount_text: amount === null ? '' : amount.toLocaleString('en-IN', { minimumFractionDigits: 2 }), ...extra }
}

function edge(source: string, target: string, type: string, amount?: number): GraphEdge {
  return { id: `${source}|${type}|${target}`, source, target, type,
    ...(amount === undefined ? {} : { amount, amount_text: amount.toLocaleString('en-IN', { minimumFractionDigits: 2 }) }) }
}

const PERIOD = { fy: '', label: 'All data up to today', from: '21-Dec-2025', to: '04-Nov-2026', so_far: true,
  text: 'All data up to today (21-Dec-2025 to 04-Nov-2026)' }
const PERIOD_2526 = { fy: '2526', label: 'FY 2025-26', from: '01-Apr-2025', to: '31-Mar-2026', so_far: false,
  text: 'FY 2025-26 (01-Apr-2025 to 31-Mar-2026)' }

const AURORA = node('customer', '3680', 'Aurora Hydraulics Private Limited', 29088275, {
  sub: 'Chennai, Tamil Nadu · Local Customer', quantity_text: '812', invoices_text: '61', data_from: '03-Apr-2026',
  data_to: '02-Nov-2026', ask: 'Top products bought by Aurora Hydraulics Private Limited',
})
const MOTOR = node('product', '45', 'Hydraulic motor HM-346-1B', 9000000, { sub: 'FG00045 · Hydraulic motors' })
const PRIYA = node('sales_person', '4', 'Priya Iyer', 180984185.5)
const TAMIL = node('state', 'Tamil Nadu', 'Tamil Nadu', 468912301.5)

const AURORA_REPLY: GraphNodeReply = {
  node: AURORA, period: PERIOD,
  neighbours: [MOTOR, PRIYA, TAMIL],
  edges: [edge(AURORA.id, MOTOR.id, 'BOUGHT', 1250000), edge(AURORA.id, PRIYA.id, 'HANDLED_BY', 29000000),
    edge(AURORA.id, TAMIL.id, 'IN_STATE', 29088275)],
  groups: [{ edge: 'BOUGHT', type: 'product', shown: 1, total: 105 }, { edge: 'HANDLED_BY', type: 'sales_person', shown: 1, total: 1 },
    { edge: 'IN_STATE', type: 'state', shown: 1, total: 1 }],
  notes: ['Unknown product (service lines, or items not in the master): 7,125.00 is in the total but not drawn.'],
}
const HYDRAULIC = node('category', 'Hydraulic motors', 'Hydraulic motors', 621565971)
const CATALOGUE = node('document', 'product_catalogue.pdf#2', 'Product Catalogue, page 2', null, { sub: 'product_catalogue.pdf' })
const MOTOR_REPLY: GraphNodeReply = {
  node: { ...MOTOR, quantity_text: '10', invoices_text: '3', ask: 'Top customers of Hydraulic motor HM-346-1B' }, period: PERIOD,
  neighbours: [AURORA, HYDRAULIC, CATALOGUE],
  edges: [edge(AURORA.id, MOTOR.id, 'BOUGHT', 1250000), edge(MOTOR.id, HYDRAULIC.id, 'IN_CATEGORY', 9000000),
    { ...edge(MOTOR.id, CATALOGUE.id, 'COVERED_BY'), mentions: 8, through: 'Hydraulic motors' }],
  groups: [{ edge: 'BOUGHT', type: 'customer', shown: 1, total: 1 }, { edge: 'IN_CATEGORY', type: 'category', shown: 1, total: 1 },
    { edge: 'COVERED_BY', type: 'document', shown: 1, total: 1 }],
  notes: [],
}
const SIMILAR: GraphSimilarReply = {
  customer: AURORA, period: PERIOD, products: 105,
  similar: [node('customer', '12', 'Twin Buyer Ltd', 900, { shared_products: 40, score_text: '38%' })],
  edges: [{ ...edge(AURORA.id, 'customer:12', 'BUYS_LIKE'), shared_products: 40, score_text: '38%' }],
}

const SEARCH_URL = '/api/graph/search?q=Aurora'
const AURORA_URL = '/api/graph/node?type=customer&id=3680&limit=25'
const MOTOR_URL = '/api/graph/node?type=product&id=45&limit=25'

function replies(extra = {}) {
  return {
    [SEARCH_URL]: { body: { q: 'Aurora', results: [AURORA, node('customer', '32', 'Aurora Fluid Power Limited', null)] } },
    [AURORA_URL]: { body: AURORA_REPLY },
    [MOTOR_URL]: { body: MOTOR_REPLY },
    '/api/graph/similar?customer_id=3680': { body: SIMILAR },
    ...extra,
  }
}

/** Types Aurora, picks the hit and waits for the graph. */
async function drawAurora() {
  fireEvent.change(screen.getByRole('combobox', { name: 'Search' }), { target: { value: 'Aurora' } })
  fireEvent.click(await screen.findByRole('option', { name: /Aurora Hydraulics Private Limited/ }))
  await waitFor(() => expect(lastChart()?.types()).toEqual(['graph']))
  return lastChart()
}

const handler = (name: string) => lastChart().on.mock.calls.find(([event]) => event === name)![1] as (p: unknown) => void
const nodeIds = () => (lastChart().option!.series[0].data as { id: string }[]).map((n) => n.id)

describe('GraphPage', () => {
  it('opens at /graph from the menu of every user', async () => {
    expect(parseRoute('/graph')).toEqual({ kind: 'graph' })
    fakeFetch({ '/api/me': { body: ASHA } })
    window.history.pushState(null, '', '/graph')
    render(<App />)
    const link = await screen.findByRole('link', { name: 'Knowledge graph' }, { timeout: 4000 }) // the whole app loads first
    expect(link).toHaveAttribute('aria-current', 'page')
    await waitFor(() => expect(document.title).toBe('Knowledge graph · Manufacturing Intelligence'))
    expect(screen.getByText('Search for a starting point')).toBeInTheDocument()
  })

  it('draws the neighbourhood of a search hit with the details in the panel', async () => {
    const fetch = fakeFetch(replies())
    renderAt('/graph', <GraphPage />)

    fireEvent.change(screen.getByRole('combobox', { name: 'Search' }), { target: { value: 'A' } })  // 1 letter: no search yet
    const chart = await drawAurora()
    expect(fetch.mock.calls.some(([url]) => String(url).includes('q=A&') || String(url).endsWith('q=A'))).toBe(false)

    const series = chart.option!.series[0]
    expect(series.layout).toBe('force')
    expect(nodeIds()).toEqual(['customer:3680', 'product:45', 'sales_person:4', 'state:Tamil Nadu'])
    expect(series.links).toHaveLength(3)
    expect(chart.option!.legend[0].data).toEqual(['Customer', 'Product', 'Sales person', 'State / country'])
    expect(screen.getByRole('img', { name: /Knowledge graph around Aurora Hydraulics Private Limited: 4 nodes/ })).toBeInTheDocument()

    const panel = screen.getByRole('complementary', { name: 'Node details' })
    expect(within(panel).getByText('INR 2,90,88,275.00')).toBeInTheDocument()
    expect(within(panel).getByText('All data up to today (21-Dec-2025 to 04-Nov-2026)')).toBeInTheDocument()
    expect(within(panel).getByText(/Unknown product .* is in the total but not drawn/)).toBeInTheDocument()
    expect(within(panel).getByText('Bought · products (top 1 of 105)')).toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: 'Ask about this' }))
      .toHaveAttribute('href', `/new?q=${encodeURIComponent('Top products bought by Aurora Hydraulics Private Limited')}`)
    expect(within(panel).getByRole('button', { name: 'In the middle' })).toBeDisabled()
  })

  it('shows a clicked node in the panel without drawing it again', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const before = lastChart().option

    handler('click')({ dataType: 'node', data: { id: 'product:45' } })

    const panel = screen.getByRole('complementary', { name: 'Node details' })
    expect(await within(panel).findByText('INR 90,00,000.00')).toBeInTheDocument()
    expect(within(panel).getByText('Hydraulic motor HM-346-1B')).toBeInTheDocument()
    expect(within(panel).getByText('8 mentions')).toBeInTheDocument()          // the PDF page that covers it
    expect(within(panel).getByRole('button', { name: 'Open' })).toBeEnabled()
    expect(lastChart().option).toBe(before)                                     // the graph stays as it is
    handler('click')({ dataType: 'edge', data: {} })                            // an edge: nothing happens
  })

  it('goes into a double-clicked node: only its own links, the path grows', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    await drawAurora()

    handler('dblclick')({ dataType: 'node', data: { id: 'product:45' } })

    await waitFor(() => expect(nodeIds()).toEqual(['product:45', 'customer:3680', 'category:Hydraulic motors',
      'document:product_catalogue.pdf#2']))                                    // Aurora's other links are gone
    const links = lastChart().option!.series[0].links as { edgeId: string; lineStyle: { type?: string } }[]
    expect(links).toHaveLength(3)
    expect(links.find((l) => l.edgeId.includes('COVERED_BY'))!.lineStyle.type).toBe('dashed')
    expect(screen.getByText('Hydraulic motor HM-346-1B · All data up to today')).toBeInTheDocument()
    const path = screen.getByRole('navigation', { name: 'Path' })
    expect(within(path).getByRole('button', { name: 'Aurora Hydraulics Private Limited' })).toBeInTheDocument()
    expect(within(path).getByText(/click the dot in the middle to go back/)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'In the middle' })).toBeDisabled()
  })

  it('adds the similar customers of a customer', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    await drawAurora()

    fireEvent.click(screen.getByRole('button', { name: 'Similar customers' }))

    expect(await screen.findByText('Twin Buyer Ltd')).toBeInTheDocument()
    expect(screen.getByText('40 shared · 38%')).toBeInTheDocument()
    await waitFor(() => expect(nodeIds()).toContain('customer:12'))
    const links = lastChart().option!.series[0].links as { edgeId: string }[]
    expect(links.some((l) => l.edgeId === 'customer:3680|BUYS_LIKE|customer:12')).toBe(true)
  })

  it('asks again for the drawn nodes when the FY changes', async () => {
    const fetch = fakeFetch(replies({
      '/api/graph/node?type=customer&id=3680&fy=2526&limit=25': { body: { ...AURORA_REPLY, period: PERIOD_2526,
        node: { ...AURORA, amount: 5000, amount_text: '5,000.00' }, neighbours: [MOTOR], edges: [AURORA_REPLY.edges[0]] } },
    }))
    renderAt('/graph', <GraphPage />)
    await drawAurora()

    fireEvent.change(screen.getByLabelText('Period'), { target: { value: '2526' } })

    expect(await screen.findByText('INR 5,000.00')).toBeInTheDocument()
    expect(fetch.mock.calls.map(([url]) => url)).toContain('/api/graph/node?type=customer&id=3680&fy=2526&limit=25')
    expect(nodeIds()).toEqual(['customer:3680', 'product:45'])
    expect(screen.getByText('01-Apr-2025 to 31-Mar-2026')).toBeInTheDocument()
  })

  it('starts again with Reset', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    await drawAurora()

    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))

    expect(screen.getByText('Search for a starting point')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: /Knowledge graph around/ })).not.toBeInTheDocument()
  })

  it('says clearly when the search or the graph cannot be read', async () => {
    fakeFetch(replies({
      '/api/graph/search?q=zz': { body: { q: 'zz', results: [] } },
      '/api/graph/search?q=%27x': { status: 400, body: { detail: 'Type at least 2 characters to search.' } },
      [AURORA_URL]: { status: 503, body: { detail: 'The NOP data (MySQL) cannot be read right now - please try again in a minute.' } },
    }))
    renderAt('/graph', <GraphPage />)
    const box = screen.getByRole('combobox', { name: 'Search' })

    fireEvent.change(box, { target: { value: 'zz' } })
    expect(await screen.findByText('Nothing found for "zz".')).toBeInTheDocument()
    fireEvent.change(box, { target: { value: "'x" } })
    expect(await screen.findByText('Type at least 2 characters to search.')).toBeInTheDocument()

    fireEvent.change(box, { target: { value: 'Aurora' } })
    fireEvent.click(await screen.findByRole('option', { name: /Aurora Hydraulics Private Limited/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The NOP data (MySQL) cannot be read right now')
    expect(screen.queryByRole('img', { name: /Knowledge graph around/ })).not.toBeInTheDocument()
  })

  it('picks a hit with the arrow keys and Enter', async () => {
    fakeFetch(replies({ '/api/graph/node?type=customer&id=32&limit=25': { body: { ...AURORA_REPLY,
      node: node('customer', '32', 'Aurora Fluid Power Limited', 2691000), neighbours: [], edges: [], groups: [], notes: [] } } }))
    renderAt('/graph', <GraphPage />)
    const box = screen.getByRole('combobox', { name: 'Search' })
    fireEvent.change(box, { target: { value: 'Aurora' } })
    await screen.findByRole('option', { name: /Aurora Fluid Power/ })

    fireEvent.keyDown(box, { key: 'ArrowDown' })
    fireEvent.keyDown(box, { key: 'Enter' })

    await waitFor(() => expect(nodeIds()).toEqual(['customer:32']))
  })
})

describe('the graph data and option', () => {
  it('merges without duplicates and stops at the node cap', () => {
    const many = Array.from({ length: 10 }, (_, i) => node('product', String(i), `P${i}`, i))
    const first = mergeGraph(EMPTY_GRAPH, [AURORA, ...many.slice(0, 5)], many.slice(0, 5).map((p) => edge(AURORA.id, p.id, 'BOUGHT', 1)), 8)
    expect(first.left).toBe(0)
    const second = mergeGraph(first.graph, many, many.map((p) => edge(AURORA.id, p.id, 'BOUGHT', 1)), 8)
    expect(second.graph.nodes).toHaveLength(8)
    expect(second.left).toBe(3)
    expect(second.graph.edges).toHaveLength(7)                                  // only edges whose two ends are drawn
    const again = mergeGraph(second.graph, [{ ...AURORA, amount: null, amount_text: '' }], [])
    expect(again.graph.nodes[0].amount).toBe(29088275)                          // a copy without numbers keeps them
  })

  it('sizes nodes by net sales, edges by amount, and labels the big nodes', () => {
    expect(nodeSize(AURORA, 29088275, 1000)).toBe(MAX_SIZE)
    expect(nodeSize(node('customer', '1', 'Small', 1000), 29088275, 1000)).toBe(MIN_SIZE)
    const middle = nodeSize(MOTOR, 1e10, 1e6)                                  // 10 lakh .. 1,000 crore: in between
    expect(middle).toBeGreaterThan(MIN_SIZE)
    expect(middle).toBeLessThan(MAX_SIZE)
    expect(nodeSize(node('customer', '1', 'Credit only', -500), 100)).toBe(MIN_SIZE)
    expect(nodeSize(CATALOGUE, 100)).toBeLessThan(MAX_SIZE)
    expect(edgeWidth(edge('a', 'b', 'BOUGHT', 100), 100)).toBe(8)
    expect(edgeWidth({ ...edge('a', 'b', 'COVERED_BY'), mentions: 3 }, 100)).toBe(1.2)

    const nodes = Array.from({ length: 20 }, (_, i) => node('customer', String(i), `C${i}`, (i + 1) * 1000))
    const option = buildGraphOption({ nodes, edges: [] }, readColours(), { center: 'customer:0' }) as any
    const labelled = option.series[0].data.filter((n: any) => n.label.show).map((n: any) => n.id)
    expect(labelled).toHaveLength(13)                                           // the 12 biggest + the centre
    expect(labelled).toContain('customer:0')
    expect(option.series[0].emphasis.label.show).toBe(true)                     // the hovered one too
    expect(option.tooltip.formatter({ dataType: 'node', data: { id: 'customer:19' } })).toContain('20,000.00')

    const withEdge = buildGraphOption({ nodes: [AURORA, MOTOR], edges: [edge(AURORA.id, MOTOR.id, 'BOUGHT', 1250000)] },
      readColours()) as any
    const tip = withEdge.tooltip.formatter({ dataType: 'edge', data: { edgeId: `${AURORA.id}|BOUGHT|${MOTOR.id}` } })
    expect(tip).toContain('Aurora Hydraulics Private Limited → Hydraulic motor HM-346-1B')
    expect(tip).toContain('12,50,000.00')
    const colours = withEdge.series[0].categories.map((c: any) => c.itemStyle.color)
    expect(colours).not.toContain('#DC2626')                                    // no red, no yellow
  })
})

describe('GraphPage remembers the graph (04-Nov: "if I move to another page it is gone")', () => {
  it('shows the same graph and path after leaving the page and coming back, without asking again', async () => {
    const fetch = fakeFetch(replies())
    const first = renderAt('/graph', <GraphPage />)
    await drawAurora()
    handler('dblclick')({ dataType: 'node', data: { id: MOTOR.id } })                 // into the motor
    await waitFor(() => expect(nodeIds()).toContain('category:Hydraulic motors'))
    const shown = nodeIds()
    const calls = fetch.mock.calls.length

    first.unmount()                                                                  // to another page ...
    renderAt('/graph', <GraphPage />)                                                // ... and back

    await waitFor(() => expect(lastChart()?.types()).toEqual(['graph']))
    expect(nodeIds()).toEqual(shown)                                                 // the same dots
    const path = screen.getByRole('navigation', { name: 'Path' })
    expect(within(path).getByRole('button', { name: 'Aurora Hydraulics Private Limited' })).toBeInTheDocument()
    const panel = screen.getByRole('complementary', { name: 'Node details' })
    expect(within(panel).getByText(/Hydraulic motor HM-346-1B/)).toBeInTheDocument() // the same panel
    expect(fetch.mock.calls.length).toBe(calls)                                      // nothing asked again
  })

  it('keeps it in this tab after a refresh (sessionStorage), and Reset forgets it', async () => {
    fakeFetch(replies())
    const first = renderAt('/graph', <GraphPage />)
    await drawAurora()
    expect(JSON.parse(window.sessionStorage.getItem('mi.graphPage.v2')!).trail.map((n: GraphNode) => n.id)).toEqual([AURORA.id])

    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(window.sessionStorage.getItem('mi.graphPage.v2')).toBeNull()
    first.unmount()
    renderAt('/graph', <GraphPage />)
    expect(screen.getByText('Search for a starting point')).toBeInTheDocument()
  })

  it('forgets it when the user signs out, so the next person never sees it', async () => {
    fakeFetch({ ...replies(), '/api/me': { body: ASHA }, '/api/logout': { body: { ok: true } } })
    window.history.pushState(null, '', '/graph')
    render(<App />)
    await screen.findByRole('link', { name: 'Knowledge graph' }, { timeout: 4000 })
    await drawAurora()
    expect(window.sessionStorage.getItem('mi.graphPage.v2')).not.toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'User menu' }))   // the round badge in the top bar
    fireEvent.click(await screen.findByRole('button', { name: /sign out|log out/i }))
    await waitFor(() => expect(window.sessionStorage.getItem('mi.graphPage.v2')).toBeNull())
  })
})

describe('GraphPage goes into a node and back (04-Nov: "double-click opens it, a click on the main one goes back")', () => {
  const AURORA_ONLY = ['customer:3680', 'product:45', 'sales_person:4', 'state:Tamil Nadu']
  const MOTOR_ONLY = ['product:45', 'customer:3680', 'category:Hydraulic motors', 'document:product_catalogue.pdf#2']

  async function intoMotor() {
    handler('dblclick')({ dataType: 'node', data: { id: MOTOR.id } })
    await waitFor(() => expect(nodeIds()).toEqual(MOTOR_ONLY))
  }

  it('shows only the start in the path, with no Back, before going anywhere', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const path = screen.getByRole('navigation', { name: 'Path' })
    expect(within(path).getByText('Aurora Hydraulics Private Limited')).toHaveAttribute('aria-current', 'step')
    expect(within(path).getAllByRole('button').map((b) => b.textContent)).toEqual(['3D view', '⛶ Full screen', 'Hide details »'])
    expect(within(path).getByText('Double-click a dot to go into it')).toBeInTheDocument()
  })

  it('a click on the node in the middle goes back, without asking the server again', async () => {
    const fetch = fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    await intoMotor()
    const calls = fetch.mock.calls.length

    handler('click')({ dataType: 'node', data: { id: MOTOR.id } })                 // the motor is in the middle
    await waitFor(() => expect(nodeIds()).toEqual(AURORA_ONLY))
    expect(lastChart().option!.series[0].data.find((n: { id: string }) => n.id === AURORA.id).itemStyle).toBeDefined()
    const panel = screen.getByRole('complementary', { name: 'Node details' })
    expect(within(panel).getByText('INR 2,90,88,275.00')).toBeInTheDocument()     // Aurora in the panel again
    expect(screen.queryByRole('button', { name: '↩ Back' })).not.toBeInTheDocument()
    expect(fetch.mock.calls.length).toBe(calls)                                     // nothing asked again
  })

  it('the rest of a double-click on the middle node does not go back in again', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    await intoMotor()

    handler('click')({ dataType: 'node', data: { id: MOTOR.id } })                 // 1st click: back to Aurora
    await waitFor(() => expect(nodeIds()).toEqual(AURORA_ONLY))
    handler('dblclick')({ dataType: 'node', data: { id: MOTOR.id } })              // the same double-click: ignored
    await new Promise((done) => setTimeout(done, 20))
    expect(nodeIds()).toEqual(AURORA_ONLY)
  })

  it('a click on a node that is not in the middle only shows its details', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    await intoMotor()

    handler('click')({ dataType: 'node', data: { id: AURORA.id } })
    const panel = screen.getByRole('complementary', { name: 'Node details' })
    expect(await within(panel).findByText('INR 2,90,88,275.00')).toBeInTheDocument()
    expect(nodeIds()).toEqual(MOTOR_ONLY)                                           // still in the motor
    expect(within(panel).getByRole('button', { name: 'Open' })).toBeEnabled()
  })

  it('the path and ↩ Back go back too; Open in the panel goes in', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    await drawAurora()

    const panel = screen.getByRole('complementary', { name: 'Node details' })
    fireEvent.click(within(panel).getByRole('button', { name: /Hydraulic motor HM-346-1B/ }))   // a link in the panel
    fireEvent.click(await within(panel).findByRole('button', { name: 'Open' }))
    await waitFor(() => expect(nodeIds()).toEqual(MOTOR_ONLY))
    const path = screen.getByRole('navigation', { name: 'Path' })
    expect(within(path).getByText('Hydraulic motor HM-346-1B')).toHaveAttribute('aria-current', 'step')

    fireEvent.click(within(path).getByRole('button', { name: 'Aurora Hydraulics Private Limited' }))
    await waitFor(() => expect(nodeIds()).toEqual(AURORA_ONLY))

    const later = Date.now() + 1000                                                 // past the quiet time after Back
    vi.spyOn(Date, 'now').mockReturnValue(later)
    await intoMotor()
    fireEvent.click(screen.getByRole('button', { name: '↩ Back' }))
    await waitFor(() => expect(nodeIds()).toEqual(AURORA_ONLY))
  })

  it('a new search starts a new path', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    await intoMotor()
    await drawAurora()
    await waitFor(() => expect(nodeIds()).toEqual(AURORA_ONLY))
    expect(within(screen.getByRole('navigation', { name: 'Path' })).queryByRole('button', { name: /Aurora|Back/ })).not.toBeInTheDocument()
  })
})

describe('GraphPage full screen and hide details (04-Nov)', () => {
  const chartHeight = () => (document.querySelector('.echart') as HTMLElement).style.height

  it('Hide details gives the graph the panel room, Show details brings it back; kept in this browser', async () => {
    fakeFetch(replies())
    const first = renderAt('/graph', <GraphPage />)
    await drawAurora()

    fireEvent.click(screen.getByRole('button', { name: 'Hide details »' }))
    expect(screen.queryByRole('complementary', { name: 'Node details' })).not.toBeInTheDocument()
    expect(document.querySelector('.graph-layout')).toHaveClass('no-panel')
    expect(window.localStorage.getItem('mi.graphPanel')).toBe('hidden')

    first.unmount()                                                                 // another page and back
    renderAt('/graph', <GraphPage />)
    await waitFor(() => expect(lastChart()?.types()).toEqual(['graph']))
    expect(screen.queryByRole('complementary', { name: 'Node details' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '« Show details' }))
    expect(screen.getByRole('complementary', { name: 'Node details' })).toBeInTheDocument()
    expect(window.localStorage.getItem('mi.graphPanel')).toBeNull()
  })

  it('Full screen shows the graph on the whole screen, taller; Esc and Exit full screen come back', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    expect(chartHeight()).toBe('580px')

    fireEvent.click(screen.getByRole('button', { name: '⛶ Full screen' }))
    expect(screen.getByRole('dialog', { name: 'Knowledge graph, full screen' })).toHaveClass('full')
    expect(chartHeight()).toBe(`${Math.max(360, window.innerHeight - 150)}px`)
    handler('dblclick')({ dataType: 'node', data: { id: MOTOR.id } })               // going in still works
    await waitFor(() => expect(nodeIds()).toContain('category:Hydraulic motors'))

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(chartHeight()).toBe('580px')

    fireEvent.click(screen.getByRole('button', { name: '⛶ Full screen' }))
    fireEvent.click(screen.getByRole('button', { name: 'Exit full screen' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('GraphPage smarter search (05-Nov): type words, close spellings, Ask AI instead - no AI while typing', () => {
  const box = () => screen.getByRole('combobox', { name: 'Search' })

  it('shows the hint while the box is empty', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    expect(screen.getByText(SEARCH_HINT)).toBeInTheDocument()
    expect(SEARCH_HINT).toBe('Type a name, or a word like customer, product, category, sales person or state')
    fireEvent.change(box(), { target: { value: 'Aurora' } })
    await screen.findByRole('option', { name: /Aurora Hydraulics Private Limited/ })
    expect(screen.queryByText(SEARCH_HINT)).not.toBeInTheDocument()
  })

  it('"customer" lists the top customers by net sales and picking one draws its graph', async () => {
    const top = { ...AURORA, sub: 'Chennai, Tamil Nadu' }
    fakeFetch(replies({
      '/api/graph/search?q=customer': { body: { q: 'customer', match: 'top', match_type: 'customer', fuzzy: false,
        note: 'Top 2 customers by net sales (all data up to today)',
        results: [top, node('customer', '14', 'Kaveri Pumps Limited', 5000000, { sub: 'Coimbatore, Tamil Nadu' })] } },
    }))
    renderAt('/graph', <GraphPage />)
    fireEvent.change(box(), { target: { value: 'customer' } })
    const options = within(await screen.findByRole('listbox', { name: 'Matching nodes' })).getAllByRole('option')
    expect(options.map((o) => o.textContent)).toEqual([
      'Aurora Hydraulics Private LimitedCustomer · Chennai, Tamil Nadu · 2,90,88,275.00',
      'Kaveri Pumps LimitedCustomer · Coimbatore, Tamil Nadu · 50,00,000.00',
    ])
    expect(screen.getByText('Top 2 customers by net sales (all data up to today)')).toBeInTheDocument()
    expect(screen.queryByText('Did you mean')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Ask AI instead/ })).not.toBeInTheDocument()
    fireEvent.click(options[0])
    await waitFor(() => expect(lastChart()?.types()).toEqual(['graph']))
    expect(nodeIds()[0]).toBe('customer:3680')
  })

  it('a close spelling says "Did you mean" on its hit', async () => {
    fakeFetch(replies({
      '/api/graph/search?q=aurra': { body: { q: 'aurra', match: 'name', match_type: '', fuzzy: true,
        note: 'No exact match for "aurra" - did you mean one of these?',
        results: [{ ...AURORA, fuzzy: true }, node('customer', '32', 'Aurora Fluid Power Limited', 2691000)] } },
    }))
    renderAt('/graph', <GraphPage />)
    fireEvent.change(box(), { target: { value: 'aurra' } })
    const fuzzy = await screen.findByRole('option', { name: /Aurora Hydraulics Private Limited/ })
    expect(within(fuzzy).getByText('Did you mean')).toBeInTheDocument()
    expect(within(screen.getByRole('option', { name: /Aurora Fluid Power/ })).queryByText('Did you mean')).not.toBeInTheDocument()
    expect(screen.getByText('No exact match for "aurra" - did you mean one of these?')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Ask AI instead/ })).not.toBeInTheDocument()
  })

  it('only when nothing is found: "Ask AI instead" links to /new?q=<the text>', async () => {
    fakeFetch(replies({
      '/api/graph/search?q=blue+widgets+%26+more': { body: { q: 'blue widgets & more', results: [] } },
    }))
    renderAt('/graph', <GraphPage />)
    expect(screen.queryByRole('link', { name: /Ask AI instead/ })).not.toBeInTheDocument()
    fireEvent.change(box(), { target: { value: 'blue widgets & more' } })
    expect(await screen.findByText('Nothing found for "blue widgets & more".')).toBeInTheDocument()
    const ask = screen.getByRole('link', { name: /Ask AI instead/ })
    expect(ask).toHaveAttribute('href', '/new?q=blue%20widgets%20%26%20more')
    fireEvent.change(box(), { target: { value: '' } })                              // cleared: the link goes
    expect(screen.queryByRole('link', { name: /Ask AI instead/ })).not.toBeInTheDocument()
    expect(screen.getByText(SEARCH_HINT)).toBeInTheDocument()
  })

  it('"Ask AI instead" only fills the question box - nothing is sent until Ask is pressed', async () => {
    const fetch = fakeFetch({ '/api/me': { body: ASHA }, '/api/graph/search?q=blue+widgets': { body: { q: 'blue widgets', results: [] } } })
    window.history.pushState(null, '', '/graph')
    render(<App />)
    fireEvent.change(await screen.findByRole('combobox', { name: 'Search' }, { timeout: 4000 }), { target: { value: 'blue widgets' } })
    fireEvent.click(await screen.findByRole('link', { name: /Ask AI instead/ }))
    expect(await screen.findByLabelText('Your question', {}, { timeout: 4000 })).toHaveValue('blue widgets')
    expect(window.location.pathname + window.location.search).toBe('/new?q=blue%20widgets')
    expect(fetch.mock.calls.filter(([, init]) => (init?.method ?? 'GET') !== 'GET')).toEqual([])  // no question sent
  })
})

describe('GraphPage search counts and "Show more" (05-Nov: "why only 10-12 customers?")', () => {
  const box = () => screen.getByRole('combobox', { name: 'Search' })
  const list = () => screen.getByRole('listbox', { name: 'Matching nodes' })
  const customers = (from: number, count: number) => Array.from({ length: count }, (_, i) =>
    node('customer', String(1000 + from + i), `Customer ${String(from + i).padStart(2, '0')}`, 100000 - (from + i)))
  const topNote = (shown: number) => `Top ${shown} of 4,982 customers by net sales (all data up to today) - type more to narrow`
  const page = (from: number) => ({ body: { q: 'customer', match: 'top', match_type: 'customer', fuzzy: false, total: 4982,
    note: topNote(from + 10), results: customers(from, 10) } })
  const pages = (extra = {}) => replies({
    '/api/graph/search?q=customer': page(0),
    ...Object.fromEntries([10, 20, 30, 40].map((from) => [`/api/graph/search?q=customer&offset=${from}&limit=10`, page(from)])),
    ...extra,
  })
  const labels = () => within(list()).getAllByRole('option').map((o) => o.querySelector('.font-semibold')?.textContent ?? o.textContent)

  it('says how many there are in all; Show more adds 10 with a spinner and keeps the list open', async () => {
    const fetch = fakeFetch(pages())
    renderAt('/graph', <GraphPage />)
    fireEvent.change(box(), { target: { value: 'customer' } })
    await screen.findByRole('option', { name: /Customer 09/ })
    expect(screen.getByText(topNote(10))).toBeInTheDocument()
    expect(within(list()).getAllByRole('option')).toHaveLength(11)                 // 10 hits + Show more

    const more = within(list()).getByRole('option', { name: 'Show more' })
    expect(fireEvent.mouseDown(more)).toBe(false)                                  // the box keeps the focus: the list stays
    fireEvent.click(more)
    expect(within(list()).getByRole('option', { name: /Loading more/ })).toHaveAttribute('aria-busy', 'true')

    expect(await screen.findByText(topNote(20))).toBeInTheDocument()
    expect(labels()).toEqual([...customers(0, 20).map((n) => n.label), 'Show more'])  // appended, in order
    expect(fetch.mock.calls.map(([url]) => url)).toContain('/api/graph/search?q=customer&offset=10&limit=10')
    expect(box()).toHaveAttribute('aria-expanded', 'true')
  })

  it('the arrow keys reach Show more, Enter loads 10 more, and Enter picks a new hit', async () => {
    fakeFetch(pages({ '/api/graph/node?type=customer&id=1010&limit=25': { body: { ...AURORA_REPLY,
      node: customers(10, 1)[0], neighbours: [], edges: [], groups: [], notes: [] } } }))
    renderAt('/graph', <GraphPage />)
    fireEvent.change(box(), { target: { value: 'customer' } })
    await screen.findByRole('option', { name: /Customer 09/ })

    for (let i = 0; i < 10; i += 1) fireEvent.keyDown(box(), { key: 'ArrowDown' })
    expect(box()).toHaveAttribute('aria-activedescendant', 'graph-hit-more')
    expect(within(list()).getByRole('option', { name: 'Show more' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(box(), { key: 'Enter' })

    await screen.findByRole('option', { name: /Customer 19/ })
    expect(box()).toHaveAttribute('aria-activedescendant', 'graph-hit-10')        // on the first new hit
    fireEvent.keyDown(box(), { key: 'ArrowUp' })
    expect(box()).toHaveAttribute('aria-activedescendant', 'graph-hit-9')
    fireEvent.keyDown(box(), { key: 'ArrowDown' })
    fireEvent.keyDown(box(), { key: 'Enter' })
    await waitFor(() => expect(nodeIds()).toEqual(['customer:1010']))
  })

  it('at 50 hits "Showing 50 - type more to narrow" replaces the button', async () => {
    fakeFetch(pages())
    renderAt('/graph', <GraphPage />)
    fireEvent.change(box(), { target: { value: 'customer' } })
    await screen.findByRole('option', { name: /Customer 09/ })
    for (const shown of [20, 30, 40, 50]) {
      fireEvent.click(within(list()).getByRole('option', { name: 'Show more' }))
      expect(await screen.findByText(topNote(shown))).toBeInTheDocument()
    }
    expect(AT_MAX).toBe(`Showing ${MAX_HITS} - type more to narrow`)
    expect(screen.getByText(AT_MAX)).toBeInTheDocument()
    expect(within(list()).queryByRole('option', { name: 'Show more' })).not.toBeInTheDocument()
    expect(within(list()).getAllByRole('option')).toHaveLength(50)
  })

  it('a new search ignores a Show more reply that comes late', async () => {
    let release!: () => void
    const gate = new Promise<void>((done) => { release = done })
    const fetch = fakeFetch(pages())
    const answer = fetch.getMockImplementation()!
    fetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.includes('offset=10')) await gate                                  // this one is slow
      return answer(url, init)
    })
    renderAt('/graph', <GraphPage />)
    fireEvent.change(box(), { target: { value: 'customer' } })
    await screen.findByRole('option', { name: /Customer 09/ })
    fireEvent.click(within(list()).getByRole('option', { name: 'Show more' }))
    expect(within(list()).getByRole('option', { name: /Loading more/ })).toBeInTheDocument()

    fireEvent.change(box(), { target: { value: 'Aurora' } })
    await screen.findByRole('option', { name: /Aurora Fluid Power/ })
    release()
    await new Promise((done) => setTimeout(done, 30))
    expect(labels()).toEqual(['Aurora Hydraulics Private Limited', 'Aurora Fluid Power Limited'])  // no old page added
    expect(screen.queryByText(topNote(20))).not.toBeInTheDocument()
    expect(within(list()).queryByRole('option', { name: /Show more|Loading more/ })).not.toBeInTheDocument()
  })

  it('close spellings and searches that fit get no Show more', async () => {
    fakeFetch(replies({
      '/api/graph/search?q=aurra': { body: { q: 'aurra', match: 'name', fuzzy: true, total: 30,
        note: 'No exact match for "aurra" - did you mean one of these?', results: [{ ...AURORA, fuzzy: true }] } },
      '/api/graph/search?q=kaveri': { body: { q: 'kaveri', match: 'name', fuzzy: false, total: 1, note: '',
        results: [node('customer', '14', 'Kaveri Pumps Limited', null)] } },
    }))
    renderAt('/graph', <GraphPage />)
    fireEvent.change(box(), { target: { value: 'aurra' } })
    await screen.findByRole('option', { name: /Aurora Hydraulics/ })
    expect(within(list()).queryByRole('option', { name: 'Show more' })).not.toBeInTheDocument()
    fireEvent.change(box(), { target: { value: 'kaveri' } })
    await screen.findByRole('option', { name: /Kaveri Pumps/ })
    expect(within(list()).getAllByRole('option')).toHaveLength(1)
  })
})

describe('GraphPage zooms only on the dots (05-Nov: "if I scroll in any empty space it zooms out")', () => {
  // ECharts' own layout on the fake chart: the 4 dots of Aurora between (100,100) and (300,200) on the screen.
  // `view` stands in for the zoom and pan (convertToPixel follows it, as in ECharts).
  const SPOTS: [number, number][] = [[100, 100], [300, 200], [200, 150], [150, 180]]
  function fakeLayout(chart: ReturnType<typeof lastChart>, view = { scale: 1, dx: 0, dy: 0 }) {
    const ids = nodeIds()
    Object.assign(chart, {
      getModel: () => ({ getSeriesByIndex: () => ({ getData: () => ({
        each: (fn: (i: number) => void) => ids.forEach((_, i) => fn(i)),
        getItemLayout: (i: number) => SPOTS[i], getId: (i: number) => ids[i],
      }) }) }),
      convertToPixel: (_finder: unknown, [x, y]: number[]) => [x * view.scale + view.dx, y * view.scale + view.dy],
    })
    return view
  }

  // ECharts listens for the wheel on a box inside the chart's own box: a stand-in that says what reached it
  function wheelOn() {
    const inner = document.createElement('div')
    document.querySelector('.echart')!.appendChild(inner)
    const reached = vi.fn()
    inner.addEventListener('wheel', reached)
    return (clientX: number, clientY: number) => {
      reached.mockClear()
      const event = new WheelEvent('wheel', { bubbles: true, cancelable: true, clientX, clientY, deltaY: 100 })
      inner.dispatchEvent(event)
      return { zooms: reached.mock.calls.length > 0, prevented: event.defaultPrevented }
    }
  }

  it('a wheel on the dots (or just around them) zooms; on the empty space the page scrolls', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    const chart = await drawAurora()
    expect(chart.option!.series[0].roamTrigger).toBe('global')
    const view = fakeLayout(chart)
    const wheel = wheelOn()

    expect(wheel(200, 150)).toEqual({ zooms: true, prevented: false })            // among the dots
    expect(wheel(335, 235).zooms).toBe(true)                                        // within 40 px of the last dot
    expect(wheel(600, 500)).toEqual({ zooms: false, prevented: false })            // empty space: the page scrolls
    expect(wheel(100, 30).zooms).toBe(false)                                       // 70 px above the dots

    Object.assign(view, { scale: 2, dx: 0, dy: 0 })                                // zoomed in: the dots grew
    expect(wheel(600, 400).zooms).toBe(true)
    Object.assign(view, { scale: 0.5, dx: -50, dy: 0 })                            // zoomed out and moved left
    expect(wheel(200, 150).zooms).toBe(false)
    expect(wheel(50, 70).zooms).toBe(true)
  })

  it('in full screen too the wheel zooms only on the dots (05-Nov: "even in full screen not on empty space")', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    fakeLayout(await drawAurora())

    fireEvent.click(screen.getByRole('button', { name: '⛶ Full screen' }))
    expect(wheelOn()(600, 500).zooms).toBe(false)                                  // empty space: no zoom
    expect(wheelOn()(200, 150).zooms).toBe(true)                                   // on the dots: zoom
    fireEvent.click(screen.getByRole('button', { name: 'Exit full screen' }))
    expect(wheelOn()(600, 500).zooms).toBe(false)
  })

  it('Fit draws the graph again where the dots are, at normal zoom, keeping the selected node', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    const chart = await drawAurora()
    fakeLayout(chart)
    const before = chart.option
    chart.dispatchAction.mockClear()

    fireEvent.click(screen.getByRole('button', { name: 'Fit' }))
    const series = chart.option!.series[0]
    expect(chart.option).not.toBe(before)                                         // a new option: zoom 1, in the middle
    expect(series.zoom).toBeUndefined()
    expect(series.center).toBeUndefined()
    expect(series.data.map((n: { x: number; y: number }) => [n.x, n.y])).toEqual(SPOTS) // the dots keep their place
    expect(chart.dispatchAction).toHaveBeenCalledWith({ type: 'select', seriesIndex: 0, dataIndex: 0 }) // Aurora again
  })
})
