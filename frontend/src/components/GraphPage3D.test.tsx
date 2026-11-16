// Knowledge graph, the 3D view (05-Nov): the switch and its memory, WebGL missing, the look (16-Nov: a disc with
// its type's icon for each node, all one size by how many there are, the middle one bigger; a label card on every
// node - full up to 15 around the middle one, short above that, full on hover / select; the first places keep the
// cards clear of each other, the layout's forces grow with the count; pills on the hovered or selected node's
// links, thin light lines, the three zoom buttons), a click
// selects (on the middle node: back), two quick clicks go in, the balls can be dragged, the wheel zooms only near
// the nodes, Fit (the first picture back: each ball glides to where it was when the layout first settled, the
// middle one pinned at the centre, nothing laid out again), full screen, Similar customers keeps the nodes in place,
// the theme (light / dark: the scene's colours change, the balls stay), and leaving 3D takes the library apart. 3d-force-graph is a fake (test/fakeForceGraph.ts): jsdom has no WebGL, so
// the tests check what it is given; the frames of Fit's move are run by hand (handFrames).
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Group, type Sprite } from 'three'
import { cutName, factLine } from '../charts/graphLook'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type FakeForceGraph, graphs, lastGraph } from '../test/fakeForceGraph'
import { readColours } from '../charts/chartOption'
import { FULL_CARDS, MIDDLE_DISC, type Placing, SHORT_NAME, discSize, layoutUnit, placeNodes, startDistance } from '../charts/Graph3D'
import { charts, lastChart } from '../test/fakeEcharts'
import { fakeFetch } from '../test/fakeFetch'
import { renderAt } from '../test/render'
import type { GraphEdge, GraphNode, GraphNodeReply, GraphSimilarReply } from '../types'
import GraphPage, { NO_WEBGL } from './GraphPage'
import { TYPE_COLOURS, forgetGraphPage } from './graphData'

vi.mock('../charts/echarts', () => import('../test/fakeEcharts'))
vi.mock('../charts/echartsGraph', () => ({}))
vi.mock('3d-force-graph', () => import('../test/fakeForceGraph'))

function node(type: GraphNode['type'], key: string, label: string, amount: number | null, extra: Partial<GraphNode> = {}): GraphNode {
  return { id: `${type}:${key}`, type, type_name: type, key, label, sub: '', amount,
    amount_text: amount === null ? '' : amount.toLocaleString('en-IN', { minimumFractionDigits: 2 }), ...extra }
}

function edge(source: string, target: string, type: string, amount?: number): GraphEdge {
  return { id: `${source}|${type}|${target}`, source, target, type,
    ...(amount === undefined ? {} : { amount, amount_text: amount.toLocaleString('en-IN', { minimumFractionDigits: 2 }) }) }
}

const PERIOD = { fy: '', label: 'All data up to today', from: '21-Dec-2025', to: '04-Nov-2026', so_far: true,
  text: 'All data up to today (21-Dec-2025 to 04-Nov-2026)' }
const AURORA = node('customer', '3680', 'Aurora Hydraulics Private Limited', 29088275)
const MOTOR = node('product', '45', 'Hydraulic motor HM-346-1B', 9000000)
const PRIYA = node('sales_person', '4', 'Priya Iyer', 180984185.5)
const TAMIL = node('state', 'Tamil Nadu', 'Tamil Nadu', 468912301.5)
const HYDRAULIC = node('category', 'Hydraulic motors', 'Hydraulic motors', 621565971)
const CATALOGUE = node('document', 'product_catalogue.pdf#2', 'Product Catalogue, page 2', null)

const AURORA_REPLY: GraphNodeReply = {
  node: AURORA, period: PERIOD, neighbours: [MOTOR, PRIYA, TAMIL],
  edges: [edge(AURORA.id, MOTOR.id, 'BOUGHT', 1250000), edge(AURORA.id, PRIYA.id, 'HANDLED_BY', 29000000),
    edge(AURORA.id, TAMIL.id, 'IN_STATE', 29088275)],
  groups: [], notes: [],
}
const MOTOR_REPLY: GraphNodeReply = {
  node: MOTOR, period: PERIOD, neighbours: [AURORA, HYDRAULIC, CATALOGUE],
  edges: [edge(AURORA.id, MOTOR.id, 'BOUGHT', 1250000), edge(MOTOR.id, HYDRAULIC.id, 'IN_CATEGORY', 9000000),
    { ...edge(MOTOR.id, CATALOGUE.id, 'COVERED_BY'), mentions: 8 }],
  groups: [], notes: [],
}
const SIMILAR: GraphSimilarReply = {
  customer: AURORA, period: PERIOD, products: 105,
  similar: [node('customer', '12', 'Twin Buyer Ltd', 900, { shared_products: 40, score_text: '38%' })],
  edges: [{ ...edge(AURORA.id, 'customer:12', 'BUYS_LIKE'), shared_products: 40, score_text: '38%' }],
}
const REPLIES = {
  '/api/graph/search?q=Aurora': { body: { q: 'Aurora', results: [AURORA] } },
  '/api/graph/node?type=customer&id=3680&limit=25': { body: AURORA_REPLY },
  '/api/graph/node?type=product&id=45&limit=25': { body: MOTOR_REPLY },
  '/api/graph/similar?customer_id=3680': { body: SIMILAR },
}
const AURORA_ONLY = ['customer:3680', 'product:45', 'sales_person:4', 'state:Tamil Nadu']
const MOTOR_ONLY = ['product:45', 'customer:3680', 'category:Hydraulic motors', 'document:product_catalogue.pdf#2']

let webgl = true
let textWidth = 60 // px: how wide the canvas measures every text (a card's lines)
// a 2D canvas that draws nothing (the names and rings are drawn on small canvases)
const paint = new Proxy({ measureText: () => ({ width: textWidth }) } as Record<string, unknown>, {
  get: (target, name) => (name in target ? target[name as string] : () => {}),
  set: () => true,
})
let clock = 100000 // Date.now in these tests: each click moves it on by hand

beforeEach(() => {
  webgl = true
  textWidth = 60
  clock = 100000
  // jsdom has no canvas: a WebGL context only when the test says the browser has one
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(((kind: string) =>
    (kind === '2d' ? paint : webgl && kind.startsWith('webgl') ? { getExtension: () => ({ loseContext: () => {} }) } : null)) as never)
  vi.spyOn(Date, 'now').mockImplementation(() => clock)
})
afterEach(() => {
  graphs.length = 0
  charts.length = 0
  document.documentElement.removeAttribute('data-theme')
})

type Spot = [number, number, number]

/** Puts nodes at these places (as the layout or a drag would); pinned: held there too (fx, fy, fz). */
function place(graph: FakeForceGraph, spots: Record<string, Spot>, pinned: string[] = []) {
  for (const [id, [x, y, z]] of Object.entries(spots)) {
    Object.assign(graph.node(id), { x, y, z, vx: 2, vy: -1, vz: 1 })
    if (pinned.includes(id)) Object.assign(graph.node(id), { fx: x, fy: y, fz: z })
  }
}

const at = (n: { x: number; y: number; z: number }): Spot => [n.x, n.y, n.z]

/** requestAnimationFrame by hand: frame(ms) runs the frames waiting, ms after the last one; finish() runs them
 *  (16 ms apart) until none is left. */
function handFrames() {
  let next = 1
  let now = 1000
  const waiting = new Map<number, FrameRequestCallback>()
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    waiting.set(next, callback)
    return next++
  })
  vi.stubGlobal('cancelAnimationFrame', (id: number) => { waiting.delete(id) })
  const frame = (ms = 16) => {
    now += ms
    const due = [...waiting.values()]
    waiting.clear()
    due.forEach((callback) => callback(now))
  }
  return {
    waiting: () => waiting.size,
    frame,
    finish() {
      for (let i = 0; i < 500 && waiting.size; i++) frame()
    },
  }
}

// where the layout first settled around Aurora (the first picture); Aurora is pinned at the centre
const FIRST: Record<string, Spot> = { [MOTOR.id]: [40, -20, 10], [PRIYA.id]: [-35, 15, -5], [TAMIL.id]: [5, 30, 20] }
// the picture went lopsided: Aurora dragged far to the left (and pinned there, as the library leaves a dragged
// middle node), the others bunched on the right, Priya pinned
const LOPSIDED: Record<string, Spot> = { [AURORA.id]: [-300, 50, 0], [MOTOR.id]: [60, -20, 10], [PRIYA.id]: [90, 15, -5],
  [TAMIL.id]: [70, 25, 20] }
const CENTRE = { x: 0, y: 0, z: 0 }
const HIGH = 580 - 28                                                          // the drawing's height (less the legend)
const START = { x: 0, y: 0, z: startDistance(3, HIGH) }                        // straight in front, for 3 around the middle

async function drawAurora() {
  fireEvent.change(screen.getByRole('combobox', { name: 'Search' }), { target: { value: 'Aurora' } })
  fireEvent.click(await screen.findByRole('option', { name: /Aurora Hydraulics Private Limited/ }))
  await screen.findByRole('navigation', { name: 'Path' })
}

/** Into 3D, and waits for the graph to get its data. */
async function into3d() {
  fireEvent.click(screen.getByRole('button', { name: '3D view' }))
  await waitFor(() => expect(lastGraph()?.ids()).toEqual(AURORA_ONLY))
  return lastGraph()
}

/** count pumps (and nothing else) around Aurora, the first one the biggest. */
function pumpsAround(count: number): GraphNode[] {
  return Array.from({ length: count }, (_, i) => node('product', `9${i}`, `Trochoid pump TP-${i}`, (count - i) * 1e6))
}

/** Aurora with these nodes around it, in 3D; view.unmount() leaves the page. */
async function into3dWith(around: GraphNode[]) {
  fakeFetch({ ...REPLIES, '/api/graph/node?type=customer&id=3680&limit=25': { body: { ...AURORA_REPLY,
    neighbours: around, edges: around.map((one) => edge(AURORA.id, one.id, 'BOUGHT', 500)) } } })
  const view = renderAt('/graph', <GraphPage />)
  await drawAurora()
  fireEvent.click(screen.getByRole('button', { name: '3D view' }))
  await waitFor(() => expect(lastGraph()?.ids()).toHaveLength(around.length + 1))
  return { graph: lastGraph(), view }
}

/** Leaves the page and forgets it (as between two tests): the next into3dWith starts afresh. */
function leave(view: { unmount: () => void }) {
  view.unmount()
  forgetGraphPage()
  window.localStorage.clear()
  window.history.replaceState(null, '', '/')
}

const FOCAL = HIGH /(2 * Math.tan((50 * Math.PI) / 360)) // px per graph unit, at a distance of 1 (the camera's fov: 50)

/** Where the camera (straight in front of the middle) shows a node: px from the middle (y up), its disc's radius in
 *  px, and px per graph unit at its depth. */
function seen(graph: FakeForceGraph, item: { x: number; y: number; z: number; r: number }) {
  const k = FOCAL / (graph.cam.position.z - item.z)
  return { x: item.x * k, y: item.y * k, r: item.r * k, k }
}

const cardsOf = (group: Group) => group.children.filter((child) => child.userData.kind === 'card') as Sprite[]

/** True when no node's disc and shown card cover another's on the screen (the camera straight in front). */
function clearOfEachOther(graph: FakeForceGraph, made: Map<string, Group>): boolean {
  const boxes = [...made].map(([id, group]) => {
    const { x, y, r, k } = seen(graph, graph.node(id))
    const card = cardsOf(group).find((one) => one.visible)!
    const top = y - card.userData.below * k - 5 // the card hangs 5 px under its point
    const half = Math.max(r, card.userData.width / 2)
    return { left: x - half, right: x + half, top: y + r, bottom: top - card.userData.height }
  })
  return boxes.every((a, i) => boxes.slice(i + 1).every((b) => a.right <= b.left + 0.5 || b.right <= a.left + 0.5
    || a.top <= b.bottom + 0.5 || b.top <= a.bottom + 0.5))
}

describe('GraphPage 3D view', () => {
  it('the switch shows the same graph in 3D and back in 2D; the choice is kept in this browser', async () => {
    fakeFetch(REPLIES)
    const first = renderAt('/graph', <GraphPage />)
    await drawAurora()
    expect(screen.getByRole('button', { name: '3D view' })).toHaveAttribute('aria-pressed', 'false')

    const graph = await into3d()
    expect(screen.getByRole('button', { name: '2D view' })).toHaveAttribute('aria-pressed', 'true')
    expect(window.localStorage.getItem('mi.graphView')).toBe('3d')
    expect(screen.getByRole('img', { name: /Knowledge graph around Aurora Hydraulics Private Limited: 4 nodes.*Drawn in 3D/ }))
      .toBeInTheDocument()
    expect(graph.config).toEqual({ controlType: 'orbit' })                     // drag turns it around the middle
    expect(graph.props.enableNodeDrag).toBe(true)                               // a ball can be dragged
    expect(graph.dragOnData[0]).toBe(true)                                      // (on before the data is drawn)
    expect(graph.props.backgroundColor).toBe('#F8F9FB')                         // the light box (bg-muted)
    // the colours of 2D for a node's type; the links are thin, light lines in the theme's muted colour
    expect(graph.props.nodeColor(graph.node(AURORA.id))).toBe(TYPE_COLOURS.customer)
    expect(graph.props.nodeColor(graph.node(MOTOR.id))).toBe(TYPE_COLOURS.product)
    expect(graph.data.links).toHaveLength(3)
    for (const link of graph.data.links) {
      expect(graph.props.linkColor(link)).toBe(readColours('light').muted)
      expect(graph.props.linkDirectionalArrowColor(link)).toBe(readColours('light').muted)
      expect(graph.props.linkWidth(link)).toBeGreaterThan(0)
      expect(graph.props.linkWidth(link)).toBeLessThan(1)                       // thin
    }
    expect(graph.props.nodeThreeObjectExtend).toBeUndefined()                   // our own discs, not the library's balls
    expect(graph.node(AURORA.id)).toMatchObject({ fx: 0, fy: 0, fz: 0 })      // the middle node at the centre
    expect(graph.node(AURORA.id).r).toBeGreaterThan(graph.node(MOTOR.id).r)  // the middle node bigger
    expect(graph.props.nodeLabel(graph.node(MOTOR.id))).toContain('Hydraulic motor HM-346-1B') // the hover tooltip
    expect(screen.getByText('Customer')).toBeInTheDocument()                    // the legend

    first.unmount()                                                             // another page and back: 3D again
    expect(graph.destroyed).toBe(true)
    renderAt('/graph', <GraphPage />)
    await waitFor(() => expect(graphs).toHaveLength(2))
    await waitFor(() => expect(lastGraph().ids()).toEqual(AURORA_ONLY))

    const again = lastGraph()
    fireEvent.click(screen.getByRole('button', { name: '2D view' }))
    await waitFor(() => expect(lastChart()?.types()).toEqual(['graph']))      // the 2D chart, as before
    expect(again.destroyed).toBe(true)                                          // the 3D one taken apart
    expect(again.pauseAnimation).toHaveBeenCalled()                             // no loop left running
    expect(again.renderer().forceContextLoss).toHaveBeenCalled()               // the WebGL context freed
    expect(again.element.childElementCount).toBe(0)
    expect(window.localStorage.getItem('mi.graphView')).toBeNull()
  })

  it('cards the middle node and rings the middle and the selected node; the ring follows the selection', async () => {
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const graph = await into3d()
    const made = (id: string) => graph.props.nodeThreeObject(graph.node(id)) as Group  // as the library asks for it
    const shown = (group: Group) => group.children.map((child) => child.visible)

    const aurora = made(AURORA.id)
    expect(aurora).toBeInstanceOf(Group)
    expect(aurora.renderOrder).toBe(20)                                         // drawn after the links
    expect(shown(aurora)).toEqual([true, true, true, true])                     // its disc, its card, the soft ring, the dark ring
    expect(aurora.children.map((child) => child.userData.kind)).toEqual(['icon', 'card', 'ring', 'ring'])
    const label = aurora.children[1] as Sprite
    expect(label.position.y).toBeLessThan(-graph.node(AURORA.id).r)             // under the disc and its soft ring
    expect(label.scale.y).toBeGreaterThan(0)
    expect(label.material.sizeAttenuation).toBe(false)                          // the same size on the screen at any zoom
    // turned: "under" follows the camera's own up (here the camera lies on its side: its up is the graph's -x)
    const below = label.userData.below as number
    label.onBeforeRender(null as never, null as never, { quaternion: { x: 0, y: 0, z: Math.SQRT1_2, w: Math.SQRT1_2 } } as never,
      null as never, null as never, null as never)
    expect(label.position.x).toBeCloseTo(below)
    expect(label.position.y).toBeCloseTo(0)

    const motor = made(MOTOR.id)
    graph.click(MOTOR.id)                                                       // select the motor
    await within(screen.getByRole('complementary', { name: 'Node details' })).findByText('INR 90,00,000.00')
    await waitFor(() => expect(shown(aurora)).toEqual([true, true, true, false])) // the dark ring moved ...
    expect(aurora.children[3].layers.isEnabled(0)).toBe(false)                  // (hidden: no hover or click on it)
    expect(shown(motor)).toEqual([true, true, true])                            // ... to the motor (disc, card, ring)
  })

  it('every node is a disc with the icon of its type; the middle one is bigger and blue with a soft ring', async () => {
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const graph = await into3d()
    const light = readColours('light')
    const made = new Map(AURORA_ONLY.map((id) => [id, graph.props.nodeThreeObject(graph.node(id)) as Group]))
    for (const id of AURORA_ONLY) {
      const item = graph.node(id)
      const icon = made.get(id)!.children[0] as Sprite
      expect(icon.userData).toMatchObject({ kind: 'icon', type: item.node.type })
      expect(icon.userData.colour).toBe(id === AURORA.id ? light.series[0] : TYPE_COLOURS[item.node.type as GraphNode['type']])
      expect(icon.visible).toBe(true)
      expect([icon.scale.x, icon.scale.y]).toEqual([item.r * 2, item.r * 2])    // as big as the node
      expect(icon.material.depthTest).toBe(false)                               // drawn over the links
    }
    const types = AURORA_ONLY.map((id) => (made.get(id)!.children[0] as Sprite).userData.type)
    expect(types).toEqual(['customer', 'product', 'sales_person', 'state'])
    // the middle node: a MIDDLE_DISC px disc in the first picture (1 px there = layoutUnit), the others discSize
    expect(graph.node(AURORA.id).r).toBeCloseTo((MIDDLE_DISC / 2) * layoutUnit(3))
    expect(MIDDLE_DISC).toBeGreaterThan(discSize(3))
    const halo = made.get(AURORA.id)!.children[2] as Sprite
    expect(halo.userData.kind).toBe('ring')
    expect(halo.scale.x).toBeGreaterThan(graph.node(AURORA.id).r * 2)           // around the disc
    expect(made.get(MOTOR.id)!.children.map((child) => child.userData.kind)).toEqual(['icon', 'card'])
  })

  it('every disc around the middle one is the same size, by how many there are (5 / 20 / 35); the middle one bigger', async () => {
    const sizes: number[] = []
    for (const count of [5, 20, 35]) {
      const { graph, view } = await into3dWith(pumpsAround(count))
      const ids: string[] = graph.ids()
      expect(graph.cam.position.z).toBeCloseTo(startDistance(count, HIGH))      // the camera of the first picture
      const outer = ids.filter((id) => id !== AURORA.id).map((id) => seen(graph, graph.node(id)).r)
      // the same on the screen (a disc nearer the camera is drawn a little smaller), not by amount: big pumps too
      for (const r of outer) expect(r).toBeCloseTo(discSize(count) / 2)
      expect(seen(graph, graph.node(AURORA.id)).r).toBeCloseTo(MIDDLE_DISC / 2)
      const depths = new Set(ids.map((id) => Math.round(graph.node(id).z)))
      expect(depths.size).toBeGreaterThan(2)                                    // at different depths: it is 3D
      for (const id of ids) {
        const icon = (graph.props.nodeThreeObject(graph.node(id)) as Group).children[0] as Sprite
        expect(icon.scale.x).toBeCloseTo(graph.node(id).r * 2)                  // the disc as big as the node
      }
      sizes.push(outer[0])
      leave(view)
    }
    expect(sizes[0]).toBeGreaterThan(sizes[1])                                 // fewer nodes, bigger discs
    expect(sizes[1]).toBeGreaterThan(sizes[2])
    expect([discSize(1), discSize(10), discSize(11), discSize(25), discSize(26), discSize(40)]).toEqual([40, 40, 32, 32, 26, 26])
    expect(MIDDLE_DISC).toBeGreaterThan(discSize(1))
  })

  it('a card on every node: name and fact line up to 15 around the middle one, all clear of each other', async () => {
    const pumps = pumpsAround(FULL_CARDS)
    const { graph } = await into3dWith(pumps)
    const ids: string[] = graph.ids()
    const made = new Map(ids.map((id) => [id, graph.props.nodeThreeObject(graph.node(id)) as Group]))
    for (const id of ids) {
      const cards = cardsOf(made.get(id)!)
      expect(cards).toHaveLength(1)                                             // one card, shown
      expect(cards[0].visible).toBe(true)
      const item = graph.node(id).node as GraphNode
      expect(cards[0].userData).toMatchObject({ short: false, name: cutName(item.label, 26), fact: factLine(item) })
    }
    expect(cardsOf(made.get(AURORA.id)!)[0].userData.name).toBe('Aurora Hydraulics Private…')
    expect(factLine(pumps[0])).toMatch(/^INR /)
    expect(clearOfEachOther(graph, made)).toBe(true)                            // the first picture: no card covers another
    graph.hover(pumps[3].id)                                                    // the mouse over one: the same card
    expect(cardsOf(made.get(pumps[3].id)!)).toHaveLength(1)
  })

  it('more than 15: a short card (the name only) on each, the full one on hover or select; the middle one always full', async () => {
    const pumps = pumpsAround(20)
    const { graph } = await into3dWith(pumps)
    const ids: string[] = graph.ids()
    const made = new Map(ids.map((id) => [id, graph.props.nodeThreeObject(graph.node(id)) as Group]))
    const middle = cardsOf(made.get(AURORA.id)!)
    expect(middle).toHaveLength(1)
    expect(middle[0].userData).toMatchObject({ short: false, fact: factLine(AURORA) })
    for (const pump of pumps) {
      const cards = cardsOf(made.get(pump.id)!)
      expect(cards).toHaveLength(1)                                             // the full one is made only when needed
      expect(cards[0].visible).toBe(true)
      expect(cards[0].userData).toMatchObject({ short: true, name: cutName(pump.label, SHORT_NAME), fact: '' })
    }
    expect(cutName(pumps[0].label, SHORT_NAME)).toBe('Trochoid pump…')
    expect(clearOfEachOther(graph, made)).toBe(true)

    const shown = (id: string) => cardsOf(made.get(id)!).filter((card) => card.visible).map((card) => card.userData.short)
    const [one, two] = pumps
    graph.hover(one.id)                                                         // the mouse over one: its full card
    expect(shown(one.id)).toEqual([false])
    const full = cardsOf(made.get(one.id)!).find((card) => !card.userData.short)!
    expect(full.userData).toMatchObject({ name: one.label, fact: factLine(one) })
    graph.hover(two.id)                                                         // on to the next: the first is short again
    expect(shown(one.id)).toEqual([true])
    expect(full.layers.isEnabled(0)).toBe(false)                                // (hidden: no hover or click on it)
    expect(shown(two.id)).toEqual([false])
    graph.hover(null)
    expect(shown(two.id)).toEqual([true])
    expect(cardsOf(made.get(one.id)!)).toContain(full)                          // kept for the next time

    graph.click(one.id)                                                         // selected: full without the mouse
    await waitFor(() => expect(shown(one.id)).toEqual([false]))
    expect(cardsOf(made.get(one.id)!)).toContain(full)                          // the same one, not made again
    clock += 1000
    graph.click(two.id)
    await waitFor(() => expect(shown(one.id)).toEqual([true]))
    expect(shown(two.id)).toEqual([false])
    expect(shown(AURORA.id)).toEqual([false])                                   // the middle one: always the full card

    // leaving 3D frees every card (the short and the full ones), disc and ring
    const sprites = [...made.values()].flatMap((group) => group.children) as Sprite[]
    expect(sprites.length).toBeGreaterThan(2 * 21)
    const freed = sprites.flatMap((sprite) => [vi.spyOn(sprite.material, 'dispose'), vi.spyOn(sprite.material.map!, 'dispose')])
    fireEvent.click(screen.getByRole('button', { name: '2D view' }))
    await waitFor(() => expect(graph.destroyed).toBe(true))
    for (const spy of freed) expect(spy).toHaveBeenCalled()
    for (const group of made.values()) expect(group.children).toHaveLength(0)
  })

  it('full cards that do not fit the drawing clear of each other: short ones, though 15 or fewer', async () => {
    textWidth = 500                                                             // very long lines
    const { graph } = await into3dWith(pumpsAround(12))
    const made = new Map((graph.ids() as string[]).map((id) => [id, graph.props.nodeThreeObject(graph.node(id)) as Group]))
    for (const [id, group] of made) expect(cardsOf(group)[0].userData.short).toBe(id !== AURORA.id)
  })

  it('more nodes, more room: longer links, a stronger push; Fit brings back the first picture of the new places', async () => {
    const lengths: number[] = []
    const pushes: number[] = []
    for (const count of [5, 20, 35]) {
      const { graph, view } = await into3dWith(pumpsAround(count))
      const links = graph.data.links
      // each link as long as its two ends' places are apart (the layout holds them there)
      for (const link of links) {
        const [a, b] = [graph.node(link.source), graph.node(link.target)]
        expect(graph.linkLength(link)).toBeCloseTo(Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z))
      }
      lengths.push(links.reduce((sum: number, link: unknown) => sum + graph.linkLength(link), 0) / links.length)
      pushes.push(-graph.forces.charge.strength.mock.lastCall[0])
      expect(graph.forces.charge.distanceMax).toHaveBeenCalled()                // a short-range push
      expect(graph.forces.home).toBeTypeOf('function')                          // each ball pulled to its own place
      expect(graph.forces.center).toBeUndefined()                               // (the middle node is pinned instead)
      leave(view)
    }
    expect(lengths[1]).toBeGreaterThan(lengths[0])
    expect(lengths[2]).toBeGreaterThan(lengths[1])
    expect(pushes[1]).toBeGreaterThan(pushes[0])
    expect(pushes[2]).toBeGreaterThan(pushes[1])

    // Fit: the first picture is where the balls were spread out when the layout first settled
    const { graph } = await into3dWith(pumpsAround(20))
    const ids: string[] = graph.ids()
    const first = new Map(ids.map((id) => [id, at(graph.node(id))]))
    graph.settle()
    const start = { ...graph.cam.position }
    ids.forEach((id, i) => Object.assign(graph.node(id), { x: i, y: -i, z: 2 * i }))   // all moved about
    graph.cam.position = { x: 300, y: 0, z: 10 }
    const frames = handFrames()
    fireEvent.click(screen.getByRole('button', { name: 'Fit' }))
    frames.finish()
    for (const id of ids) at(graph.node(id)).forEach((value, i) => expect(value).toBeCloseTo(first.get(id)![i], 9))
    expect(graph.cam.position).toEqual(start)

    // a ball dropped somewhere: its link as long as its new place asks
    const pump = graph.node(ids[1])
    Object.assign(pump, { x: 200, y: 50, z: 0 })
    graph.props.onNodeDragEnd(pump, { x: 0, y: 0, z: 0 })
    const link = graph.data.links.find((l: { edge: GraphEdge }) => l.edge.target === pump.id)
    expect(graph.linkLength(link)).toBeCloseTo(Math.hypot(200, 50))
  })

  it('the first places keep every card clear of the others, up to 30 nodes on a laptop-sized drawing', () => {
    // cards as wide as real names: 7 px a letter (bold 12 px), full up to 15 nodes, short above
    for (const count of [5, 10, 15, 20, 25, 30]) {
      const short = count > FULL_CARDS
      const disc = discSize(count)
      const items: Placing[] = [{ fixed: true, x: 0, y: 0, room: { side: 101, up: 34, down: 84 } }] // the middle node
      for (let i = 0; i < count; i++) {
        const letters = Math.min(short ? SHORT_NAME : 26, 9 + ((i * 7) % 20))
        const room = { side: Math.max(disc / 2, (letters * 7 + 20) / 2), up: disc / 2, down: disc / 2 + 5 + (short ? 24 : 40) }
        items.push({ fixed: false, x: 0, y: 0, room })
      }
      expect(placeNodes(items, 800, HIGH)).toBe(0)
      for (const [i, a] of items.entries()) {
        expect(Math.abs(a.x) + a.room.side).toBeLessThanOrEqual(400)            // inside the drawing
        expect(a.y + a.room.up).toBeLessThanOrEqual(HIGH / 2)
        expect(a.room.down - a.y).toBeLessThanOrEqual(HIGH / 2)
        for (const b of items.slice(i + 1)) {
          const apart = Math.abs(a.x - b.x) >= a.room.side + b.room.side
            || a.y - a.room.down >= b.y + b.room.up || b.y - b.room.down >= a.y + a.room.up
          expect(apart).toBe(true)
        }
      }
    }
  })

  it('link pills name only the links of the hovered or the selected node, in the middle of each link', async () => {
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const graph = await into3d()
    place(graph, FIRST)
    const holder = graph.stage.children.find((child) => child instanceof Group) as Group
    expect(holder.renderOrder).toBe(30)                                         // over the links and the nodes
    const words = () => holder.children.map((pill) => pill.userData.text).sort()
    expect(words()).toEqual([])                                                 // none at first: never all at once

    graph.hover(MOTOR.id)
    expect(words()).toEqual(['Bought'])                                         // its one link, in plain words
    const pill = holder.children[0] as Sprite
    expect(pill.position.toArray()).toEqual([20, -10, 5])                       // half-way between Aurora and the motor
    expect(pill.material.sizeAttenuation).toBe(false)
    Object.assign(graph.node(MOTOR.id), { x: 100, y: 40, z: -20 })              // the motor is dragged: the pill follows
    graph.moveLinks()
    expect(pill.position.toArray()).toEqual([50, 20, -10])
    expect(graph.props.linkPositionUpdate({}, { start: CENTRE, end: CENTRE }, graph.data.links[0])).toBe(false) // the line is the library's
    graph.moveLinks()

    graph.hover(AURORA.id)                                                      // the middle node: all three of its links
    expect(words()).toEqual(['Bought', 'Handled by', 'In state'])
    expect(holder.children).toContain(pill)
    const freed = vi.spyOn(pill.material, 'dispose')
    graph.hover(null)
    expect(words()).toEqual([])
    expect(freed).toHaveBeenCalled()                                            // a pill taken away is freed

    graph.click(PRIYA.id)                                                       // selected: named without the mouse
    await waitFor(() => expect(words()).toEqual(['Handled by']))
    graph.hover(TAMIL.id)
    expect(words()).toEqual(['Handled by', 'In state'])
    graph.hover(null)
    expect(words()).toEqual(['Handled by'])
  })

  it('the zoom buttons: + and - move the camera towards and away from the centre, reset does what Fit does', async () => {
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const graph = await into3d()
    place(graph, FIRST)
    graph.settle()
    const zoomIn = screen.getByRole('button', { name: 'Zoom in' })
    const zoomOut = screen.getByRole('button', { name: 'Zoom out' })
    const reset = screen.getByRole('button', { name: 'Reset the view' })
    const picture = screen.getByRole('img', { name: /Drawn in 3D/ })
    for (const button of [zoomIn, zoomOut, reset]) {
      expect(picture.parentElement).toContainElement(button)                    // inside the 3D box ...
      expect(picture).not.toContainElement(button)                              // ... beside the picture, not in it
    }
    expect(screen.getByRole('button', { name: 'Fit' })).toBeInTheDocument()     // Fit and Download PNG stay
    expect(screen.getByRole('button', { name: 'Download PNG' })).toBeInTheDocument()
    const drawn = graph.dragOnData.length

    expect(graph.cam.position).toEqual(START)
    fireEvent.click(zoomIn)                                                     // 22% closer, in one short move
    expect(graph.cameraPosition).toHaveBeenLastCalledWith({ x: 0, y: 0, z: START.z * 0.78 }, CENTRE, 250)
    fireEvent.click(zoomOut)                                                    // and back
    expect(graph.cam.position.z).toBeCloseTo(START.z)
    fireEvent.click(zoomOut)
    expect(graph.cam.position.z).toBeCloseTo(START.z / 0.78)

    graph.cam.position = { x: 110, y: 20, z: 0 }                                // turned, and moved with a right-drag:
    graph.cam.lookAt = { x: 10, y: 20, z: 0 }                                   // towards the point it turns around
    fireEvent.click(zoomIn)
    expect(graph.cam.position.x).toBeCloseTo(10 + 100 * 0.78)
    expect(graph.cam).toMatchObject({ position: { y: 20, z: 0 }, lookAt: { x: 10, y: 20, z: 0 } })

    graph.cam.position = { x: 10, y: 20, z: 32 }                                // the limits: not closer than 30 ...
    fireEvent.click(zoomIn)
    expect(graph.cam.position.z).toBeCloseTo(30)
    fireEvent.click(zoomIn)
    expect(graph.cam.position.z).toBeCloseTo(30)
    graph.cam.position = { x: 10, y: 20, z: 2900 }                              // ... not further than 3000
    fireEvent.click(zoomOut)
    expect(graph.cam.position.z).toBeCloseTo(3000)
    expect(graph.dragOnData.length).toBe(drawn)                                 // the graph is not given again
    expect(graph.d3ReheatSimulation).not.toHaveBeenCalled()

    place(graph, LOPSIDED, [AURORA.id])                                         // reset: the first picture back, as Fit
    const frames = handFrames()
    fireEvent.click(reset)
    expect(graph.cameraPosition).toHaveBeenLastCalledWith(START, CENTRE, 800)
    expect(graph.cam).toMatchObject({ position: START, lookAt: CENTRE })
    frames.finish()
    expect(graph.node(AURORA.id)).toMatchObject({ ...CENTRE, fx: 0, fy: 0, fz: 0 })
    for (const [id, spot] of Object.entries(FIRST)) expect(at(graph.node(id))).toEqual(spot)
  })

  it('leaving 3D frees every disc, card, ring and pill', async () => {
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const graph = await into3d()
    const groups = AURORA_ONLY.map((id) => graph.props.nodeThreeObject(graph.node(id)) as Group)
    const holder = graph.stage.children.find((child) => child instanceof Group) as Group
    graph.hover(MOTOR.id)
    const sprites = [...groups.flatMap((group) => group.children), ...holder.children] as Sprite[]
    expect(sprites).toHaveLength(4 + 4 + 2 + 1)                                 // 4 discs, 4 cards, Aurora's 2 rings, 1 pill
    const freed = sprites.flatMap((sprite) => [vi.spyOn(sprite.material, 'dispose'), vi.spyOn(sprite.material.map!, 'dispose')])

    // the same node drawn again by the library (another middle node and back): the first pictures are freed
    const again = graph.props.nodeThreeObject(graph.node(PRIYA.id)) as Group
    expect(groups[2].children).toHaveLength(0)
    const more = again.children.map((sprite) => vi.spyOn((sprite as Sprite).material, 'dispose'))
    expect(more).toHaveLength(2)

    fireEvent.click(screen.getByRole('button', { name: '2D view' }))
    await waitFor(() => expect(graph.destroyed).toBe(true))
    for (const spy of [...freed, ...more]) expect(spy).toHaveBeenCalled()       // pictures and materials freed
    for (const group of [...groups, again, holder]) expect(group.children).toHaveLength(0)
    expect(graph.stage.children).not.toContain(holder)
  })

  it('the dark theme changes the scene\'s background, discs, cards, rings, pills and lines; the balls and the first picture stay', async () => {
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const graph = await into3d()
    place(graph, FIRST)
    graph.settle()                                                              // the first picture
    const light = readColours('light')
    const dark = readColours('dark')
    expect(graph.props.backgroundColor).toBe(light.box)
    const aurora = graph.props.nodeThreeObject(graph.node(AURORA.id)) as Group  // its disc, its card, the soft ring, the selected ring
    const motor = graph.props.nodeThreeObject(graph.node(MOTOR.id)) as Group
    const [icon, label, middle, ring] = aurora.children
    const holder = graph.stage.children.find((child) => child instanceof Group) as Group
    graph.hover(PRIYA.id)                                                       // a pill on Priya's link
    const [pill] = holder.children
    expect(graph.props.linkColor(graph.data.links[0])).toBe(light.muted)
    const motorNode = graph.node(MOTOR.id)
    Object.assign(motorNode, { x: 12, y: -30, z: 7 })                           // dragged somewhere
    const drawn = graph.dragOnData.length                                       // how often the graph got its data
    const moves = graph.cameraPosition.mock.calls.length
    const opacity = graph.props.linkOpacity

    act(() => document.documentElement.setAttribute('data-theme', 'dark'))
    await waitFor(() => expect(graph.props.backgroundColor).toBe(dark.box))
    expect(dark.box).not.toBe(light.box)
    expect(graph.props.linkOpacity).toBeGreaterThan(opacity)                    // the links a bit stronger on dark
    expect(graphs).toHaveLength(1)                                              // the same graph ...
    expect(graph.destroyed).toBe(false)
    expect(graph.dragOnData.length).toBe(drawn)                                 // ... not given its data again
    expect(graph.d3ReheatSimulation).not.toHaveBeenCalled()                     // the layout does not run
    expect(graph.cameraPosition.mock.calls.length).toBe(moves)                  // the camera stays
    expect(graph.node(MOTOR.id)).toBe(motorNode)
    expect(motorNode).toMatchObject({ x: 12, y: -30, z: 7 })                    // the ball stays where it was
    expect(graph.node(AURORA.id)).toMatchObject({ fx: 0, fy: 0, fz: 0 })
    // the disc, the card and both rings were painted again (new sprites in the same group), and show as before
    expect(aurora.children).toHaveLength(4)
    for (const old of [icon, label, middle, ring]) expect(aurora.children).not.toContain(old)
    expect(aurora.children.map((child) => child.visible)).toEqual([true, true, true, true])
    expect(aurora.children.map((child) => child.userData.kind)).toEqual(['icon', 'card', 'ring', 'ring'])
    expect(aurora.children[0].userData.colour).toBe(dark.series[0])             // the middle node: the dark theme's blue
    expect(motor.children.map((child) => child.visible)).toEqual([true, true])
    expect((aurora.children[1] as Sprite).userData.text).toBe((label as Sprite).userData.text)
    expect(holder.children).toHaveLength(1)                                     // the pill too
    expect(holder.children).not.toContain(pill)
    expect(holder.children[0].userData.text).toBe('Handled by')
    expect(graph.props.linkColor(graph.data.links[0])).toBe(dark.muted)         // the lines in the dark theme's colour
    expect(dark.muted).not.toBe(light.muted)

    // Fit still brings back the first picture kept before the theme changed
    const frames = handFrames()
    fireEvent.click(screen.getByRole('button', { name: 'Fit' }))
    frames.finish()
    expect(at(motorNode)).toEqual(FIRST[MOTOR.id])

    act(() => document.documentElement.setAttribute('data-theme', 'light'))
    await waitFor(() => expect(graph.props.backgroundColor).toBe(light.box))
    expect(graph.dragOnData.length).toBe(drawn)
  })

  it('without WebGL says so and stays in 2D', async () => {
    webgl = false
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()

    fireEvent.click(screen.getByRole('button', { name: '3D view' }))
    expect(screen.getByText(NO_WEBGL)).toBeInTheDocument()
    expect(NO_WEBGL).toBe('3D needs WebGL, which this browser does not have.')
    expect(screen.getByRole('button', { name: '3D view' })).toHaveAttribute('aria-pressed', 'false')
    expect(graphs).toHaveLength(0)
    expect(window.localStorage.getItem('mi.graphView')).toBeNull()
    await waitFor(() => expect(lastChart()?.types()).toEqual(['graph']))
  })

  it('3D kept in this browser, but this one has no WebGL: 2D with the message', async () => {
    webgl = false
    window.localStorage.setItem('mi.graphView', '3d')
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    expect(screen.getByText(NO_WEBGL)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '3D view' })).toBeInTheDocument()
    await waitFor(() => expect(lastChart()?.types()).toEqual(['graph']))
    expect(graphs).toHaveLength(0)
  })

  it('a click selects, two quick clicks go in, a click on the middle node goes back (and its 2nd click is quiet)', async () => {
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const graph = await into3d()
    const moves = graph.cameraPosition.mock.calls.length

    graph.click(MOTOR.id)                                                       // one click: its details
    const panel = screen.getByRole('complementary', { name: 'Node details' })
    expect(await within(panel).findByText('INR 90,00,000.00')).toBeInTheDocument()
    expect(graph.ids()).toEqual(AURORA_ONLY)                                    // the graph stays

    clock += 150
    graph.click(MOTOR.id)                                                       // the 2nd click, 150 ms later: in
    await waitFor(() => expect(graph.ids()).toEqual(MOTOR_ONLY))
    expect(graph.node(MOTOR.id)).toMatchObject({ fx: 0, fy: 0, fz: 0 })
    expect(graph.cameraPosition.mock.calls.length).toBe(moves + 1)             // the camera turns to the new middle
    const path = screen.getByRole('navigation', { name: 'Path' })
    expect(within(path).getByText('Hydraulic motor HM-346-1B')).toHaveAttribute('aria-current', 'step')

    clock += 1000
    graph.click(MOTOR.id)                                                       // a click on the middle node: back
    await waitFor(() => expect(graph.ids()).toEqual(AURORA_ONLY))
    clock += 120
    graph.click(MOTOR.id)                                                       // the rest of that double-click
    await new Promise((done) => setTimeout(done, 20))
    expect(graph.ids()).toEqual(AURORA_ONLY)                                    // not in again

    clock += 1000
    graph.click(PRIYA.id)
    clock += DOUBLE_LATER
    graph.click(PRIYA.id)                                                       // two slow clicks: two selects, not in
    expect(await within(panel).findByText('Priya Iyer')).toBeInTheDocument()
    expect(graph.ids()).toEqual(AURORA_ONLY)
  })

  it('the wheel zooms only on or near the nodes; on the empty space the page scrolls', async () => {
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const graph = await into3d()
    const spots: [number, number][] = [[100, 100], [300, 200], [200, 150], [150, 180]] // where the library put them
    graph.data.nodes.forEach((n, i) => Object.assign(n, { x: spots[i][0], y: spots[i][1], z: 0 }))
    const wheel = (clientX: number, clientY: number) => {
      graph.wheels.mockClear()
      const event = new WheelEvent('wheel', { bubbles: true, cancelable: true, clientX, clientY, deltaY: 100 })
      graph.canvas.dispatchEvent(event)
      return { zooms: graph.wheels.mock.calls.length > 0, prevented: event.defaultPrevented }
    }

    expect(wheel(200, 150)).toEqual({ zooms: true, prevented: false })         // among the nodes
    expect(wheel(335, 235).zooms).toBe(true)                                     // within 40 px of the last one
    expect(wheel(600, 500)).toEqual({ zooms: false, prevented: false })         // empty space: the page scrolls
    expect(wheel(100, 30).zooms).toBe(false)                                    // 70 px above them

    graph.graph2ScreenCoords.mockImplementation((x: number, y: number, z: number) => ({ x: x * 2, y: y * 2, z }))
    expect(wheel(600, 400).zooms).toBe(true)                                    // zoomed in: the box grew

    fireEvent.click(screen.getByRole('button', { name: '⛶ Full screen' }))     // in full screen too
    expect(wheel(900, 900).zooms).toBe(false)
    expect(wheel(400, 300).zooms).toBe(true)
  })

  it('the first picture is kept when the layout first settles, and Fit brings it back: each ball glides home', async () => {
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const graph = await into3d()
    expect(graph.props.height).toBe(580 - 28)                                   // the 2D height, less the legend row
    expect(graph.cameraPosition).toHaveBeenLastCalledWith(START, CENTRE, 800)   // where a new centre starts
    const moves = graph.cameraPosition.mock.calls.length
    place(graph, FIRST)
    graph.settle()                                                              // the first layout settles: kept
    expect(graph.zoomToFit).not.toHaveBeenCalled()                              // (the camera framed the places already)
    expect(graph.cameraPosition.mock.calls.length).toBe(moves)

    place(graph, LOPSIDED, [AURORA.id, PRIYA.id])                               // dragged about ...
    graph.settle()                                                              // ... and settled again: not kept
    expect(graph.zoomToFit).not.toHaveBeenCalled()
    graph.cam.position = { x: 160, y: 40, z: -30 }                              // turned sideways and moved
    graph.cam.lookAt = { x: 20, y: -10, z: 0 }

    const frames = handFrames()
    const fitButton = screen.getByRole('button', { name: 'Fit' })
    expect(fitButton).toHaveAttribute('title', 'Back to the starting view')
    fireEvent.click(fitButton)
    // the camera at once straight in front, as far as the first picture asks (the lopsided one would ask for more)
    expect(graph.cameraPosition).toHaveBeenLastCalledWith(START, CENTRE, 800)
    expect(graph.cam).toMatchObject({ position: START, lookAt: CENTRE })
    expect(frames.waiting()).toBe(1)

    frames.frame()                                                              // the move starts where they are
    frames.frame(400)                                                           // half-way: on the way, held there
    const aurora = graph.node(AURORA.id)
    expect(aurora.x).toBeGreaterThan(-300)
    expect(aurora.x).toBeLessThan(0)
    expect([aurora.fx, aurora.fy, aurora.fz]).toEqual(at(aurora))
    const motor = graph.node(MOTOR.id)
    expect(motor.x).toBeGreaterThan(40)
    expect(motor.x).toBeLessThan(60)
    expect(motor.fx).toBe(motor.x)                                              // (the layout does not pull it away)
    expect(graph.engine.resetCountdown).toHaveBeenCalled()                     // the library draws balls and links

    frames.finish()
    expect(frames.waiting()).toBe(0)                                            // done: no loop
    const still = { vx: 0, vy: 0, vz: 0 }
    expect(aurora).toMatchObject({ ...CENTRE, fx: 0, fy: 0, fz: 0, ...still }) // back at the centre, pinned
    for (const [id, spot] of Object.entries(FIRST)) {
      const n = graph.node(id)
      expect(at(n)).toEqual(spot)                                               // each back in its first place ...
      expect([n.fx, n.fy, n.fz]).toEqual([undefined, undefined, undefined])    // ... and let go (Priya too)
      expect(n).toMatchObject(still)
    }
    expect(graph.d3ReheatSimulation).not.toHaveBeenCalled()                     // not laid out again: no spreading
    expect(graph.zoomToFit).not.toHaveBeenCalled()
    graph.settle()                                                              // the engine stops after it: nothing more
    expect(graph.zoomToFit).not.toHaveBeenCalled()
    expect(at(motor)).toEqual(FIRST[MOTOR.id])
    expect(screen.getByText(/Drag a ball to move it, drag the space to turn the graph/)).toBeInTheDocument()
    expect(screen.getByText(/Fit brings back the first picture\./)).toBeInTheDocument()

    // dragged again, settled again: Fit still brings back the first picture
    place(graph, LOPSIDED)
    graph.settle()
    fireEvent.click(fitButton)
    frames.finish()
    expect(at(graph.node(PRIYA.id))).toEqual(FIRST[PRIYA.id])
    expect(at(aurora)).toEqual([0, 0, 0])

    fireEvent.click(screen.getByRole('button', { name: '⛶ Full screen' }))
    expect(graph.props.height).toBe(Math.max(360, window.innerHeight - 150) - 28)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(graph.props.height).toBe(580 - 28)

    // after Fit a click still selects and two quick clicks still go in
    clock += 1000
    graph.click(MOTOR.id)
    const panel = screen.getByRole('complementary', { name: 'Node details' })
    expect(await within(panel).findByText('INR 90,00,000.00')).toBeInTheDocument()
    expect(graph.ids()).toEqual(AURORA_ONLY)
    clock += 150
    graph.click(MOTOR.id)
    await waitFor(() => expect(graph.ids()).toEqual(MOTOR_ONLY))
  })

  it('Fit before the layout first settles only turns the camera; a new middle node keeps a new first picture', async () => {
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const graph = await into3d()
    const frames = handFrames()
    place(graph, LOPSIDED)
    graph.cam.position = { x: 160, y: 40, z: -30 }
    const fitButton = screen.getByRole('button', { name: 'Fit' })
    fireEvent.click(fitButton)                                                  // no first picture yet
    expect(graph.cam).toMatchObject({ lookAt: CENTRE })                         // the camera in front ...
    expect(graph.cam.position.x).toBe(0)
    expect(frames.waiting()).toBe(0)                                            // ... and no ball moves
    expect(at(graph.node(MOTOR.id))).toEqual(LOPSIDED[MOTOR.id])
    expect(graph.engine.resetCountdown).not.toHaveBeenCalled()

    place(graph, FIRST)
    graph.settle()                                                              // Aurora's first picture
    graph.click(MOTOR.id)
    clock += 150
    graph.click(MOTOR.id)                                                       // into the motor: a new middle node
    await waitFor(() => expect(graph.ids()).toEqual(MOTOR_ONLY))
    const motorFirst: Record<string, Spot> = { [AURORA.id]: [25, 25, 0], [HYDRAULIC.id]: [-30, 0, 10], [CATALOGUE.id]: [0, -40, -10] }
    place(graph, { [AURORA.id]: [80, 80, 80] })
    fireEvent.click(fitButton)                                                  // Aurora's picture is forgotten
    expect(frames.waiting()).toBe(0)
    expect(at(graph.node(AURORA.id))).toEqual([80, 80, 80])

    place(graph, motorFirst)
    graph.settle()                                                              // the motor's first picture
    place(graph, { [MOTOR.id]: [-100, 0, 0], [AURORA.id]: [200, 10, 0], [CATALOGUE.id]: [0, 90, 5] }, [MOTOR.id])
    fireEvent.click(fitButton)
    frames.finish()
    expect(graph.node(MOTOR.id)).toMatchObject({ ...CENTRE, fx: 0, fy: 0, fz: 0 })
    for (const [id, spot] of Object.entries(motorFirst)) expect(at(graph.node(id))).toEqual(spot)
    expect(graph.d3ReheatSimulation).not.toHaveBeenCalled()
  })

  it('two quick Fits end in the first picture without a jump; leaving 3D during the move stops it', async () => {
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const graph = await into3d()
    place(graph, FIRST)
    graph.settle()
    place(graph, LOPSIDED, [AURORA.id])
    const frames = handFrames()
    const fitButton = screen.getByRole('button', { name: 'Fit' })
    fireEvent.click(fitButton)
    frames.frame()
    frames.frame(200)
    const motor = graph.node(MOTOR.id)
    const midway = at(motor)
    fireEvent.click(fitButton)                                                  // pressed again during the move
    expect(frames.waiting()).toBe(1)                                            // the first move stopped: one loop only
    frames.frame()                                                              // the new move starts where the balls are
    expect(at(motor)).toEqual(midway)
    frames.finish()
    expect(frames.waiting()).toBe(0)
    expect(at(motor)).toEqual(FIRST[MOTOR.id])
    expect(graph.node(AURORA.id)).toMatchObject({ ...CENTRE, fx: 0, fy: 0, fz: 0 })
    expect(motor.fx).toBeUndefined()

    place(graph, LOPSIDED)
    fireEvent.click(fitButton)
    frames.frame()
    frames.frame(200)
    expect(frames.waiting()).toBe(1)
    fireEvent.click(screen.getByRole('button', { name: '2D view' }))            // 3D left during the move
    await waitFor(() => expect(graph.destroyed).toBe(true))
    expect(frames.waiting()).toBe(0)                                            // the move stopped with it
  })

  it('Similar customers adds nodes and keeps the ones drawn where they are; the new ones join the first picture', async () => {
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const graph = await into3d()
    place(graph, FIRST)
    graph.settle()
    const motor = graph.node(MOTOR.id)
    Object.assign(motor, { x: 12, y: -30, z: 7 })
    const moves = graph.cameraPosition.mock.calls.length

    fireEvent.click(screen.getByRole('button', { name: 'Similar customers' }))
    await waitFor(() => expect(graph.ids()).toContain('customer:12'))
    expect(graph.node(MOTOR.id)).toBe(motor)                                    // the same object ...
    expect(motor).toMatchObject({ x: 12, y: -30, z: 7 })                        // ... in the same place
    expect(graph.cameraPosition.mock.calls.length).toBe(moves)                  // the camera stays
    const buysLike = graph.data.links.find((l: { edge: GraphEdge }) => l.edge.type === 'BUYS_LIKE')
    expect(buysLike).toMatchObject({ width: 0 })                                // the thinnest line, as 2D's dashed one

    place(graph, { 'customer:12': [-20, -25, 15], [PRIYA.id]: [-50, 10, 0] })   // the layout settles with the new one
    graph.settle()
    place(graph, { 'customer:12': [150, 0, 0], [PRIYA.id]: [0, 150, 0] })
    const frames = handFrames()
    fireEvent.click(screen.getByRole('button', { name: 'Fit' }))
    frames.finish()
    expect(at(graph.node('customer:12'))).toEqual([-20, -25, 15])               // the new node: its first place
    expect(at(graph.node(PRIYA.id))).toEqual(FIRST[PRIYA.id])                   // the others: still their first ones
    expect(at(motor)).toEqual(FIRST[MOTOR.id])
  })
})

const DOUBLE_LATER = 400 // ms: more than DOUBLE (300), so two clicks are not a double-click
