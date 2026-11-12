// A stand-in for 3d-force-graph in the tests (jsdom has no WebGL): it keeps every graph made, the data and the
// settings (nodeColor, onNodeClick ...) it was given, and a canvas that counts the wheel events reaching it (the
// library's controls listen there), plus a camera that cameraPosition moves (a test can turn it by hand). The node
// objects are the ones the page gave (a test can move them, as the layout or a drag would), and settle() is the
// layout settling (the library's onEngineStop). Its scene holds a layout engine that counts resetCountdown (the
// library draws the balls and links only while that engine runs). Use it with
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
  forces = { charge: { strength: vi.fn() }, link: { distance: vi.fn() } }
  engine = { resetCountdown: vi.fn() } // three-forcegraph, in the scene: kept running, it draws where the nodes are
  stage = { children: [{}, this.engine] }
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
  d3Force(name: 'charge' | 'link') { return this.forces[name] }
  _destructor() { this.destroyed = true }

  /** The node object the graph holds now. */
  node(id: string) { return this.data.nodes.find((n) => n.id === id) }
  ids() { return this.data.nodes.map((n) => n.id) }
  /** The layout settles (the library calls onEngineStop when its engine stops). */
  settle() { this.props.onEngineStop?.() }
  /** A click on a node, as the library reports it. */
  click(id: string) { this.props.onNodeClick(this.node(id), new MouseEvent('click')) }
}

export default FakeForceGraph
