// Knowledge graph: a search hit draws its neighbourhood (ECharts is a fake - jsdom has no canvas - so the tests
// check the option it gets), a click fills the side panel, a double-click merges the node's neighbours in, Similar
// customers, the FY filter asks again, Reset, the 150-node cap, the option itself (circles with an icon, label
// cards, pills on the links, the rings), the zoom buttons, and friendly errors.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { readColours } from '../charts/chartOption'
import { hiddenCards } from '../charts/graphLayout'
import { buildGraphOption, cardModeFor, edgeWidth, FULL_CARDS, MAX_SIZE, MIN_SIZE, nodeSize, nodeSizeFor, PILL_LINKS, textWidth } from '../charts/graphOption'
import { TYPE_ICONS } from '../charts/graphLook'
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
    await waitFor(() => expect(document.title).toBe('Knowledge graph · SSAGE'))
    expect(screen.getByText('Search for a starting point')).toBeInTheDocument()
  })

  it('draws the neighbourhood of a search hit with the details in the panel', async () => {
    const fetch = fakeFetch(replies())
    renderAt('/graph', <GraphPage />)

    fireEvent.change(screen.getByRole('combobox', { name: 'Search' }), { target: { value: 'A' } })  // 1 letter: no search yet
    const chart = await drawAurora()
    expect(fetch.mock.calls.some(([url]) => String(url).includes('q=A&') || String(url).endsWith('q=A'))).toBe(false)

    const series = chart.option!.series[0]
    expect(series.layout).toBe('none')                                           // on a ring: nothing wobbles
    expect([series.data[0].x, series.data[0].y]).toEqual([0, 0])                // Aurora in the middle
    expect(series.label.formatter({ data: { id: 'customer:3680' } }))            // its card: the name and two facts
      .toBe('{big|Aurora Hydraulics Private Limited}\n{fact|INR 2.9 Cr}\n{fact|Chennai, Tamil Nadu · Local Customer}')
    expect(series.label.formatter({ data: { id: 'product:45' } })).toBe('{name|Hydraulic motor HM-346-1B}\n{fact|INR 90 L}')
    expect(series.edgeLabel.show).toBe(true)                                     // few links: a pill on each
    expect((series.links as { kind: string }[]).map((link) => series.edgeLabel.formatter({ data: link })))
      .toEqual(['Bought', 'Handled by', 'In state'])
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
      [AURORA_URL]: { status: 503, body: { detail: 'The SS Manufacturing data (MySQL) cannot be read right now - please try again in a minute.' } },
    }))
    renderAt('/graph', <GraphPage />)
    const box = screen.getByRole('combobox', { name: 'Search' })

    fireEvent.change(box, { target: { value: 'zz' } })
    expect(await screen.findByText('Nothing found for "zz".')).toBeInTheDocument()
    fireEvent.change(box, { target: { value: "'x" } })
    expect(await screen.findByText('Type at least 2 characters to search.')).toBeInTheDocument()

    fireEvent.change(box, { target: { value: 'Aurora' } })
    fireEvent.click(await screen.findByRole('option', { name: /Aurora Hydraulics Private Limited/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The SS Manufacturing data (MySQL) cannot be read right now')
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

  it('sizes nodes by net sales (3D), edges by amount; in 2D every node around the middle one the same, with a card', () => {
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
    const drawn = option.series[0].data
    expect(option.series[0].label.show).toBe(true)                              // every node carries its label card
    expect(drawn.every((n: any) => n.label?.show !== false)).toBe(true)
    expect(option.series[0].label.formatter({ data: { id: 'customer:19' } })).toBe('{name|C19}')   // 19 around: compact
    expect(option.series[0].emphasis.label.formatter({ data: { id: 'customer:19' } })).toBe('{name|C19}\n{fact|INR 20 K}')
    expect(drawn[0].symbolSize).toBeGreaterThan(drawn[19].symbolSize)           // the middle node is the biggest ...
    expect(drawn[19].symbolSize).toBe(drawn[1].symbolSize)                      // ... the others all the same, whatever their amount
    expect(drawn[1].symbolSize).toBeGreaterThanOrEqual(26)                      // with room for the icon
    expect(option.series[0].emphasis.label.show).toBe(true)                     // the hovered one always shows its card
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

describe('the 2D look (15-Nov): circles with an icon, label cards, pills, rings', () => {
  // Aurora with `count` products around it (and so `count` links)
  const products = (count: number) => Array.from({ length: count }, (_, i) =>
    node('product', String(i), `Hydraulic motor HM-${300 + i}-1B`, 9000000 / (i + 1), { sub: `FG${i}` }))
  const around = (count: number) => {
    const nodes = products(count)
    return { nodes: [AURORA, ...nodes], edges: nodes.map((p, i) => edge(AURORA.id, p.id, 'BOUGHT', 1250000 / (i + 1))) }
  }
  const build = (count: number, view = {}) =>
    buildGraphOption(around(count), readColours(), { center: AURORA.id, width: 1100, height: 760, ...view }) as any
  // the SVG picture of a node's circle, as text
  const picture = (symbol: string) => decodeURIComponent(symbol.slice(symbol.indexOf(',') + 1))

  it('a node is a circle in its type colour with its white icon; the middle one is the app blue with a soft ring', () => {
    const option = buildGraphOption({ nodes: [AURORA, MOTOR, PRIYA, TAMIL, CATALOGUE], edges: [] }, readColours(), { center: AURORA.id }) as any
    const [aurora, motor, priya, tamil, page] = option.series[0].data
    expect(motor.symbol.startsWith('image://data:image/svg+xml')).toBe(true)
    expect(picture(motor.symbol)).toContain('fill="#16A34A"')                       // a product: green
    expect(picture(motor.symbol)).toContain(`fill="#fff" d="${TYPE_ICONS.product}"`) // its box, in white
    expect(picture(priya.symbol)).toContain(TYPE_ICONS.sales_person)
    expect(picture(tamil.symbol)).toContain(TYPE_ICONS.state)
    expect(picture(page.symbol)).toContain(TYPE_ICONS.document)
    expect(picture(aurora.symbol)).toContain(`fill="${readColours().series[0]}"`)   // the middle node: the app's blue
    expect(picture(aurora.symbol)).toContain('fill-opacity="0.2"')                  // with the soft ring
    expect(picture(aurora.symbol)).toContain(TYPE_ICONS.customer)
    expect(picture(motor.symbol)).not.toContain('fill-opacity')
    expect(aurora.symbolSize).toBeGreaterThan(motor.symbolSize)
  })

  it('a label card has the name in bold (cut when long) and the fact line; in the card, heading and muted colours', () => {
    const long = node('product', '9', 'Gear pump GP-2200 series with a very long description', 4500000)
    const option = buildGraphOption({ nodes: [AURORA, long, CATALOGUE, SIMILAR.similar[0]], edges: [] }, readColours(), { center: AURORA.id }) as any
    const { label } = option.series[0]
    const card = (id: string) => label.formatter({ data: { id } })
    expect(card(long.id)).toBe('{name|Gear pump GP-2200 series…}\n{fact|INR 45 L}')
    expect(card(CATALOGUE.id)).toBe('{name|Product Catalogue, page 2}\n{fact|product_catalogue.pdf}')   // no amount: its file
    expect(card('customer:12')).toBe('{name|Twin Buyer Ltd}\n{fact|INR 900}')
    expect(label.position).toBe('bottom')
    expect(label.backgroundColor).toBe(readColours().surface)
    expect(label.borderRadius).toBeGreaterThan(0)
    expect(label.shadowBlur).toBeGreaterThan(0)
    expect(label.rich.name).toMatchObject({ fontWeight: 600, color: readColours().head })
    expect(label.rich.big.fontWeight).toBe(700)
    expect(label.rich.fact.color).toBe(readColours().muted)
    const braces = node('product', '8', 'Odd {name} here', 100)                                       // { } would start a style
    expect((buildGraphOption({ nodes: [braces], edges: [] }, readColours()) as any).series[0].label.formatter({ data: { id: braces.id } }))
      .toBe('{name|Odd (name) here}\n{fact|INR 100}')
  })

  it('the links are thin straight grey lines with a rounded pill that names them', () => {
    const series = build(3).series[0]
    expect(series.lineStyle).toMatchObject({ curveness: 0, color: readColours().muted })
    expect(series.links.every((l: any) => l.lineStyle.width <= 2.4)).toBe(true)
    expect(series.edgeLabel).toMatchObject({ show: true, backgroundColor: readColours().surface, opacity: 1 })
    expect(series.edgeLabel.borderRadius).toBeGreaterThan(6)
    expect(series.edgeLabel.formatter({ data: { kind: 'BUYS_AS' } })).toBe('Buys as')
    expect(series.edgeLabel.formatter({ data: { kind: 'BUYS_LIKE' } })).toBe('Buys like')
    expect(series.edgeLabel.formatter({ data: { kind: 'COVERED_BY' } })).toBe('Covered by')
  })

  it(`with more than ${PILL_LINKS} links only the hovered and the selected node's links show their pill`, () => {
    expect(build(PILL_LINKS).series[0].edgeLabel.show).toBe(true)
    const many = build(PILL_LINKS + 1, { selected: 'product:3' }).series[0]
    expect(many.edgeLabel.show).toBe(false)
    expect(many.emphasis).toMatchObject({ focus: 'adjacency', edgeLabel: { show: true } })   // under the pointer
    const withPill = many.links.filter((l: any) => l.label?.show).map((l: any) => l.target)
    expect(withPill).toEqual(['product:3'])                                                    // the selected node's link
    const middle = build(PILL_LINKS + 1, { selected: AURORA.id }).series[0]
    expect(middle.links.every((l: any) => l.label?.show)).toBe(true)                           // the middle one: all its links
    expect(build(PILL_LINKS + 1).series[0].links.some((l: any) => l.label)).toBe(false)
  })

  // the box each node fills on the screen: its circle and its card under it (the sizes the layout works with)
  function boxes(option: any) {
    const series = option.series[0]
    return series.data.map((n: any) => {
      const lines = String(series.label.formatter({ data: { id: n.id } })).split('\n').map((line) => line.replace(/^\{\w+\|/, '').replace(/\}$/, ''))
      const width = Math.max(n.symbolSize, ...lines.map((line) => line.length * 6.2 + 20))
      return { id: n.id, left: n.x - width / 2, right: n.x + width / 2, top: n.y - n.symbolSize / 2,
        bottom: n.y + n.symbolSize / 2 + 6 + lines.length * 14 + 10 }
    })
  }
  const touching = (all: ReturnType<typeof boxes>) => all.flatMap((a: any, i: number) => all.slice(i + 1)
    .filter((b: any) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom).map((b: any) => `${a.id} / ${b.id}`))

  it.each([1, 3, 8, 12, 20, 30])('%i nodes sit evenly on rings around the middle and no card lies on another', (count) => {
    const option = build(count)
    const series = option.series[0]
    expect(series.layout).toBe('none')
    expect([series.data[0].x, series.data[0].y]).toEqual([0, 0])
    expect(touching(boxes(option))).toEqual([])
    expect(series.data.every((n: any) => n.label?.show !== false)).toBe(true)        // and every card is shown
    // a ring is an ellipse as wide as the box allows: each node's distance from the middle, as the ring's height
    const aspect = Math.min(1.7, (1100 - 24) / (760 - 52))
    const far: number[] = series.data.slice(1).map((n: any) => Math.hypot(n.x / aspect, n.y)).sort((a: number, b: number) => a - b)
    const rings = far.filter((d, i) => i === 0 || d - far[i - 1] > 10).length
    expect(rings).toBeLessThanOrEqual(4)
    if (count <= 8) {
      expect(rings).toBe(1)                                                          // few nodes: one ring, evenly spaced
      const angles: number[] = series.data.slice(1).map((n: any) => Math.atan2(n.y, n.x / aspect)).sort((a: number, b: number) => a - b)
      angles.slice(1).forEach((angle, i) => expect(angle - angles[i]).toBeCloseTo((2 * Math.PI) / count, 1))
    }
    if (count === 30) expect(rings).toBeGreaterThan(1)                               // many nodes: more than one ring
  })

  it('draws the rings at their own size in the middle of the box, smaller only when they do not fit', () => {
    const big = build(8).series[0]
    const xs = big.data.map((n: any) => n.x)
    const ys = big.data.map((n: any) => n.y)
    expect(big.width).toBeCloseTo(Math.max(...xs) - Math.min(...xs), 0)              // 1 px of the layout = 1 px on the screen
    expect(big.height).toBeCloseTo(Math.max(...ys) - Math.min(...ys), 0)
    expect(big.left).toBeGreaterThan(12)
    expect(big.top).toBeGreaterThan(40)                                              // under the legend
    const small = build(30, { width: 520, height: 420 }).series[0]
    const wide = Math.max(...small.data.map((n: any) => n.x)) - Math.min(...small.data.map((n: any) => n.x))
    expect(small.width).toBeLessThan(wide)                                           // scaled down to fit
    expect(small.left + small.width).toBeLessThanOrEqual(520)
    expect(small.top + small.height).toBeLessThanOrEqual(420)
    const out = small.data.filter((n: any) => n.label?.show === false)
    expect(out.length).toBeGreaterThan(0)                                            // there cards would lie on each other: some are left out
    expect(small.data[0].label?.show).not.toBe(false)                                // never the middle node's
    const zoomed = build(30, { width: 520, height: 420, zoom: 4 }).series[0]         // zoomed in: they have room again
    expect(zoomed.zoom).toBe(4)
    expect(zoomed.data.filter((n: any) => n.label?.show === false).length).toBeLessThan(out.length)
  })

  it('hiddenCards leaves out the later card of two that lie on each other, and none at normal size', () => {
    const blocks = [{ id: 'a', dot: 30, width: 100, height: 36 }, { id: 'b', dot: 30, width: 100, height: 36 }]
    const spots = new Map<string, [number, number]>([['a', [0, 0]], ['b', [200, 0]]])
    expect([...hiddenCards(blocks, spots, 1)]).toEqual([])
    expect([...hiddenCards(blocks, spots, 0.3)]).toEqual(['b'])
  })

  it('nodes already drawn keep their place; new ones (Similar customers) take free places on the rings', () => {
    const first = build(8)
    const kept = new Map<string, [number, number]>(first.series[0].data.map((n: any) => [n.id, [n.x, n.y]]))
    const twins = [node('customer', '12', 'Twin Buyer Ltd', 900), node('customer', '13', 'Other Buyer Ltd', 800)]
    const data = { nodes: [...around(8).nodes, ...twins], edges: [...around(8).edges, ...twins.map((t) => edge(AURORA.id, t.id, 'BUYS_LIKE'))] }
    const option = buildGraphOption(data, readColours(), { center: AURORA.id, width: 1100, height: 760, positions: kept }) as any
    const drawn = option.series[0].data
    for (const n of drawn.slice(0, 9)) expect([n.x, n.y], n.id).toEqual(kept.get(n.id))
    expect(touching(boxes(option))).toEqual([])
    expect(option.series[0].links.find((l: any) => l.kind === 'BUYS_LIKE').lineStyle.type).toBe('dashed')
  })

  it('a phone shows a short name on each node that has room (the whole card when tapped), on a ring that fits', () => {
    const series = build(8, { narrow: true, width: 360, height: 440 }).series[0]
    expect(series.data.every((n: any) => n.label?.show !== false)).toBe(true)          // 8 around: every name fits
    expect(series.label.formatter({ data: { id: 'product:0' } })).toBe('{name|Hydraulic m…}')
    expect(series.select.label.show).toBe(true)
    expect(series.select.label.formatter({ data: { id: 'product:0' } })).toBe('{name|Hydraulic m…}\n{fact|INR 90 L}')
    expect(series.left + series.width).toBeLessThanOrEqual(360)
    // 30 around on a phone: no room for every name - the last way out, the smaller amounts show theirs when tapped
    const crowded = build(30, { narrow: true, width: 360, height: 440 }).series[0]
    const out = crowded.data.filter((n: any) => n.label?.show === false).map((n: any) => n.id)
    expect(out.length).toBeGreaterThan(0)
    expect(out.length).toBeLessThan(30)
    expect(out).not.toContain(AURORA.id)                                               // never the middle node's
    expect(crowded.data.filter((n: any) => n.symbolSize !== 30).map((n: any) => n.id)).toEqual([AURORA.id])
  })
})

describe('the 2D sizes and names (16-Nov: "all same size, dynamic depending how many we have, and names on all")', () => {
  // Aurora with `count` nodes around it: products, and a document page and a similar customer among them
  const mixed = (count: number) => {
    const nodes: GraphNode[] = Array.from({ length: count }, (_, i) =>
      node('product', String(i), `Hydraulic motor HM-${300 + i}-1B`, 9000000 / (i + 1), { sub: `FG${i}` }))
    if (count >= 5) nodes.splice(1, 2, CATALOGUE, SIMILAR.similar[0])
    const edges = nodes.map((n, i) => edge(AURORA.id, n.id, n.type === 'document' ? 'COVERED_BY' : n.type === 'customer' ? 'BUYS_LIKE' : 'BOUGHT', 1000 / (i + 1)))
    return { nodes: [AURORA, ...nodes], edges }
  }
  const build = (count: number, view = {}) =>
    buildGraphOption(mixed(count), readColours(), { center: AURORA.id, width: 1000, height: 580, ...view }) as any
  const text = (line: string) => line.replace(/^\{\w+\|/, '').replace(/\}$/, '')

  it.each([[5, 44], [10, 44], [11, 36], [20, 36], [25, 36], [26, 30], [35, 30]])(
    '%i nodes around the middle: every one is %i px, a document and a similar customer too; the middle one clearly bigger',
    (count, size) => {
      expect(nodeSizeFor(count)).toBe(size)
      const data = build(count).series[0].data
      expect(new Set(data.slice(1).map((n: any) => n.symbolSize))).toEqual(new Set([size]))
      // the middle node's circle (its picture without the soft ring around it) is at least 1.4 times as big
      expect((data[0].symbolSize * 25) / 32).toBeGreaterThan(size * 1.4)
    })

  it('a phone: medium circles up to 10 nodes, small above; the size never follows the amount', () => {
    expect([nodeSizeFor(8, true), nodeSizeFor(11, true)]).toEqual([36, 30])
    const data = build(8, { narrow: true, width: 360, height: 440 }).series[0].data
    expect(new Set(data.slice(1).map((n: any) => n.symbolSize))).toEqual(new Set([36]))
  })

  it(`up to ${FULL_CARDS} nodes a full card (name and fact line); more: the short name, the rest under the pointer`, () => {
    expect([cardModeFor(FULL_CARDS), cardModeFor(FULL_CARDS + 1), cardModeFor(3, true)]).toEqual(['full', 'compact', 'compact'])
    const full = build(FULL_CARDS).series[0]
    for (const n of full.data) expect(full.label.formatter({ data: n }), n.id).toContain('\n{fact|')
    expect(full.label.formatter({ data: { id: 'product:0' } })).toBe('{name|Hydraulic motor H…}\n{fact|INR 90 L}')
    expect(build(10).series[0].label.formatter({ data: { id: 'product:0' } })).toBe('{name|Hydraulic motor HM-300-1B}\n{fact|INR 90 L}')

    const compact = build(FULL_CARDS + 1).series[0]
    const card = (id: string) => compact.label.formatter({ data: { id } })
    for (const n of compact.data.slice(1)) {
      expect(card(n.id), n.id).not.toContain('{fact|')                                 // the name only ...
      expect(text(card(n.id)).length, n.id).toBeLessThanOrEqual(16)                   // ... short
    }
    expect(card('product:0')).toBe('{name|Hydraulic motor…}')
    expect(card(CATALOGUE.id)).toBe('{name|Product Catalog…}')
    expect(card(AURORA.id)).toContain('{fact|INR 2.9 Cr}')                            // the middle node keeps its whole card
    // under the pointer and when selected: the whole card, the amount in it
    expect(compact.emphasis.label.formatter({ data: { id: 'product:0' } })).toBe('{name|Hydraulic motor…}\n{fact|INR 90 L}')
    expect(compact.select.label.formatter({ data: { id: 'product:0' } })).toBe('{name|Hydraulic motor…}\n{fact|INR 90 L}')
    // the amount is never lost: the tooltip has it as the app writes it
    const option = build(30)
    expect(option.tooltip.formatter({ dataType: 'node', data: { id: 'product:29' } })).toContain('3,00,000.00')
    expect(option.tooltip.formatter({ dataType: 'node', data: { id: 'product:29' } })).toContain('Hydraulic motor HM-329-1B')
  })

  // where each card and circle is on the screen: the option's x / y scaled into its frame (ECharts fits the box
  // around the nodes' centres into left / top / width / height), the cards' size as the option measures it
  function onScreen(option: any) {
    const series = option.series[0]
    const xs = series.data.map((n: any) => n.x)
    const ys = series.data.map((n: any) => n.y)
    const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
    const scale = maxX > minX ? series.width / (maxX - minX) : maxY > minY ? series.height / (maxY - minY) : 1
    const { rich } = series.label
    return series.data.map((n: any) => {
      const [x, y] = [(n.x - minX) * scale, (n.y - minY) * scale]
      const lines = String(series.label.formatter({ data: n })).split('\n')
      const style = (line: string) => rich[line.slice(1, line.indexOf('|'))]
      const width = Math.max(...lines.map((line) => textWidth(text(line), style(line).fontSize, style(line).fontWeight >= 600))) + 20
      const height = lines.reduce((sum, line) => sum + style(line).lineHeight, 0) + 12
      const top = y + n.symbolSize / 2 + 6
      return { id: n.id, circle: [x - n.symbolSize / 2, y - n.symbolSize / 2, x + n.symbolSize / 2, y + n.symbolSize / 2],
        card: [x - width / 2, top, x + width / 2, top + height] }
    })
  }
  const lies = (a: number[], b: number[]) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3]

  it.each([...Array.from({ length: 30 }, (_, i) => i + 1), 35])('%i nodes in a 1000 x 580 box: a name on each, no card on another', (count) => {
    const option = build(count)
    const series = option.series[0]
    expect(series.data.filter((n: any) => n.label?.show === false).map((n: any) => n.id)).toEqual([])
    const all = onScreen(option)
    const clash = all.flatMap((a: any, i: number) => all.flatMap((b: any, j: number) => [
      ...(j > i && lies(a.card, b.card) ? [`${a.id} card / ${b.id} card`] : []),
      ...(j !== i && lies(a.card, b.circle) ? [`${a.id} card / ${b.id} circle`] : []),
    ]))
    expect(clash).toEqual([])
    expect(series.left + series.width).toBeLessThanOrEqual(1000)                       // and it is in the box
    expect(series.top + series.height).toBeLessThanOrEqual(580)
  })

  it('a card is left out only from 40 nodes on (the last way out): up to 39 every node keeps its name', () => {
    for (const count of [36, 37, 38, 39]) {
      expect(build(count).series[0].data.filter((n: any) => n.label?.show === false).map((n: any) => n.id), `${count}`).toEqual([])
    }
  })
})

describe('GraphChart zoom buttons (15-Nov): +, - and reset at the top right of the graph box', () => {
  // Aurora with 16 products: more links than get a pill each
  const pumps = Array.from({ length: 16 }, (_, i) => node('product', String(100 + i), `Pump ${i}`, 1000 * (i + 1)))
  const manyLinks = () => replies({
    [AURORA_URL]: { body: { ...AURORA_REPLY, neighbours: pumps, edges: pumps.map((p) => edge(AURORA.id, p.id, 'BOUGHT', 500)), groups: [] } },
    '/api/graph/node?type=product&id=103&limit=25': { body: { ...MOTOR_REPLY, node: pumps[3], neighbours: [AURORA],
      edges: [edge(AURORA.id, pumps[3].id, 'BOUGHT', 500)], groups: [] } },
  })

  it('Zoom in and Zoom out ask ECharts to zoom around the middle; they are not inside the picture', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    const chart = await drawAurora()
    const picture = screen.getByRole('img', { name: /Knowledge graph around/ })
    const zoomIn = screen.getByRole('button', { name: 'Zoom in' })
    expect(picture.contains(zoomIn)).toBe(false)                                    // role="img" would hide it
    expect(picture.parentElement!.contains(zoomIn)).toBe(true)                      // but in the same box
    chart.dispatchAction.mockClear()

    fireEvent.click(zoomIn)
    expect(chart.dispatchAction).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'graphRoam', seriesIndex: 0, zoom: 1.25 }))
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out' }))
    expect(chart.dispatchAction).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'graphRoam', seriesIndex: 0, zoom: 0.8 }))
  })

  it('Reset the view does what Fit does: a new option at normal zoom, the dots where they are', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    const chart = await drawAurora()
    const spots: [number, number][] = [[5, 5], [300, 20], [20, 250], [-200, 40]]
    const ids = nodeIds()
    Object.assign(chart, {
      getModel: () => ({ getSeriesByIndex: () => ({ getData: () => ({
        each: (fn: (i: number) => void) => ids.forEach((_, i) => fn(i)), getItemLayout: (i: number) => spots[i], getId: (i: number) => ids[i],
      }) }) }),
      getOption: () => ({ series: [{ zoom: 2, center: [40, 50] }] }),                // the user zoomed and moved
    })
    const before = chart.option

    fireEvent.click(screen.getByRole('button', { name: 'Reset the view' }))
    const series = chart.option!.series[0]
    expect(chart.option).not.toBe(before)
    expect(series.zoom).toBeUndefined()
    expect(series.center).toBeUndefined()
    expect(series.data.map((n: { x: number; y: number }) => [n.x, n.y])).toEqual(spots)
  })

  it('with many links a click draws the selected node\'s pills and keeps the zoom and the place', async () => {
    fakeFetch(manyLinks())
    renderAt('/graph', <GraphPage />)
    const chart = await drawAurora()
    expect(chart.option!.series[0].edgeLabel.show).toBe(false)                      // 16 links: no pill on each
    Object.assign(chart, { getOption: () => ({ series: [{ zoom: 1.5, center: [10, 20] }] }) })
    const before = chart.option!.series[0].data.map((n: { x: number; y: number }) => [n.x, n.y])

    handler('click')({ dataType: 'node', data: { id: 'product:103' } })
    await waitFor(() => expect(chart.option!.series[0].links.filter((l: any) => l.label?.show).map((l: any) => l.target)).toEqual(['product:103']))
    const series = chart.option!.series[0]
    expect(series.zoom).toBe(1.5)                                                    // the view stays as the user left it
    expect(series.center).toEqual([10, 20])
    expect(series.data.map((n: { x: number; y: number }) => [n.x, n.y])).toEqual(before)
  })

  it('after a zoom the option is built again only when cards were left out or the graph got smaller', async () => {
    fakeFetch(replies())
    renderAt('/graph', <GraphPage />)
    const chart = await drawAurora()
    const before = chart.option
    let zoom = 1.6
    Object.assign(chart, { getOption: () => ({ series: [{ zoom }] }) })

    handler('graphroam')({})                                                        // zoomed in, every card shown: nothing to do
    await new Promise((done) => setTimeout(done, 260))
    expect(chart.option).toBe(before)

    zoom = 0.5                                                                      // zoomed out: cards may lie on each other
    handler('graphroam')({})
    await waitFor(() => expect(chart.option).not.toBe(before))
    expect(chart.option!.series[0].zoom).toBe(0.5)
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

describe('GraphPage smarter search (05-Nov): type words, close spellings, Ask the Assistant instead - no AI while typing', () => {
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
    expect(screen.queryByRole('link', { name: /Ask the Assistant instead/ })).not.toBeInTheDocument()
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
    expect(screen.queryByRole('link', { name: /Ask the Assistant instead/ })).not.toBeInTheDocument()
  })

  it('only when nothing is found: "Ask the Assistant instead" links to /new?q=<the text>', async () => {
    fakeFetch(replies({
      '/api/graph/search?q=blue+widgets+%26+more': { body: { q: 'blue widgets & more', results: [] } },
    }))
    renderAt('/graph', <GraphPage />)
    expect(screen.queryByRole('link', { name: /Ask the Assistant instead/ })).not.toBeInTheDocument()
    fireEvent.change(box(), { target: { value: 'blue widgets & more' } })
    expect(await screen.findByText('Nothing found for "blue widgets & more".')).toBeInTheDocument()
    const ask = screen.getByRole('link', { name: /Ask the Assistant instead/ })
    expect(ask).toHaveAttribute('href', '/new?q=blue%20widgets%20%26%20more')
    fireEvent.change(box(), { target: { value: '' } })                              // cleared: the link goes
    expect(screen.queryByRole('link', { name: /Ask the Assistant instead/ })).not.toBeInTheDocument()
    expect(screen.getByText(SEARCH_HINT)).toBeInTheDocument()
  })

  it('"Ask the Assistant instead" only fills the question box - nothing is sent until Ask is pressed', async () => {
    const fetch = fakeFetch({ '/api/me': { body: ASHA }, '/api/graph/search?q=blue+widgets': { body: { q: 'blue widgets', results: [] } } })
    window.history.pushState(null, '', '/graph')
    render(<App />)
    fireEvent.change(await screen.findByRole('combobox', { name: 'Search' }, { timeout: 4000 }), { target: { value: 'blue widgets' } })
    fireEvent.click(await screen.findByRole('link', { name: /Ask the Assistant instead/ }))
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
