// A stand-in for 3d-force-graph in the tests (jsdom has no WebGL): it keeps every graph made, the data and the
// settings (nodeColor, onNodeClick ...) it was given, and a canvas that counts the wheel events reaching it (the
// library's controls listen there), plus a camera that cameraPosition moves (a test can turn it by hand). The node
// objects are the ones the page gave (a test can move them, as the layout or a drag would), and settle() is the
// layout settling (the library's onEngineStop). Its scene holds a layout engine that counts resetCountdown (the
// library draws the balls and links only while that engine runs), and takes what the page adds to it (the link
// pills' group). hover() is the mouse over a node, moveLinks() the library moving every link to where its two
// nodes are now (linkPositionUpdate), controls() the orbit controls with the point the camera turns around;
// d3Force() keeps the layout's forces by name (the page adds its own and takes the library's 'center' away). Use it with
//   vi.mock('3d-force-graph', () => import('../test/fakeForceGraph'))
import { vi } from 'vitest'

type Settings = Record<string, any>

export const graphs: FakeForceGraph[] = []
export const lastGraph = (): FakeForceGraph => graphs[graphs.length - 1]

export class FakeForceGraph {
  element: HTMLElement
  config: unknown
  props: Settings = {} // every setting given: backgroundColor, nodeColor, onNodeClick ...
  data: { nodes: any[]; links: any[] } = { nodes: [], links: [] }
  canvas: HTMLCanvasElement
  destroyed = false
  wheels = vi.fn() // the wheel events that reached the canvas (the library would zoom)
  zoomToFit = vi.fn(() => this.self)
  d3ReheatSimulation = vi.fn(() => this.self) // the layout runs again
  dragOnData: unknown[] = [] // enableNodeDrag as it was at each graphData (the library reads it when it draws the data)
  cam = { fov: 50, position: { x: 0, y: 0, z: 1000 }, lookAt: { x: 0, y: 0, z: 0 } } // where it is and looks at
  cameraPosition = vi.fn((position?: { x: number; y: number; z: number }, lookAt?: { x: number; y: number; z: number }, _ms?: number) => {
    if (!position) return { ...this.cam.position, lookAt: this.cam.lookAt } // the getter
    this.cam.position = { ...position } // as at the end of the move
    this.cam.lookAt = { ...(lookAt ?? { x: 0, y: 0, z: 0 }) }
    return this.self
  })
  pauseAnimation = vi.fn(() => this.self)
  graph2ScreenCoords = vi.fn((x: number, y: number, z: number) => ({ x, y, z })) // the screen = the graph's x and y
  // the layout's forces, by name: the library's charge and link (a test reads what they were given), the page's own
  forces: Record<string, any> = { charge: { strength: vi.fn(), distanceMax: vi.fn() }, link: { distance: vi.fn() }, center: {} }
  engine = { resetCountdown: vi.fn() } // three-forcegraph, in the scene: kept running, it draws where the nodes are
  stage = {
    children: [{}, this.engine] as any[],
    add: (item: unknown) => { this.stage.children.push(item) },
    remove: (item: unknown) => { this.stage.children = this.stage.children.filter((child) => child !== item) },
  }
  rendererStub: Settings
  self: any

  constructor(element: HTMLElement, config?: unknown) {
    this.element = element
    this.config = config
    this.canvas = document.createElement('canvas')
    element.appendChild(this.canvas)
    this.canvas.addEventListener('wheel', this.wheels)
    this.rendererStub = { domElement: this.canvas, getPixelRatio: () => 1, setPixelRatio: vi.fn(), render: vi.fn(), forceContextLoss: vi.fn() }
    graphs.push(this)
    // the library's settings are chainable: graph.width(800).height(500); graph.width() reads one back
    this.self = new Proxy(this, {
      get: (target, name) => {
        if (typeof name === 'symbol' || name in target) return (target as any)[name]
        return (...args: unknown[]) => {
          if (!args.length) return target.props[name]
          target.props[name] = args[0]
          return target.self
        }
      },
    })
    return this.self
  }

  graphData(data?: { nodes: any[]; links: any[] }) {
    if (data === undefined) return this.data
    this.data = data
    this.dragOnData.push(this.props.enableNodeDrag)
    return this.self
  }

  renderer() { return this.rendererStub }
  scene() { return this.stage }
  camera() { return this.cam }
  /** The orbit controls: the point the camera turns around (and looks at). */
  controls() { return { target: this.cam.lookAt } }
  /** d3Force(name) reads a force; d3Force(name, force) sets it (null takes it away), chainable as the library's. */
  d3Force(name: string, force?: unknown) {
    if (force === undefined) return this.forces[name]
    if (force === null) delete this.forces[name]
    else this.forces[name] = force
    return this.self
  }
  /** How long the link force wants a link now (the last distance the page gave it). */
  linkLength(link: unknown): number { return this.forces.link.distance.mock.lastCall[0](link) }
  _destructor() { this.destroyed = true }

  /** The node object the graph holds now. */
  node(id: string) { return this.data.nodes.find((n) => n.id === id) }
  ids() { return this.data.nodes.map((n) => n.id) }
  /** The layout settles (the library calls onEngineStop when its engine stops). */
  settle() { this.props.onEngineStop?.() }
  /** A click on a node, as the library reports it. */
  click(id: string) { this.props.onNodeClick(this.node(id), new MouseEvent('click')) }
  /** The mouse over a node (null: over none), as the library reports it. */
  hover(id: string | null) { this.props.onNodeHover(id ? this.node(id) : null, null) }
  /** The library moves every link to where its two nodes are now (it does on each frame while the layout runs). */
  moveLinks() {
    const spot = (end: any) => {
      const n = typeof end === 'object' ? end : this.node(end)
      return { x: n?.x ?? 0, y: n?.y ?? 0, z: n?.z ?? 0 }
    }
    for (const link of this.data.links) this.props.linkPositionUpdate?.({}, { start: spot(link.source), end: spot(link.target) }, link)
  }
}

export default FakeForceGraph
