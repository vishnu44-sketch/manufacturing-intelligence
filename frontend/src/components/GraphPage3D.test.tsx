// Knowledge graph, the 3D view (05-Nov): the switch and its memory, WebGL missing, the same colours as 2D, a click
// selects (on the middle node: back), two quick clicks go in, the balls can be dragged, the wheel zooms only near
// the nodes, Fit (the first picture back: each ball glides to where it was when the layout first settled, the
// middle one pinned at the centre, nothing laid out again), full screen, Similar customers keeps the nodes in place,
// the theme (light / dark: the scene's colours change, the balls stay), and leaving 3D takes the library apart. 3d-force-graph is a fake (test/fakeForceGraph.ts): jsdom has no WebGL, so
// the tests check what it is given; the frames of Fit's move are run by hand (handFrames).
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Group, type Sprite } from 'three'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type FakeForceGraph, graphs, lastGraph } from '../test/fakeForceGraph'
import { readColours } from '../charts/chartOption'
import { charts, lastChart } from '../test/fakeEcharts'
import { fakeFetch } from '../test/fakeFetch'
import { renderAt } from '../test/render'
import type { GraphEdge, GraphNode, GraphNodeReply, GraphSimilarReply } from '../types'
import GraphPage, { NO_WEBGL } from './GraphPage'
import { TYPE_COLOURS } from './graphData'

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
// a 2D canvas that draws nothing (the names and rings are drawn on small canvases)
const paint = new Proxy({ measureText: () => ({ width: 60 }) } as Record<string, unknown>, {
  get: (target, name) => (name in target ? target[name as string] : () => {}),
  set: () => true,
})
let clock = 100000 // Date.now in these tests: each click moves it on by hand

beforeEach(() => {
  webgl = true
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
const START = { x: 0, y: 0, z: 90 + 40 * Math.sqrt(4) }                      // straight in front, for 4 nodes

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
    // the colours of 2D: a node's type, a link its source's colour
    expect(graph.props.nodeColor(graph.node(AURORA.id))).toBe(TYPE_COLOURS.customer)
    expect(graph.props.nodeColor(graph.node(MOTOR.id))).toBe(TYPE_COLOURS.product)
    expect(graph.data.links).toHaveLength(3)
    expect(graph.data.links.every((l: { colour: string }) => l.colour === TYPE_COLOURS.customer)).toBe(true)
    expect(graph.node(AURORA.id)).toMatchObject({ fx: 0, fy: 0, fz: 0 })      // the middle node at the centre
    expect(graph.node(AURORA.id).r).toBeGreaterThan(graph.node(MOTOR.id).r)  // sized by net sales, as in 2D
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

  it('names the middle node and rings the middle and the selected node; the ring follows the selection', async () => {
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const graph = await into3d()
    const made = (id: string) => graph.props.nodeThreeObject(graph.node(id)) as Group  // as the library asks for it
    const shown = (group: Group) => group.children.map((child) => child.visible)

    const aurora = made(AURORA.id)
    expect(aurora).toBeInstanceOf(Group)
    expect(shown(aurora)).toEqual([true, true, true])                           // its name, the white ring, the dark ring
    const label = aurora.children[0] as Sprite
    expect(label.position.y).toBe(graph.node(AURORA.id).r)                      // just above the ball
    expect(label.scale.y).toBeGreaterThan(0)

    const motor = made(MOTOR.id)
    graph.click(MOTOR.id)                                                       // select the motor
    await within(screen.getByRole('complementary', { name: 'Node details' })).findByText('INR 90,00,000.00')
    await waitFor(() => expect(shown(aurora)).toEqual([true, true, false]))     // the dark ring moved ...
    expect(aurora.children[2].layers.isEnabled(0)).toBe(false)                  // (hidden: no hover or click on it)
    expect(shown(motor)).toEqual([true, true])                                  // ... to the motor (name + ring)
  })

  it('the dark theme changes the scene\'s background, tags and rings; the balls and the first picture stay', async () => {
    fakeFetch(REPLIES)
    renderAt('/graph', <GraphPage />)
    await drawAurora()
    const graph = await into3d()
    place(graph, FIRST)
    graph.settle()                                                              // the first picture
    const light = readColours('light')
    const dark = readColours('dark')
    expect(graph.props.backgroundColor).toBe(light.box)
    const aurora = graph.props.nodeThreeObject(graph.node(AURORA.id)) as Group  // its name, the middle ring, the selected ring
    const motor = graph.props.nodeThreeObject(graph.node(MOTOR.id)) as Group
    const [label, middle, ring] = aurora.children
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
    // the name tag and both rings were painted again (new sprites in the same group), and show as before
    expect(aurora.children).toHaveLength(3)
    for (const old of [label, middle, ring]) expect(aurora.children).not.toContain(old)
    expect(aurora.children.map((child) => child.visible)).toEqual([true, true, true])
    expect(motor.children.map((child) => child.visible)).toEqual([true])
    expect((aurora.children[0] as Sprite).userData.text).toBe((label as Sprite).userData.text)

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
    place(graph, FIRST)
    graph.settle()                                                              // the first layout settles: kept, fitted once
    expect(graph.zoomToFit).toHaveBeenCalledTimes(1)
    graph.zoomToFit.mockClear()

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
    expect(buysLike).toMatchObject({ colour: TYPE_COLOURS.customer, width: 0 }) // a thin line, as 2D's dashed one

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
