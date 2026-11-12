// The Knowledge graph in 3D: the "3D view" switch of GraphPage. It loads lazily with 3d-force-graph and three.js,
// only when the user picks 3D, so the 2D page stays as small as before. The same nodes, colours, sizes and legend
// as the 2D graph (graphOption.ts), drawn as balls in space; the node in the middle sits at the centre with a white
// ring, the selected one has a dark ring (on the dark theme: a light ring with a glow, and a light ring). The
// biggest nodes, the middle one and the selected one carry their name;
// the others show it (and a tooltip) on hover.
// A click selects a node (on the node in the middle: goes back); two clicks on the same node within DOUBLE ms go
// into it (the library has no double-click). A ball can be dragged to another place; a drag on the space around
// them turns the graph, a right-drag moves it. The mouse wheel zooms only on the balls (the box around them on the
// screen, NEAR px wider): on the empty space around them the page scrolls, as in 2D - in full screen too. The first
// picture of a new middle node (where every ball is once the layout first settles) is kept, and Fit brings it back
// at once: every ball glides back to its place there (the middle one pinned at the centre again, the layout not run
// again) and the camera goes back straight in front. Download PNG saves the picture with the legend and the title,
// like the 2D one. Leaving 3D (or the page) stops the drawing loop and frees the WebGL context.
// The theme (light / dark): the scene's background, the name tags, the rings and the links' strength follow it.
// A change of theme only repaints those - the data is not given again, so every ball stays where it is and the
// first picture kept for Fit stays too.
import ForceGraph3D, { type ForceGraph3DInstance } from '3d-force-graph'
import { Download, Maximize } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CanvasTexture, Group, LinearFilter, type PerspectiveCamera, SRGBColorSpace, Sprite, SpriteMaterial } from 'three'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'
import { type GraphData, TYPE_COLOURS, TYPE_NAMES, TYPE_ORDER } from '../components/graphData'
import type { GraphEdge, GraphNode, GraphNodeType } from '../types'
import { type Colours, FONT, NARROW, type Paper, cutText, downloadImage, fade, pngName, pngPaper, readColours } from './chartOption'
import { LINK_OPACITY, LINK_OPACITY_DARK, MONEY_EDGES, describeGraph, edgeTip, edgeWidth, nodeSize, nodeTip } from './graphOption'
import useThemeName from './useThemeName'
import './chart.css'
import './graph3d.css'

export interface Graph3DProps {
  data: GraphData
  center: string | null
  selected: string | null
  title: string // above the graph and in the PNG
  subtitle?: string // the period's dates, in the PNG
  onSelect: (id: string) => void
  onOpen: (id: string) => void
  height?: number // full screen: the graph as tall as the screen
  onNoWebGL?: () => void // the browser could not start WebGL: GraphPage goes back to 2D
}

export const DOUBLE = 300 // ms: two clicks on the same node within this go into it
export const LABELLED_3D = 8 // the biggest nodes that always show their name (fewer than 2D: labels overlap in 3D)
const NEAR = 40 // px around the balls where the mouse wheel still zooms
const LEGEND = 28 // px: the legend row above the drawing
const RADIUS = 0.22 // a ball's radius per px of the 2D dot (12..48 px -> 2.6..10.6)
const EDGE = 0.3 // a link's width per px of the 2D line; documents and "buys like" are thin lines
const MOVE_MS = 800 // camera moves: slow and gentle
const FIT_PAD = 40 // px around the nodes after Fit
const MIDDLE = { x: 0, y: 0, z: 0 } // where the node in the middle sits, and where the camera looks

interface Spot {
  x: number
  y: number
  z: number
}

/** A node as the library holds it (it adds x, y, z and its speed). */
interface Node3D {
  id: string
  node: GraphNode
  r: number
  x?: number
  y?: number
  z?: number
  fx?: number
  fy?: number
  fz?: number
  vx?: number
  vy?: number
  vz?: number
}

/** The library's layout engine (three-forcegraph, a group in the scene). It moves the balls and links on the
 *  screen only while it runs, so Fit keeps it running (resetCountdown, as the library's own node drag does)
 *  without heating the layout up again. */
interface Engine {
  resetCountdown: () => unknown
}

function engineOf(graph: ForceGraph3DInstance): Engine | null {
  const children = (graph.scene() as { children?: unknown[] }).children ?? []
  const found = children.find((child) => typeof (child as Partial<Engine>)?.resetCountdown === 'function')
  return (found as Engine | undefined) ?? null
}

interface Link3D {
  source: string | Node3D
  target: string | Node3D
  edge: GraphEdge
  colour: string
  width: number
}

/** The extra things drawn with one node: its name, the white ring of the middle node, the selected node's ring. */
interface Marks {
  group: Group
  label: Sprite | null
  middle: Sprite | null
  ring: Sprite | null
}

/** A name on a small tag (white; the card's dark colour on the dark theme), as a sprite that keeps its size on
 *  the screen (scaled in `mark`). */
function textSprite(text: string, colours: Colours): Sprite | null {
  const canvas = document.createElement('canvas')
  let ctx: CanvasRenderingContext2D | null = null
  try {
    ctx = canvas.getContext('2d')
  } catch {
    ctx = null
  }
  if (!ctx) return null
  const scale = 2 // drawn at twice the size: sharp on every screen
  const font = `500 ${11 * scale}px ${FONT}`
  ctx.font = font
  const width = Math.ceil(ctx.measureText(text).width) + 12 * scale
  const height = 18 * scale
  canvas.width = width
  canvas.height = height
  ctx.font = font // a new size clears the font
  ctx.fillStyle = colours.dark ? fade(colours.surface, 0.85) : 'rgba(255,255,255,.85)'
  ctx.beginPath()
  ctx.roundRect?.(0, 0, width, height, 5 * scale)
  ctx.fill()
  ctx.fillStyle = colours.ink
  ctx.textBaseline = 'middle'
  ctx.fillText(text, 6 * scale, height / 2 + scale)
  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  texture.minFilter = LinearFilter
  const sprite = new Sprite(new SpriteMaterial({ map: texture, transparent: true, depthTest: false, depthWrite: false, sizeAttenuation: false }))
  sprite.renderOrder = 10 // names always on top
  sprite.center.set(0.5, -0.3) // above the ball, a small gap under the tag
  sprite.userData = { width: width / scale, height: height / scale, text }
  return sprite
}

/** A ring around a ball (a sprite always faces the camera, like the 2D dot's border). at = the ring's radius
 *  as a share of the sprite's size, to size it from the ball's radius. glow = the colour of a soft glow around it. */
function ringSprite(colour: string, line: number, glow = ''): Sprite | null {
  const canvas = document.createElement('canvas')
  canvas.width = 128
  canvas.height = 128
  let ctx: CanvasRenderingContext2D | null = null
  try {
    ctx = canvas.getContext('2d')
  } catch {
    ctx = null
  }
  if (!ctx) return null
  const radius = 64 - line / 2 - (glow ? 12 : 2)
  if (glow) {
    ctx.shadowBlur = 10
    ctx.shadowColor = glow
  }
  ctx.strokeStyle = colour
  ctx.lineWidth = line
  ctx.beginPath()
  ctx.arc(64, 64, radius, 0, Math.PI * 2)
  ctx.stroke()
  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  const sprite = new Sprite(new SpriteMaterial({ map: texture, transparent: true, depthWrite: false }))
  sprite.userData = { at: radius / 128 }
  return sprite
}

/** Takes a name or ring out of its node's group and frees its picture. */
function drop(group: Group, sprite: Sprite) {
  group.remove(sprite)
  sprite.material.map?.dispose()
  sprite.material.dispose()
}

/** Shows or hides a name or ring. A hidden one moves to another layer too: the library's hover and click
 *  (three.js' raycaster) skip only other layers, not hidden objects, and an empty spot must not pick a node. */
function show(sprite: Sprite, on: boolean) {
  sprite.visible = on
  sprite.layers.set(on ? 0 : 1)
}

/** The box around the nodes on the screen now, in px of the drawing (after any turn and zoom); null when unknown. */
function nodesBox(graph: ForceGraph3DInstance, nodes: Iterable<Node3D>) {
  let box: { left: number; top: number; right: number; bottom: number } | null = null
  for (const node of nodes) {
    if (![node.x, node.y, node.z].every(Number.isFinite)) continue
    const at = graph.graph2ScreenCoords(node.x as number, node.y as number, node.z as number)
    if (!Number.isFinite(at.x) || !Number.isFinite(at.y)) continue
    box = box ? { left: Math.min(box.left, at.x), top: Math.min(box.top, at.y), right: Math.max(box.right, at.x), bottom: Math.max(box.bottom, at.y) }
      : { left: at.x, top: at.y, right: at.x, bottom: at.y }
  }
  return box
}

/** The camera back to the starting view, in one smooth move: straight in front of the node in the middle, looking
 *  at it (the target a right-drag moved goes back to the centre too), as far away as the number of nodes asks - or
 *  further, when a node already placed would be outside the view from there (FIT_PAD px kept around them). The
 *  controls are OrbitControls: they never roll the camera, so its "up" is still straight up. The nodes do not move. */
function startCamera(graph: ForceGraph3DInstance, nodes: Node3D[]) {
  let distance = 90 + 40 * Math.sqrt(nodes.length)
  const camera = graph.camera() as PerspectiveCamera
  const height = Math.max(1, graph.height() || 1)
  const aspect = (graph.width() || height) / height
  const fov = ((camera.fov || 50) * Math.max(0.1, 1 - (2 * FIT_PAD) / height) * Math.PI) / 180 // less the padding
  const up = Math.tan(fov / 2) // how far the view reaches up and down, per unit of distance
  const side = up * aspect // and to the sides
  for (const node of nodes) {
    if (![node.x, node.y, node.z].every(Number.isFinite)) continue // not placed yet (a new centre)
    const z = node.z as number
    distance = Math.max(distance, z + (Math.abs(node.y as number) + node.r) / up, z + (Math.abs(node.x as number) + node.r) / side)
  }
  graph.cameraPosition({ x: 0, y: 0, z: distance }, MIDDLE, MOVE_MS)
}

function loadImage(url: string): Promise<HTMLImageElement> {
  const image = new Image()
  return new Promise((resolve, reject) => {
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('the picture could not be read'))
    image.src = url
  })
}

/** The picture with the legend over it (the dots and names of the node types drawn), on the PNG's paper (white;
 *  the dark card on the dark theme). */
async function withLegend(url: string, types: GraphNodeType[], paper: Paper): Promise<string> {
  const image = await loadImage(url)
  const scale = 2
  const band = LEGEND * scale
  const canvas = document.createElement('canvas')
  canvas.width = image.width
  canvas.height = image.height + band
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('no canvas')
  ctx.fillStyle = paper.background
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.font = `${11 * scale}px ${FONT}`
  ctx.textBaseline = 'middle'
  const items = types.map((type) => ({ type, width: 15 * scale + ctx.measureText(TYPE_NAMES[type]).width }))
  const gap = 14 * scale
  let x = (canvas.width - items.reduce((sum, item) => sum + item.width, 0) - gap * Math.max(0, items.length - 1)) / 2
  for (const item of items) {
    ctx.fillStyle = TYPE_COLOURS[item.type]
    ctx.beginPath()
    ctx.arc(x + 5 * scale, band / 2, 5 * scale, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillStyle = paper.muted
    ctx.fillText(TYPE_NAMES[item.type], x + 15 * scale, band / 2)
    x += item.width + gap
  }
  ctx.drawImage(image, 0, band)
  return canvas.toDataURL('image/png')
}

export default function Graph3D({
  data, center, selected, title, subtitle = '', onSelect, onOpen, height, onNoWebGL,
}: Graph3DProps) {
  const box = useRef<HTMLDivElement>(null) // the outer box: the wheel is caught here first
  const mount = useRef<HTMLDivElement>(null) // where the library draws
  const graph = useRef<ForceGraph3DInstance | null>(null)
  const handlers = useRef({ onSelect, onOpen, onNoWebGL })
  handlers.current = { onSelect, onOpen, onNoWebGL }
  const nodes = useRef(new Map<string, Node3D>()) // the node objects the library moves (kept while the centre stays)
  const marks = useRef(new Map<string, Marks>())
  const byId = useRef(new Map<string, GraphNode>())
  const drawnCenter = useRef<string | null | undefined>(undefined)
  const refit = useRef(false) // a new centre: fit the camera when the layout settles
  const firstSpots = useRef(new Map<string, Spot>()) // the first picture: where each ball was when the layout first settled
  const keepSpots = useRef(false) // the next settle keeps the places of the balls that have none kept yet
  const glide = useRef({ frame: 0, items: [] as Node3D[] }) // Fit's move back: its next frame (0: none), the balls it moves
  const lastClick = useRef({ id: '', at: 0 })
  const [width, setWidth] = useState(0)
  const narrow = width > 0 && width < NARROW
  const total = height ?? (narrow ? 440 : 580)
  const drawHeight = Math.max(200, total - LEGEND)
  // what the marks show now (read by the library's callbacks, outside React)
  const view = useRef({ center, selected, hovered: null as string | null, labelled: new Set<string>(), height: drawHeight, narrow })
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const theme = useThemeName()
  const colours = useMemo(() => readColours(theme), [theme])
  const tint = useRef(colours) // the colours the scene is drawn with now (read by the library's callbacks)

  /** Shows, sizes and places the name and rings of one node, as the view is now. */
  const mark = useCallback((id: string, made: Marks) => {
    const item = nodes.current.get(id)
    const made3d = graph.current
    if (!item || !made3d) return
    const { center: middle, selected: chosen, hovered, labelled, height: drawn } = view.current
    const fov = (made3d.camera() as PerspectiveCamera).fov || 50
    const perPx = (2 * Math.tan((fov * Math.PI) / 360)) / Math.max(1, drawn) // a sprite's scale for 1 px on the screen
    if (made.label) {
      show(made.label, labelled.has(id) || id === middle || id === chosen || id === hovered)
      made.label.position.set(0, item.r, 0)
      made.label.scale.set(made.label.userData.width * perPx, made.label.userData.height * perPx, 1)
    }
    if (id === middle && !made.middle) {
      // a white ring with a soft shadow; on dark a light ring with a light glow
      made.middle = tint.current.dark ? ringSprite(tint.current.ink, 12, 'rgba(255,255,255,.45)') : ringSprite('#fff', 12, 'rgba(0,0,0,.3)')
      if (made.middle) made.group.add(made.middle)
    }
    if (made.middle) {
      show(made.middle, id === middle)
      const size = (item.r * 1.22) / made.middle.userData.at
      made.middle.scale.set(size, size, 1)
    }
    if (id === chosen && !made.ring) {
      made.ring = ringSprite(tint.current.ink, 9)
      if (made.ring) made.group.add(made.ring)
    }
    if (made.ring) {
      show(made.ring, id === chosen)
      const size = (item.r * (id === middle ? 1.6 : 1.3)) / made.ring.userData.at
      made.ring.scale.set(size, size, 1)
    }
  }, [])

  const markAll = useCallback(() => {
    for (const [id, made] of marks.current) {
      if (nodes.current.has(id)) mark(id, made)
      else marks.current.delete(id)
    }
  }, [mark])

  /** Stops Fit's move back where it is now: the balls it held are let go (the middle one stays pinned). */
  const stopGlide = useCallback(() => {
    const { frame, items } = glide.current
    if (frame) cancelAnimationFrame(frame)
    for (const item of items) {
      if (item.id === view.current.center) continue
      delete item.fx
      delete item.fy
      delete item.fz
    }
    glide.current = { frame: 0, items: [] }
  }, [])

  // the library is made once (and taken apart when 3D is left): the drawing loop stops, the WebGL context is freed
  useEffect(() => {
    const el = mount.current
    const outer = box.current
    if (!el || !outer) return
    let made: ForceGraph3DInstance
    try {
      made = new ForceGraph3D(el, { controlType: 'orbit' })
    } catch {
      handlers.current.onNoWebGL?.() // no WebGL after all: back to 2D
      return
    }
    graph.current = made
    nodes.current = new Map()
    marks.current = new Map()
    drawnCenter.current = undefined
    const scene = made.scene()

    made.backgroundColor(tint.current.box).showNavInfo(false)
      .enableNodeDrag(true) // a ball can be dragged (read when the data is drawn: set before it)
      .width(el.clientWidth || 800).height(view.current.height)
      .nodeId('id').nodeRelSize(1).nodeResolution(20).nodeOpacity(0.95)
      .nodeVal((n) => (n as Node3D).r ** 3)
      .nodeColor((n) => TYPE_COLOURS[(n as Node3D).node.type])
      .nodeLabel((n) => nodeTip((n as Node3D).node))
      .nodeThreeObjectExtend(true)
      .nodeThreeObject((n) => {
        const item = n as Node3D
        const group = new Group()
        const label = textSprite(cutText(item.node.label, view.current.narrow ? 18 : 28), tint.current)
        if (label) group.add(label)
        const made3 = { group, label, middle: null, ring: null }
        marks.current.set(item.id, made3)
        mark(item.id, made3)
        return group
      })
      .linkColor((l) => (l as Link3D).colour)
      .linkWidth((l) => (l as Link3D).width)
      .linkOpacity(tint.current.dark ? LINK_OPACITY_DARK : LINK_OPACITY)
      .linkDirectionalArrowLength((l) => 3 + (l as Link3D).width * 0.8)
      .linkDirectionalArrowRelPos(1)
      .linkDirectionalArrowColor((l) => (l as Link3D).colour)
      .linkLabel((l) => edgeTip((l as Link3D).edge, byId.current))
      .onNodeClick((n) => {
        const id = String((n as Node3D).id)
        const now = Date.now()
        const again = lastClick.current.id === id && now - lastClick.current.at < DOUBLE
        if (again) {
          // the 2nd click of a double-click: only "go in" (GraphPage's BACK_QUIET ignores it right after going back)
          lastClick.current = { id: '', at: 0 }
          handlers.current.onOpen(id)
          return
        }
        lastClick.current = { id, at: now }
        handlers.current.onSelect(id)
      })
      .onNodeHover((n) => {
        const before = view.current.hovered
        view.current.hovered = n ? String((n as Node3D).id) : null
        for (const id of [before, view.current.hovered]) {
          const found = id ? marks.current.get(id) : undefined
          if (id && found) mark(id, found)
        }
      })
      .onNodeDrag(() => {
        if (glide.current.frame) stopGlide() // a ball dragged during Fit's move: the hand wins
      })
      .warmupTicks(40).cooldownTime(3000)
      .onEngineStop(() => {
        // the layout settled: the first time after a new middle node (or new nodes) their places are the first
        // picture Fit brings back. Later settles (after a drag) leave it as it is.
        if (keepSpots.current) {
          keepSpots.current = false
          for (const item of nodes.current.values()) {
            if (firstSpots.current.has(item.id)) continue
            if (item.id === view.current.center) firstSpots.current.set(item.id, { ...MIDDLE })
            else if ([item.x, item.y, item.z].every(Number.isFinite)) {
              firstSpots.current.set(item.id, { x: item.x as number, y: item.y as number, z: item.z as number })
            }
          }
        }
        if (!refit.current) return
        refit.current = false
        made.zoomToFit(MOVE_MS, FIT_PAD)
      })
    // a bit more room between the balls than the library's default (they are bigger than its dots)
    const charge = made.d3Force('charge') as unknown as { strength?: (value: number) => unknown } | undefined
    charge?.strength?.(-130)
    const link = made.d3Force('link') as unknown as { distance?: (value: (l: Link3D) => number) => unknown } | undefined
    const radius = (end: string | Node3D) => (typeof end === 'object' ? end.r : 0)
    link?.distance?.((l) => 30 + radius(l.source) + radius(l.target))

    // the box's width follows the page (Hide details, the window); jsdom (the tests) has no ResizeObserver
    setWidth(el.clientWidth)
    const watch = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => setWidth(el.clientWidth))
    watch?.observe(el)

    // a wheel away from the balls never reaches the library's controls (they listen on its canvas, inside this
    // box), so the page scrolls instead of the graph zooming. Nothing is prevented here: the browser scrolls as usual.
    const wheel = (event: Event) => {
      const found = nodesBox(made, nodes.current.values())
      if (!found) return // where the balls are is not known: the library zooms
      const rect = el.getBoundingClientRect()
      const { clientX, clientY } = event as MouseEvent
      const x = clientX - rect.left
      const y = clientY - rect.top
      const near = x >= found.left - NEAR && x <= found.right + NEAR && y >= found.top - NEAR && y <= found.bottom + NEAR
      if (!near) event.stopPropagation()
    }
    const how = { capture: true, passive: true }
    outer.addEventListener('wheel', wheel, how)

    return () => {
      stopGlide()
      outer.removeEventListener('wheel', wheel, how)
      watch?.disconnect()
      graph.current = null
      try {
        made.pauseAnimation()
        made._destructor()
        made.renderer().forceContextLoss()
      } catch {
        // already taken apart
      }
      const global = window as unknown as { scene?: unknown }
      if (global.scene === scene) delete global.scene // the library leaves its scene on window
      el.replaceChildren()
    }
  }, [mark, stopGlide])

  // new data or another node in the middle: the graph again. With the same node in the middle the nodes already
  // drawn keep their place; another node in the middle is laid out afresh, pinned at the centre, and the camera
  // turns to it (and fits all nodes in view once the layout settles).
  useEffect(() => {
    const made = graph.current
    if (!made) return
    const same = drawnCenter.current === center && nodes.current.size > 0
    drawnCenter.current = center
    view.current.center = center
    const amounts = data.nodes.filter((n) => n.type !== 'document' && (n.amount ?? 0) > 0).map((n) => n.amount as number)
    const biggest = Math.max(0, ...amounts)
    const smallest = amounts.length ? Math.min(...amounts) : 1
    const next = new Map<string, Node3D>()
    for (const node of data.nodes) {
      const item: Node3D = (same ? nodes.current.get(node.id) : undefined) ?? { id: node.id, node, r: 0 }
      item.node = node
      item.r = nodeSize(node, biggest, smallest) * RADIUS
      if (node.id === center) Object.assign(item, { fx: 0, fy: 0, fz: 0 })
      next.set(node.id, item)
    }
    nodes.current = next
    byId.current = new Map(data.nodes.map((node) => [node.id, node]))
    view.current.labelled = new Set([...data.nodes].sort((a, b) => (b.amount ?? 0) - (a.amount ?? 0))
      .slice(0, LABELLED_3D).map((node) => node.id))
    const biggestEdge = Math.max(0, ...data.edges.filter((e) => MONEY_EDGES.has(e.type)).map((e) => Math.abs(e.amount ?? 0)))
    const links: Link3D[] = data.edges.filter((edge) => next.has(edge.source) && next.has(edge.target)).map((edge) => {
      const money = MONEY_EDGES.has(edge.type)
      // as in 2D: a link has its source's colour; a document or "buys like" link a thin line of its own colour
      const colour = money ? TYPE_COLOURS[next.get(edge.source)!.node.type]
        : edge.type === 'BUYS_LIKE' ? TYPE_COLOURS.customer : TYPE_COLOURS.document
      return { source: edge.source, target: edge.target, edge, colour, width: money ? edgeWidth(edge, biggestEdge) * EDGE : 0 }
    })
    if (!same) {
      stopGlide()
      firstSpots.current = new Map() // a new first picture, kept when this layout settles
      keepSpots.current = true
      refit.current = true
      startCamera(made, [...next.values()]) // the new nodes have no place yet: the distance for their number
    } else {
      // the same middle node (Similar customers): the places kept stay; new nodes get theirs when the layout settles
      for (const id of firstSpots.current.keys()) if (!next.has(id)) firstSpots.current.delete(id)
      if ([...next.keys()].some((id) => !firstSpots.current.has(id))) keepSpots.current = true
    }
    made.graphData({ nodes: [...next.values()], links })
    markAll()
  }, [data, center, markAll, stopGlide])

  // the panel or a search can select a node too: its ring moves (nothing is laid out again)
  useEffect(() => {
    view.current.selected = selected
    markAll()
  }, [selected, markAll])

  // another theme: the scene's background and the links' strength, and every name tag and ring painted again in
  // the new colours. The data is not given again: the layout does not run, the balls and the first picture stay.
  useEffect(() => {
    const made = graph.current
    if (!made || tint.current === colours) return
    tint.current = colours
    made.backgroundColor(colours.box).linkOpacity(colours.dark ? LINK_OPACITY_DARK : LINK_OPACITY)
    for (const [id, item] of marks.current) {
      if (item.label) {
        const text = String(item.label.userData.text ?? '')
        drop(item.group, item.label)
        item.label = textSprite(text, colours)
        if (item.label) item.group.add(item.label)
      }
      for (const key of ['middle', 'ring'] as const) {
        const ring = item[key]
        if (!ring) continue
        drop(item.group, ring) // `mark` makes the rings still needed again, in the new colours
        item[key] = null
      }
      mark(id, item)
    }
  }, [colours, mark])

  // full screen (the height) and Hide details (the width) resize the drawing
  useEffect(() => {
    view.current.height = drawHeight
    view.current.narrow = narrow
    const made = graph.current
    if (!made) return
    made.width(width || mount.current?.clientWidth || 800).height(drawHeight)
    markAll() // the names keep their size on the screen
  }, [width, drawHeight, narrow, markAll])

  // Fit: back to the first picture, as 2D's Fit. Every ball with a kept place glides back to it in MOVE_MS
  // (held there on each frame, so the layout does not pull it elsewhere); at the end the middle node is pinned at
  // the centre again and the others are let go, standing still. The layout is not run again: nothing spreads out
  // afresh. Balls without a kept place (the layout has not settled yet) stay where they are. The camera moves
  // straight in front at the same time, as far away as the first picture asks (zoomToFit alone would keep the
  // angle the graph was turned to). Pressing it again starts the move again from where the balls are.
  const fit = () => {
    const made = graph.current
    if (!made) return
    stopGlide()
    const all = [...nodes.current.values()]
    const spots = firstSpots.current
    const items = all.filter((item) => spots.has(item.id))
    startCamera(made, all.map((item) => ({ ...item, ...spots.get(item.id) }))) // the distance for the first picture
    if (!items.length) return // no first picture yet: only the camera
    const from = new Map(items.map((item) => [item.id, { x: item.x ?? 0, y: item.y ?? 0, z: item.z ?? 0 }]))
    const engine = engineOf(made)
    let begin: number | null = null
    const step = (now: number) => {
      begin ??= now
      const done = Math.min(1, (now - begin) / MOVE_MS)
      const eased = 1 - (1 - done) ** 3 // fast at first, gently at the end
      for (const item of items) {
        const a = from.get(item.id) as Spot
        const b = spots.get(item.id) as Spot
        const at = { x: a.x + (b.x - a.x) * eased, y: a.y + (b.y - a.y) * eased, z: a.z + (b.z - a.z) * eased }
        Object.assign(item, at, { fx: at.x, fy: at.y, fz: at.z, vx: 0, vy: 0, vz: 0 })
      }
      engine?.resetCountdown() // the library draws the balls and links where they are now
      if (done < 1) {
        glide.current.frame = requestAnimationFrame(step)
        return
      }
      for (const item of items) {
        if (item.id === view.current.center) Object.assign(item, MIDDLE, { fx: MIDDLE.x, fy: MIDDLE.y, fz: MIDDLE.z })
        else {
          delete item.fx
          delete item.fy
          delete item.fz
        }
      }
      glide.current = { frame: 0, items: [] }
    }
    glide.current = { frame: requestAnimationFrame(step), items }
  }

  const save = () => {
    const made = graph.current
    if (!made) return
    setSaving(true)
    setSaveError('')
    const types = TYPE_ORDER.filter((type) => data.nodes.some((node) => node.type === type))
    const paper = pngPaper(colours) // white in the light theme, the dark card in the dark one
    new Promise<string>((resolve) => {
      // drawn once more at twice the size, read at once (the canvas keeps no copy of its last picture)
      const renderer = made.renderer()
      const ratio = renderer.getPixelRatio()
      renderer.setPixelRatio(2)
      renderer.render(made.scene(), made.camera())
      const shot = renderer.domElement.toDataURL('image/png')
      renderer.setPixelRatio(ratio)
      renderer.render(made.scene(), made.camera())
      resolve(shot)
    })
      .then((shot) => withLegend(shot, types, paper))
      .then((png) => downloadImage(png, pngName(title || 'knowledge_graph'), title, subtitle, paper))
      .catch(() => setSaveError('The PNG could not be made in this browser.'))
      .finally(() => setSaving(false))
  }

  const present = TYPE_ORDER.filter((type) => data.nodes.some((node) => node.type === type))
  const centerLabel = data.nodes.find((node) => node.id === center)?.label ?? 'the search'
  const selectedLabel = data.nodes.find((node) => node.id === selected)?.label
  return (
    <Card className="px-4 pt-3 pb-3 max-[700px]:px-2.5">
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-0 text-[13.5px] font-semibold text-heading [overflow-wrap:anywhere]">{title}</div>
        <span className="ml-auto flex items-center gap-1.5 max-[700px]:ml-0">
          <Button type="button" variant="outline" size="sm" onClick={fit} title="Back to the starting view">
            <Maximize aria-hidden="true" />Fit
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={save} aria-busy={saving || undefined}
            className={cn(saving && 'pointer-events-none opacity-80')}>
            {saving ? <Spinner /> : <Download aria-hidden="true" />}Download PNG
          </Button>
        </span>
      </div>
      <div ref={box} className="graph3d w-full min-w-0 overflow-hidden rounded-lg border border-border bg-muted" role="img"
        aria-label={`${describeGraph(data, centerLabel)} Drawn in 3D.`}>
        <div className="flex min-h-7 flex-wrap items-center justify-center gap-x-3.5 gap-y-1 overflow-hidden px-2 text-[11px] text-muted-foreground max-[480px]:gap-x-2 max-[480px]:text-[10px]"
          aria-hidden="true">
          {present.map((type) => (
            <span key={type} className="inline-flex items-center gap-1.5">
              <span className="inline-block size-2.5 rounded-full" style={{ background: TYPE_COLOURS[type] }} />{TYPE_NAMES[type]}
            </span>
          ))}
        </div>
        <div ref={mount} className="graph3d-canvas w-full" style={{ height: drawHeight }} />
      </div>
      {saveError && (
        <div className="mt-2 rounded-lg border border-destructive/20 bg-danger-soft px-3 py-2 text-[12.5px] text-destructive" role="alert">{saveError}</div>
      )}
      <div className="mt-2 text-xs leading-relaxed text-muted-foreground">
        {selectedLabel ? `Selected: ${selectedLabel}. ` : ''}Click a node for its details; double-click it (or use Open) to
        go into it; click the node in the middle to go back. Drag a ball to move it, drag the space to turn the
        graph, right-drag to move it; scroll on the graph or pinch to zoom; Fit brings back the first picture.
      </div>
    </Card>
  )
}
