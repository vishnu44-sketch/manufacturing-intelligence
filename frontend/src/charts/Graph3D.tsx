// The Knowledge graph in 3D: the "3D view" switch of GraphPage. It loads lazily with 3d-force-graph and three.js,
// only when the user picks 3D, so the 2D page stays as small as before. The same nodes, colours, sizes and legend
// as the 2D graph (graphOption.ts), with the look both share (graphLook.ts): every node is a round disc in its
// type's colour with the type's white icon, always facing the camera; the node in the middle is bigger and blue,
// sits at the centre and has a soft light ring; the selected one has a dark ring (a light one on the dark theme).
// The other discs are all one size, chosen by how many there are (discSize: fewer nodes, bigger discs) - not by
// their amount, which their cards, the tooltip and the details panel give.
// Under every node a label card: up to FULL_CARDS nodes around the middle one, its name in bold and one small fact
// line; more (or when the full cards do not all fit clear of each other in the drawing: a small screen, long names),
// a short card with the name only (SHORT_NAME letters), and the full card on hover or when selected (made the first
// time it is needed, then kept). The node in the middle always has the full card.
// Where the nodes start (placeNodes): around the middle node on the screen as the camera first sees them, each disc
// with its card kept clear of the others (a card never covers another in that first picture), at different depths
// (so turning the graph shows it is 3D). The layout then only holds them there: a soft pull to each ball's own
// place (the 'home' force), links as long as those places ask, a short-range push that keeps two balls apart when
// one is dragged near another. The links are thin, light lines; the links of the hovered node, and of the
// selected one (not the middle node: that would be nearly all of them), carry a small pill that names them in
// plain words ('Bought', 'Handled by'), at most PILLS for one node.
// Three small buttons at the top right of the drawing: zoom in, zoom out, and reset (the same as Fit).
// A click selects a node (on the node in the middle: goes back); two clicks on the same node within DOUBLE ms go
// into it (the library has no double-click). A ball can be dragged to another place; a drag on the space around
// them turns the graph, a right-drag moves it. The mouse wheel zooms only on the balls (the box around them on the
// screen, NEAR px wider): on the empty space around them the page scrolls, as in 2D - in full screen too. A ball
// dropped somewhere stays there (its place moves with it). The first
// picture of a new middle node (where every ball is once the layout first settles) is kept, and Fit brings it back
// at once: every ball glides back to its place there (the middle one pinned at the centre again, the layout not run
// again) and the camera goes back straight in front. Download PNG saves the picture with the legend and the title,
// like the 2D one. Leaving 3D (or the page) stops the drawing loop and frees the WebGL context.
// The theme (light / dark): the scene's background, the discs, cards, pills, rings and the links follow it.
// A change of theme only repaints those - the data is not given again, so every ball stays where it is and the
// first picture kept for Fit stays too.
// How it is drawn: the discs, cards, rings and pills are sprites that skip the depth test, in groups drawn after
// the links (renderOrder), far ones first - so a link never crosses a disc, and a card is never behind a disc.
import ForceGraph3D, { type ForceGraph3DInstance } from '3d-force-graph'
import { Download, Maximize, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { type Camera, CanvasTexture, Group, LinearFilter, type PerspectiveCamera, SRGBColorSpace, Sprite, SpriteMaterial } from 'three'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'
import { type GraphData, TYPE_COLOURS, TYPE_NAMES, TYPE_ORDER } from '../components/graphData'
import type { GraphEdge, GraphNode, GraphNodeType } from '../types'
import { type Colours, FONT, NARROW, type Paper, downloadImage, fade, pngName, pngPaper, readColours } from './chartOption'
import { ICON_BOX, TYPE_ICONS, cutName, factLine, linkWords } from './graphLook'
import { LINK_OPACITY, LINK_OPACITY_DARK, MONEY_EDGES, describeGraph, edgeTip, edgeWidth, nodeTip } from './graphOption'
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
export const FULL_CARDS = 15 // up to this many nodes around the middle one, every card has the name and the fact line
export const SHORT_NAME = 14 // more: a short card, the name cut to this many letters (hover / select: the full card)
export const MIDDLE_DISC = 56 // px: the disc of the node in the middle, in the first picture
export const PILLS = 12 // the most link pills one node shows (its biggest links first)
export const ZOOM_STEP = 0.22 // a click on + / - moves the camera this share of its distance to the centre
export const ZOOM_NEAR = 30 // the closest and the furthest the buttons bring the camera
export const ZOOM_FAR = 3000
const ZOOM_MS = 250
const ICON_WHITE = '#fff' // the icon inside a disc
const NEAR = 40 // px around the balls where the mouse wheel still zooms
const LEGEND = 28 // px: the legend row above the drawing
const EDGE = 0.07 // a link's width per px of the 2D line (thin), on top of EDGE_MIN; documents and "buys like"
const EDGE_MIN = 0.25 // are the thinnest lines
const MOVE_MS = 800 // camera moves: slow and gentle
const FIT_PAD = 24 // px kept free around the nodes and their cards, in the first picture and after Fit
const CARD_GAP = 5 // px between a disc and the card under it
const MIDDLE_BELOW = 1.4 // the middle node's card starts this many radii under its middle (under its soft ring)
const HALO = 1.22 // the middle node's soft ring, in radii of its disc
const ROOM_X = 6 // px kept free between two nodes (their discs and cards) in the first picture, side by side ...
const ROOM_Y = 4 // ... and one above the other
const PLACE_STEP = 8 // px: the grid the places are looked for on
const PLACE_MS = 60 // no other way round the rings is tried once the places took this long (many nodes, little room)
const DEPTH = 0.3 // the nodes lie this share of the camera's first distance in front of or behind the middle one
const HOME = 0.3 // how strongly the layout pulls each ball back to its own place
const PUSH_REACH = 1.5 // the push between balls reaches this many disc sizes (only a ball dragged near another)
const MIDDLE = { x: 0, y: 0, z: 0 } // where the node in the middle sits, and where the camera looks

/** The size of every disc around the middle node, in px in the first picture, by how many there are: up to 10
 *  big, up to 25 medium, more smaller - all the same size, so none looks more important than the others. */
export function discSize(outer: number): number {
  return outer <= 10 ? 40 : outer <= 25 ? 32 : 26
}

/** The graph's units per px of the first picture: a little more for more nodes, so the links grow longer (and the
 *  camera starts further away) as their number grows. */
export function layoutUnit(outer: number): number {
  return 0.25 + 0.006 * outer
}

/** How far the camera starts in front of the middle node: 1 px of the first picture is layoutUnit there. */
export function startDistance(outer: number, height: number, fov = 50): number {
  return (layoutUnit(outer) * height) / (2 * Math.tan((fov * Math.PI) / 360))
}

interface Spot {
  x: number
  y: number
  z: number
}

/** A card's size on the screen, in px. */
interface CardSize {
  w: number
  h: number
}

/** A node as the library holds it (it adds x, y, z and its speed). r: its disc's radius; card: the size of the card
 *  it shows when not hovered (the first picture keeps those clear of each other). */
interface Node3D {
  id: string
  node: GraphNode
  r: number
  card: CardSize
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
  width: number
}

/** What is drawn for one node: its disc with the icon, its label card, its full card (only a node with a short
 *  card: made the first time it is hovered or selected, then kept), the soft ring of the middle node, the
 *  selected node's ring. */
interface Marks {
  group: Group
  icon: Sprite | null
  label: Sprite | null
  full: Sprite | null
  middle: Sprite | null
  ring: Sprite | null
}

const MARK_KEYS = ['icon', 'label', 'full', 'middle', 'ring'] as const

/** The texts of a node's card: short = the name only, cut to SHORT_NAME letters; else the name (cut shorter on a
 *  narrow screen) and the fact line (its amount, when it has one). */
function cardText(node: GraphNode, short: boolean, narrow: boolean): { name: string; fact: string; short: boolean } {
  if (short) return { name: cutName(node.label, SHORT_NAME), fact: '', short }
  return { name: cutName(node.label, narrow ? 18 : 26), fact: factLine(node), short }
}

/** A small canvas to draw a sprite's picture on; null where the browser has none. */
function drawing(width: number, height: number): { canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D } | null {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  let ctx: CanvasRenderingContext2D | null = null
  try {
    ctx = canvas.getContext('2d')
  } catch {
    ctx = null
  }
  return ctx ? { canvas, ctx } : null
}

/** The sprite of a drawn canvas. It skips the depth test (see the top of the file); order = which sprites are
 *  drawn over which: rings 1, discs 2, cards 3. fixed: it keeps its size on the screen (scaled in px). */
function spriteOf(canvas: HTMLCanvasElement, order: number, fixed: boolean): Sprite {
  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  if (fixed) texture.minFilter = LinearFilter
  const sprite = new Sprite(new SpriteMaterial({ map: texture, transparent: true, depthTest: false, depthWrite: false, sizeAttenuation: !fixed }))
  sprite.renderOrder = order
  return sprite
}

/** A node's disc: a circle in its colour with a thin rim in the card's colour (so two discs that overlap can be
 *  told apart) and its type's icon in white, as a sprite - it always faces the camera. */
function iconSprite(type: GraphNodeType, colour: string, colours: Colours): Sprite | null {
  const size = 128
  const made = drawing(size, size)
  if (!made) return null
  const { canvas, ctx } = made
  const rim = 4
  ctx.fillStyle = colour
  ctx.beginPath()
  ctx.arc(size / 2, size / 2, size / 2 - rim, 0, Math.PI * 2)
  ctx.fill()
  ctx.strokeStyle = colours.surface
  ctx.lineWidth = rim
  ctx.stroke()
  if (typeof Path2D !== 'undefined') {
    const scale = (size * 0.5) / ICON_BOX // the icon fills half the disc
    ctx.save()
    ctx.translate((size - ICON_BOX * scale) / 2, (size - ICON_BOX * scale) / 2)
    ctx.scale(scale, scale)
    ctx.fillStyle = ICON_WHITE
    ctx.fill(new Path2D(TYPE_ICONS[type]))
    ctx.restore()
  }
  const sprite = spriteOf(canvas, 2, false)
  sprite.userData = { kind: 'icon', type, colour }
  return sprite
}

const UP = { x: 0, y: 1, z: 0 }

const CARD_SCALE = 2 // the cards are drawn at twice their size: sharp on every screen
const NAME_FONT = `600 ${12 * CARD_SCALE}px ${FONT}`
const FACT_FONT = `400 ${10.5 * CARD_SCALE}px ${FONT}`

/** A card's size on the screen (px): as wide as its longest line and a margin; a short card (the name only) is a
 *  little slimmer. null where the browser has no canvas. */
function cardSize(name: string, fact: string, short: boolean): CardSize | null {
  const probe = drawing(1, 1)
  if (!probe) return null
  probe.ctx.font = NAME_FONT
  let wide = probe.ctx.measureText(name).width
  if (fact) {
    probe.ctx.font = FACT_FONT
    wide = Math.max(wide, probe.ctx.measureText(fact).width)
  }
  return { w: (Math.ceil(wide) + (short ? 14 : 20) * CARD_SCALE) / CARD_SCALE, h: fact ? 40 : short ? 24 : 26 }
}

/** A label card: the name in bold and the fact line under it (muted), on a rounded box in the card's colour with a
 *  thin border; a short card has the name only. A sprite that keeps its size on the screen (scaled in `mark`) and
 *  sits just under its disc, also when the graph is turned (userData.below = how far under the node's middle, set
 *  in `mark`). */
function cardSprite(name: string, fact: string, short: boolean, colours: Colours): Sprite | null {
  const scale = CARD_SCALE
  const size = cardSize(name, fact, short)
  if (!size) return null
  const width = Math.round(size.w * scale)
  const height = size.h * scale
  const made = drawing(width, height)
  if (!made) return null
  const { canvas, ctx } = made
  ctx.fillStyle = colours.surface
  ctx.strokeStyle = colours.line
  ctx.lineWidth = scale
  ctx.beginPath()
  ctx.roundRect?.(scale / 2, scale / 2, width - scale, height - scale, 8 * scale)
  ctx.fill()
  ctx.stroke()
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.font = NAME_FONT
  ctx.fillStyle = colours.ink
  ctx.fillText(name, width / 2, (fact ? 14 : height / scale / 2 + 0.5) * scale)
  if (fact) {
    ctx.font = FACT_FONT
    ctx.fillStyle = colours.muted
    ctx.fillText(fact, width / 2, 28.5 * scale)
  }
  const sprite = spriteOf(canvas, 3, true)
  sprite.center.set(0.5, 1 + (CARD_GAP * scale) / height) // under the disc, a small gap above the card
  sprite.userData = { kind: 'card', width: width / scale, height: height / scale, text: `${name}\n${fact}`, name, fact, short, below: 0 }
  // "under" is down on the screen: when the graph is turned, the card moves with the camera's own up
  sprite.onBeforeRender = (_renderer, _scene, camera: Camera) => {
    sprite.position.set(UP.x, UP.y, UP.z).applyQuaternion(camera.quaternion).multiplyScalar(-Number(sprite.userData.below))
  }
  return sprite
}

/** A link's pill: its plain words on a small rounded box, a sprite that keeps its size on the screen. */
function pillSprite(text: string, colours: Colours): Sprite | null {
  const scale = 2
  const font = `500 ${10 * scale}px ${FONT}`
  const probe = drawing(1, 1)
  if (!probe) return null
  probe.ctx.font = font
  const width = Math.ceil(probe.ctx.measureText(text).width) + 16 * scale
  const height = 18 * scale
  const made = drawing(width, height)
  if (!made) return null
  const { canvas, ctx } = made
  ctx.fillStyle = colours.surface
  ctx.strokeStyle = colours.line
  ctx.lineWidth = scale
  ctx.beginPath()
  ctx.roundRect?.(scale / 2, scale / 2, width - scale, height - scale, height / 2)
  ctx.fill()
  ctx.stroke()
  ctx.font = font
  ctx.fillStyle = colours.muted
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, width / 2, height / 2 + scale / 2)
  const sprite = spriteOf(canvas, 1, true)
  sprite.userData = { kind: 'pill', width: width / scale, height: height / scale, text }
  return sprite
}


/** A ring around a ball (a sprite always faces the camera, like the 2D dot's border). at = the ring's radius
 *  as a share of the sprite's size, to size it from the ball's radius. glow = the colour of a soft glow around it. */
function ringSprite(colour: string, line: number, glow = ''): Sprite | null {
  const made = drawing(128, 128)
  if (!made) return null
  const { canvas, ctx } = made
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
  const sprite = spriteOf(canvas, 1, false)
  sprite.userData = { kind: 'ring', at: radius / 128 }
  return sprite
}

/** Takes a sprite (a disc, card, ring or pill) out of its group and frees its picture. */
function drop(group: Group, sprite: Sprite) {
  group.remove(sprite)
  sprite.material.map?.dispose()
  sprite.material.dispose()
}

/** Shows or hides a card or ring. A hidden one moves to another layer too: the library's hover and click
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

/** What one node takes in the first picture, in px around its middle (y up): side = half its width (its disc or
 *  its card, the wider), up = above its middle (its disc; the middle node's soft ring), down = under it (the disc,
 *  the gap and the card). */
export interface Room {
  side: number
  up: number
  down: number
}

/** A node to place: its room and its place (px from the middle of the first picture, y up). fixed: it has its
 *  place already (the middle node; the nodes drawn before, when the same middle node gets more). */
export interface Placing {
  room: Room
  fixed: boolean
  x: number
  y: number
}

/** Every step from a wanted place to look for a free one, nearest first (on the drawing's own proportions), kept
 *  for the last drawing size. */
let stepsKept = { key: '', list: [] as [number, number][] }

function stepsFor(width: number, height: number): [number, number][] {
  const key = `${width}x${height}`
  if (stepsKept.key === key) return stepsKept.list
  // each step as one number (how far, then its number), so the browser's own fast sort of numbers orders them
  const steps: [number, number][] = []
  for (let dx = -width; dx <= width; dx += PLACE_STEP) {
    for (let dy = -height; dy <= height; dy += PLACE_STEP) steps.push([dx, dy])
  }
  const order = new Float64Array(steps.length)
  steps.forEach(([dx, dy], i) => { order[i] = Math.floor(((dx / width) ** 2 + (dy / height) ** 2) * 2 ** 20) * 2 ** 21 + i })
  order.sort()
  stepsKept = { key, list: Array.from(order, (value) => steps[value % 2 ** 21]) }
  return stepsKept.list
}

/** The box a node takes at (x, y), with half the free room kept around it. */
function taken(room: Room, x: number, y: number) {
  return { left: x - room.side - ROOM_X / 2, right: x + room.side + ROOM_X / 2, top: y + room.up + ROOM_Y / 2, bottom: y - room.down - ROOM_Y / 2 }
}

type Taken = ReturnType<typeof taken>

/** Where the nodes would like to be: one ring around the middle (up to 8 nodes) or a few (more), ellipses as wide
 *  and as high as the drawing allows; the nodes of the next ring sit between those of the one before. turn moves
 *  every node that share of the gap between two along its ring; extra: one ring more (or less). */
function ringSpots(count: number, wide: number, high: number, turn: number, extra: number): { x: number; y: number }[] {
  const rings = Math.max(1, (count <= 8 ? 1 : count <= 20 ? 2 : count <= 36 ? 3 : 4) + (count > 8 ? extra : 0))
  const radii = rings === 1 ? [Math.min(1, 0.6 + 0.05 * count)]
    : Array.from({ length: rings }, (_, k) => 0.45 + (0.55 * k) / (rings - 1))
  const total = radii.reduce((sum, r) => sum + r, 0)
  const counts = radii.map((r) => Math.floor((count * r) / total)) // more on the longer rings
  let left = count - counts.reduce((sum, n) => sum + n, 0)
  for (let k = rings - 1; left > 0; left--, k = k > 0 ? k - 1 : rings - 1) counts[k]++
  const spots: { x: number; y: number }[] = []
  radii.forEach((r, k) => {
    for (let j = 0; j < counts[k]; j++) {
      const angle = Math.PI / 2 + (2 * Math.PI * (j + turn + (k % 2) * 0.5)) / counts[k]
      spots.push({ x: wide * r * Math.cos(angle), y: high * r * Math.sin(angle) })
    }
  })
  return spots
}

/** The free place nearest to `wanted` (on a PLACE_STEP grid) where a node's box covers none of `boxes` and stays
 *  inside the drawing (less FIT_PAD); hit 0. When there is none, the place where it covers the least of them (hit:
 *  by how much, in px²). */
function freeSpot(room: Room, wanted: { x: number; y: number }, boxes: Taken[], width: number, height: number) {
  const most = Math.max(0, width / 2 - FIT_PAD - room.side - 0.5)
  let top = height / 2 - FIT_PAD - room.up - 0.5
  let bottom = -(height / 2 - FIT_PAD - room.down - 0.5)
  if (bottom > top) top = bottom = (top + bottom) / 2 // no room up and down: on one line
  let least: { x: number; y: number; hit: number } | null = null
  for (const [dx, dy] of stepsFor(width, height)) {
    const x = wanted.x + dx
    const y = wanted.y + dy
    if (x < -most || x > most || y < bottom || y > top) continue
    const box = taken(room, x, y)
    let hit = 0
    for (const other of boxes) {
      const wide = Math.min(box.right, other.right) - Math.max(box.left, other.left)
      if (wide <= 0) continue
      const high = Math.min(box.top, other.top) - Math.max(box.bottom, other.bottom)
      if (high > 0) hit += wide * high
      if (least && hit >= least.hit) break // no better than the best one yet (fast in a crowded drawing)
    }
    if (!hit) return { x, y, hit }
    if (!least || hit < least.hit) least = { x, y, hit }
  }
  return least ?? { x: Math.max(-most, Math.min(most, wanted.x)), y: Math.max(bottom, Math.min(top, wanted.y)), hit: 0 }
}

/** Places the nodes that are not fixed, for the first picture (a drawing width x height px): each as near to its
 *  place on the rings as it can be with its disc and card clear of every node placed before it (ROOM_X / ROOM_Y px
 *  between them), inside the drawing. A few ways round the rings are tried: the first where no card covers another
 *  is kept (else the one where they cover the least). The nodes are taken in their order: the first ones get the
 *  inner ring. Gives back how much they still cover of each other (px², with the free room): 0 = all clear. */
export function placeNodes(items: Placing[], width: number, height: number): number {
  const open = items.filter((item) => !item.fixed)
  if (!open.length) return 0
  const side = Math.max(...open.map((item) => item.room.side))
  const upDown = open.reduce((sum, item) => sum + item.room.up + item.room.down, 0) / open.length
  const wide = Math.max(0, width / 2 - FIT_PAD - side)
  const high = Math.max(0, height / 2 - FIT_PAD - upDown / 2)
  let best: { hit: number; spots: [number, number][] } | null = null
  const began = performance.now()
  for (const [turn, extra] of [[0, 0], [0.5, 0], [0.25, 1], [0.75, -1]]) {
    if (best && performance.now() - began > PLACE_MS) break // a crowded drawing: the best way found so far
    const wanted = ringSpots(open.length, wide, high, turn, extra)
    const boxes = items.filter((item) => item.fixed).map((item) => taken(item.room, item.x, item.y))
    let hit = 0
    open.forEach((item, i) => {
      const spot = freeSpot(item.room, wanted[i], boxes, width, height)
      item.x = spot.x
      item.y = spot.y
      hit += spot.hit
      boxes.push(taken(item.room, item.x, item.y))
    })
    if (!best || hit < best.hit) best = { hit, spots: open.map((item) => [item.x, item.y]) }
    if (!hit) break
  }
  const spots = best?.spots ?? []
  open.forEach((item, i) => {
    item.x = spots[i][0]
    item.y = spots[i][1]
  })
  return best?.hit ?? 0
}

/** The camera back to the starting view, in one smooth move: straight in front of the node in the middle, looking
 *  at it (the target a right-drag moved goes back to the centre too), at the first picture's distance (1 px there
 *  is `unit`) - or further, when a node or its card would be outside the view from there (FIT_PAD px kept around
 *  them). The controls are OrbitControls: they never roll the camera, so its "up" is still straight up. The nodes
 *  do not move. */
function startCamera(graph: ForceGraph3DInstance, nodes: Node3D[], unit: number, middle: string | null) {
  const camera = graph.camera() as PerspectiveCamera
  const height = Math.max(1, graph.height() || 1)
  const width = graph.width() || height
  const up = Math.tan(((camera.fov || 50) * Math.PI) / 360) // how far the view reaches up and down, per unit of distance
  const side = (up * width) / height // and to the sides
  // how far the camera must be for `world` units from the middle (and `px` more on the screen) to stay in view
  const needs = (world: number, px: number, half: number, reach: number) => (world > 0 ? world / (reach * Math.max(0.05, 1 - (FIT_PAD + px) / half)) : 0)
  let distance = (unit * height) / (2 * up)
  for (const node of nodes) {
    if (![node.x, node.y, node.z].every(Number.isFinite)) continue // not placed (yet)
    const x = Math.abs(node.x as number)
    const y = node.y as number
    const z = node.z as number
    const below = node.id === middle ? MIDDLE_BELOW : 1
    distance = Math.max(distance, z + needs(y + node.r, 0, height / 2, up),
      z + needs(node.r * below - y, CARD_GAP + node.card.h, height / 2, up),
      z + needs(x + node.r, 0, width / 2, side), z + needs(x, node.card.w / 2, width / 2, side))
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
  const links = useRef<Link3D[]>([]) // the links drawn now
  const pills = useRef(new Map<string, Sprite>()) // the link pills shown now, by the edge's id
  const pillBox = useRef<Group | null>(null) // the pills' own group in the scene, drawn over everything
  const byId = useRef(new Map<string, GraphNode>())
  const drawnCenter = useRef<string | null | undefined>(undefined)
  // the first picture's scale (graph units per px) and disc size, chosen for a new middle node by how many nodes
  // there are; kept while the middle node stays (the nodes Similar customers adds get the same size). short: the
  // nodes around the middle one show a short card at rest (more than FULL_CARDS, or the full ones did not fit)
  const plan = useRef({ unit: layoutUnit(0), disc: discSize(0), short: false })
  const homes = useRef(new Map<string, Spot>()) // each ball's own place, where the layout holds it (see 'home' below)
  const firstSpots = useRef(new Map<string, Spot>()) // the first picture: where each ball was when the layout first settled
  const keepSpots = useRef(false) // the next settle keeps the places of the balls that have none kept yet
  const glide = useRef({ frame: 0, items: [] as Node3D[] }) // Fit's move back: its next frame (0: none), the balls it moves
  const relink = useRef(() => {}) // gives the link force its lengths again (after the balls' own places changed)
  const lastClick = useRef({ id: '', at: 0 })
  const [width, setWidth] = useState(0)
  const narrow = width > 0 && width < NARROW
  const total = height ?? (narrow ? 440 : 580)
  const drawHeight = Math.max(200, total - LEGEND)
  // what the marks show now (read by the library's callbacks, outside React) (short: as plan.short)
  const view = useRef({ center, selected, hovered: null as string | null, short: false, height: drawHeight, narrow })
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const theme = useThemeName()
  const colours = useMemo(() => readColours(theme), [theme])
  const tint = useRef(colours) // the colours the scene is drawn with now (read by the library's callbacks)

  /** A sprite's scale for 1 px on the screen (the cards and pills keep their size when the camera moves). */
  const pxScale = useCallback(() => {
    const fov = (graph.current?.camera() as PerspectiveCamera | undefined)?.fov || 50
    return (2 * Math.tan((fov * Math.PI) / 360)) / Math.max(1, view.current.height)
  }, [])

  /** Makes (when needed), shows, sizes and places the disc, card and rings of one node, as the view is now. */
  const mark = useCallback((id: string, made: Marks) => {
    const item = nodes.current.get(id)
    if (!item || !graph.current) return
    const { center: middle, selected: chosen, hovered, narrow: small } = view.current
    const perPx = pxScale()
    // the disc: the type's colour and icon; the node in the middle is blue (the brand colour)
    const colour = id === middle ? tint.current.series[0] : TYPE_COLOURS[item.node.type]
    if (made.icon && (made.icon.userData.colour !== colour || made.icon.userData.type !== item.node.type)) {
      drop(made.group, made.icon)
      made.icon = null
    }
    if (!made.icon) {
      made.icon = iconSprite(item.node.type, colour, tint.current)
      if (made.icon) made.group.add(made.icon)
    }
    made.icon?.scale.set(item.r * 2, item.r * 2, 1)
    // the cards: `label` the one it shows at rest (the full card; a short one when there are many nodes - never
    // for the middle node), made with the node; `full` the full card of a node with a short one, made the first
    // time it is hovered or selected and then kept (shown instead of the short one while hovered or selected).
    // Each is made again when its texts changed.
    const short = view.current.short && id !== middle
    const open = short && (id === chosen || id === hovered)
    const below = item.r * (id === middle ? MIDDLE_BELOW : 1) // the middle node: under its soft ring
    for (const key of ['label', 'full'] as const) {
      const text = cardText(item.node, key === 'label' && short, small)
      const before = made[key]
      if (before && (before.userData.text !== `${text.name}\n${text.fact}` || before.userData.short !== text.short)) {
        drop(made.group, before)
        made[key] = null
      }
      if (!made[key] && (key === 'label' || open)) {
        made[key] = cardSprite(text.name, text.fact, text.short, tint.current)
        if (made[key]) made.group.add(made[key])
      }
      const card = made[key]
      if (!card) continue
      show(card, key === 'label' ? !open : open)
      card.userData.below = below
      card.position.set(0, -below, 0)
      card.scale.set(card.userData.width * perPx, card.userData.height * perPx, 1)
    }
    if (id === middle && !made.middle) {
      // a wide, soft ring in the disc's own blue, light
      made.middle = ringSprite(fade(tint.current.series[0], tint.current.dark ? 0.38 : 0.24), 16)
      if (made.middle) made.group.add(made.middle)
    }
    if (made.middle) {
      show(made.middle, id === middle)
      const size = (item.r * HALO) / made.middle.userData.at
      made.middle.scale.set(size, size, 1)
    }
    if (id === chosen && !made.ring) {
      made.ring = ringSprite(tint.current.ink, 7)
      if (made.ring) made.group.add(made.ring)
    }
    if (made.ring) {
      show(made.ring, id === chosen)
      const size = (item.r * (id === middle ? 1.6 : 1.3)) / made.ring.userData.at
      made.ring.scale.set(size, size, 1)
    }
  }, [pxScale])

  /** Frees everything drawn for one node. */
  const dropMarks = useCallback((made: Marks) => {
    for (const key of MARK_KEYS) {
      const sprite = made[key]
      if (sprite) drop(made.group, sprite)
      made[key] = null
    }
  }, [])

  const markAll = useCallback(() => {
    for (const [id, made] of marks.current) {
      if (nodes.current.has(id)) mark(id, made)
      else {
        dropMarks(made) // a node no longer drawn: its pictures are freed
        marks.current.delete(id)
      }
    }
  }, [mark, dropMarks])

  /** The link pills as the view is now: on the links of the hovered node and of the selected one (not when that
   *  is the node in the middle - nearly every link is its own), at most PILLS for a node, its biggest links first.
   *  A pill no longer wanted is freed; each one sits in the middle of its link (the library moves it with the link
   *  while the layout runs: linkPositionUpdate). */
  const showPills = useCallback(() => {
    const holder = pillBox.current
    if (!holder || !graph.current) return
    const { center: middle, selected: chosen, hovered } = view.current
    const wanted = new Map<string, Link3D>()
    for (const id of new Set([hovered, chosen === middle ? null : chosen])) {
      if (!id || !nodes.current.has(id)) continue
      links.current.filter((link) => link.edge.source === id || link.edge.target === id)
        .sort((a, b) => Math.abs(b.edge.amount ?? 0) - Math.abs(a.edge.amount ?? 0)).slice(0, PILLS)
        .forEach((link) => wanted.set(link.edge.id, link))
    }
    for (const [id, pill] of pills.current) {
      if (wanted.has(id)) continue
      drop(holder, pill)
      pills.current.delete(id)
    }
    const perPx = pxScale()
    for (const [id, link] of wanted) {
      let pill = pills.current.get(id)
      if (!pill) {
        const made = pillSprite(linkWords(link.edge.type), tint.current)
        if (!made) continue
        pill = made
        holder.add(pill)
        pills.current.set(id, pill)
        const a = nodes.current.get(link.edge.source)
        const b = nodes.current.get(link.edge.target)
        pill.position.set(((a?.x ?? 0) + (b?.x ?? 0)) / 2, ((a?.y ?? 0) + (b?.y ?? 0)) / 2, ((a?.z ?? 0) + (b?.z ?? 0)) / 2)
      }
      pill.scale.set(pill.userData.width * perPx, pill.userData.height * perPx, 1)
    }
  }, [pxScale])

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
    // the pills' own group, drawn after the links (the library gives them renderOrder 10) and the nodes (20)
    const holder = new Group()
    holder.renderOrder = 30
    pillBox.current = holder
    pills.current = new Map()
    scene.add(holder)

    // how long the layout wants a link: as far apart as its two ends' own places (see the forces below)
    const ofEnd = (end: string | Node3D) => (typeof end === 'object' ? end : nodes.current.get(end))
    const linkLength = (l: Link3D) => {
      const [a, b] = [ofEnd(l.source), ofEnd(l.target)]
      const [from, to] = [a && homes.current.get(a.id), b && homes.current.get(b.id)]
      if (from && to) return Math.max(1, Math.hypot(from.x - to.x, from.y - to.y, from.z - to.z))
      return 30 + (a?.r ?? 0) + (b?.r ?? 0)
    }
    const link = made.d3Force('link') as unknown as { distance?: (value: (l: Link3D) => number) => unknown } | undefined

    made.backgroundColor(tint.current.box).showNavInfo(false)
      .enableNodeDrag(true) // a ball can be dragged (read when the data is drawn: set before it)
      .width(el.clientWidth || 800).height(view.current.height)
      .nodeId('id').nodeRelSize(1)
      .nodeVal((n) => (n as Node3D).r ** 3) // the size the library takes a node to have: a link's arrow stops at its edge
      .nodeColor((n) => TYPE_COLOURS[(n as Node3D).node.type])
      .nodeLabel((n) => nodeTip((n as Node3D).node))
      // a node is our own group (the disc, the card, the rings) instead of the library's ball
      .nodeThreeObject((n) => {
        const item = n as Node3D
        const before = marks.current.get(item.id)
        if (before) dropMarks(before) // drawn before (another middle node since): its pictures are freed
        const group = new Group()
        group.renderOrder = 20 // after the links: a line never crosses a disc
        const made3: Marks = { group, icon: null, label: null, full: null, middle: null, ring: null }
        marks.current.set(item.id, made3)
        mark(item.id, made3)
        return group
      })
      // thin, light lines in the theme's muted colour
      .linkColor(() => tint.current.muted)
      .linkWidth((l) => (l as Link3D).width)
      .linkOpacity(tint.current.dark ? LINK_OPACITY_DARK : LINK_OPACITY)
      .linkDirectionalArrowLength((l) => 2.5 + (l as Link3D).width * 2)
      .linkDirectionalArrowRelPos(1)
      .linkDirectionalArrowColor(() => tint.current.muted)
      .linkLabel((l) => edgeTip((l as Link3D).edge, byId.current))
      // each time the library moves a link (the layout running, a ball dragged, Fit), its pill moves to its middle
      .linkPositionUpdate((_line, { start, end }, l) => {
        const pill = pills.current.get((l as Link3D).edge.id)
        if (pill) pill.position.set((start.x + end.x) / 2, (start.y + end.y) / 2, (start.z + end.z) / 2)
        return false // the library draws the line itself
      })
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
        showPills() // the hovered node's links are named
      })
      .onNodeDrag(() => {
        if (glide.current.frame) stopGlide() // a ball dragged during Fit's move: the hand wins
      })
      .onNodeDragEnd((n) => {
        // a ball dropped somewhere: that is its own place now (the layout does not pull it back)
        const item = n as Node3D
        if (item.id === view.current.center || ![item.x, item.y, item.z].every(Number.isFinite)) return
        homes.current.set(item.id, { x: item.x as number, y: item.y as number, z: item.z as number })
        relink.current() // its links as long as its new place asks
      })
      .warmupTicks(40).cooldownTime(3000)
      .onEngineStop(() => {
        // the layout settled: the first time after a new middle node (or new nodes) their places are the first
        // picture Fit brings back. Later settles (after a drag) leave it as it is. (The camera was put in front
        // when the nodes got their places: their places were known then.)
        if (!keepSpots.current) return
        keepSpots.current = false
        for (const item of nodes.current.values()) {
          if (firstSpots.current.has(item.id)) continue
          if (item.id === view.current.center) firstSpots.current.set(item.id, { ...MIDDLE })
          else if ([item.x, item.y, item.z].every(Number.isFinite)) {
            firstSpots.current.set(item.id, { x: item.x as number, y: item.y as number, z: item.z as number })
          }
        }
      })
    // The layout's forces. The balls start at their places (placeNodes): a link is as long as the places of its
    // two ends ask (else the library's way: a little longer than the two balls), so the links pull no ball away
    // from its place; 'home' pulls every ball softly back to its own place (as d3's forceX does: the further away,
    // the stronger); the push between balls (charge) reaches only PUSH_REACH disc sizes - set for each new middle
    // node, by the number of nodes - so it acts only when a ball is dragged close to another. The library's own
    // 'center' force is not needed: the middle node is pinned at the centre.
    // (the link force reads the lengths only when it is given them or new data: a dropped ball and Fit give them again)
    relink.current = () => link?.distance?.(linkLength)
    relink.current()
    const home = (alpha: number) => {
      for (const item of nodes.current.values()) {
        const spot = homes.current.get(item.id)
        if (!spot || ![item.x, item.y, item.z].every(Number.isFinite)) continue
        item.vx = (item.vx ?? 0) + (spot.x - (item.x as number)) * HOME * alpha
        item.vy = (item.vy ?? 0) + (spot.y - (item.y as number)) * HOME * alpha
        item.vz = (item.vz ?? 0) + (spot.z - (item.z as number)) * HOME * alpha
      }
    }
    made.d3Force('home', home as never).d3Force('center', null)

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
      relink.current = () => {}
      // every picture we made is freed: the discs, cards and rings of each node, and the pills
      for (const item of marks.current.values()) dropMarks(item)
      marks.current = new Map()
      for (const pill of pills.current.values()) drop(holder, pill)
      pills.current = new Map()
      pillBox.current = null
      try {
        scene.remove(holder)
      } catch {
        // the scene is gone already
      }
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
  }, [mark, dropMarks, showPills, stopGlide])

  // new data or another node in the middle: the graph again. Another node in the middle: every node gets a new
  // place (placeNodes: clear of each other's cards in the first picture, at different depths), the middle one
  // pinned at the centre, all discs one size by how many there are, and the camera turns to it (it frames them
  // all at once: their places are known now). With the same node in the middle the nodes already drawn keep their
  // place and size; the new ones (Similar customers) get a free place among them, of the same size.
  useEffect(() => {
    const made = graph.current
    if (!made) return
    const same = drawnCenter.current === center && nodes.current.size > 0
    drawnCenter.current = center
    view.current.center = center
    const outer = data.nodes.filter((node) => node.id !== center).length
    if (!same) {
      plan.current = { unit: layoutUnit(outer), disc: discSize(outer), short: outer > FULL_CARDS }
      homes.current = new Map()
    } else if (outer > FULL_CARDS) plan.current.short = true // more nodes now (Similar customers): short cards
    const { unit, disc } = plan.current
    const viewWidth = made.width() || mount.current?.clientWidth || 800
    const viewHeight = view.current.height
    const fov = (made.camera() as PerspectiveCamera).fov || 50
    const distance = (unit * viewHeight) / (2 * Math.tan((fov * Math.PI) / 360)) // the camera's, in the first picture
    const next = new Map<string, Node3D>()
    for (const node of data.nodes) {
      const item: Node3D = (same ? nodes.current.get(node.id) : undefined)
        ?? { id: node.id, node, r: ((node.id === center ? MIDDLE_DISC : disc) / 2) * unit, card: { w: 0, h: 0 } }
      item.node = node
      if (node.id === center) Object.assign(item, MIDDLE, { fx: 0, fy: 0, fz: 0 })
      next.set(node.id, item)
    }
    // the places (px of the first picture, y up) of the nodes that have none yet, clear of those that have one; with
    // the cards they show at rest (full or short, see plan.short)
    const placed = (item: Node3D) => [item.x, item.y, item.z].every(Number.isFinite)
    const placeAll = () => {
      view.current.short = plan.current.short
      const placing = [...next.values()].map((item) => {
        const text = cardText(item.node, plan.current.short && item.id !== center, view.current.narrow)
        item.card = cardSize(text.name, text.fact, text.short) ?? { w: 0, h: 0 }
        const px = item.id === center ? MIDDLE_DISC / 2 : disc / 2 // the disc's radius
        const room: Room = { side: Math.max(px, item.card.w / 2), up: px * (item.id === center ? HALO : 1),
          down: px * (item.id === center ? MIDDLE_BELOW : 1) + CARD_GAP + item.card.h }
        // a node with a place: where the camera of the first picture sees it
        const seen = placed(item) ? distance / Math.max(1, distance - (item.z as number)) / unit : 0
        return { item, room, fixed: item.id === center || placed(item), x: (item.x ?? 0) * seen, y: (item.y ?? 0) * seen }
      })
      return { placing, hit: placeNodes(placing, viewWidth, viewHeight) }
    }
    let { placing, hit } = placeAll()
    if (hit > 0 && !plan.current.short) {
      // the full cards do not all fit clear of each other in this drawing (a small screen, long names): short ones
      plan.current.short = true
      ;({ placing, hit } = placeAll())
    }
    // from px to the graph's units, each at its own depth: a node nearer the camera is drawn a little closer to the
    // middle and a little smaller, so the camera sees every disc the same size and every place as planned
    let depth = 0
    for (const one of placing) {
      if (one.fixed) continue
      depth += 1
      const z = DEPTH * distance * (((depth * 0.618034) % 1) * 2 - 1)
      const near = (distance - z) / distance
      Object.assign(one.item, { x: one.x * unit * near, y: one.y * unit * near, z, r: (disc / 2) * unit * near })
      homes.current.set(one.item.id, { x: one.item.x as number, y: one.item.y as number, z })
    }
    if (center && next.has(center)) homes.current.set(center, { ...MIDDLE })
    for (const id of homes.current.keys()) if (!next.has(id)) homes.current.delete(id)
    nodes.current = next
    byId.current = new Map(data.nodes.map((node) => [node.id, node]))
    const biggestEdge = Math.max(0, ...data.edges.filter((e) => MONEY_EDGES.has(e.type)).map((e) => Math.abs(e.amount ?? 0)))
    // a link with an amount is a thin line, a little wider for more; a document or "buys like" link the thinnest
    const drawn: Link3D[] = data.edges.filter((edge) => next.has(edge.source) && next.has(edge.target)).map((edge) => (
      { source: edge.source, target: edge.target, edge, width: MONEY_EDGES.has(edge.type) ? EDGE_MIN + edgeWidth(edge, biggestEdge) * EDGE : 0 }
    ))
    links.current = drawn
    if (view.current.hovered && !next.has(view.current.hovered)) view.current.hovered = null
    if (!same) {
      // the push between two balls: stronger for more nodes, reaching only a little past a disc
      const charge = made.d3Force('charge') as unknown as
        { strength?: (value: number) => unknown; distanceMax?: (value: number) => unknown } | undefined
      charge?.strength?.(-(30 + 2 * outer))
      charge?.distanceMax?.(PUSH_REACH * disc * unit)
      stopGlide()
      firstSpots.current = new Map() // a new first picture, kept when this layout settles
      keepSpots.current = true
      startCamera(made, [...next.values()], unit, center)
    } else {
      // the same middle node (Similar customers): the places kept stay; new nodes get theirs when the layout settles
      for (const id of firstSpots.current.keys()) if (!next.has(id)) firstSpots.current.delete(id)
      if ([...next.keys()].some((id) => !firstSpots.current.has(id))) keepSpots.current = true
    }
    made.graphData({ nodes: [...next.values()], links: drawn })
    markAll()
    showPills()
  }, [data, center, markAll, showPills, stopGlide])

  // the panel or a search can select a node too: its ring moves (nothing is laid out again)
  useEffect(() => {
    view.current.selected = selected
    markAll()
    showPills() // the selected node's links are named
  }, [selected, markAll, showPills])

  // another theme: the scene's background, the links' colour and strength, and every disc, card, ring and pill
  // painted again in the new colours. The data is not given again: the layout does not run, the balls and the
  // first picture stay, the camera too.
  useEffect(() => {
    const made = graph.current
    if (!made || tint.current === colours) return
    tint.current = colours
    made.backgroundColor(colours.box).linkOpacity(colours.dark ? LINK_OPACITY_DARK : LINK_OPACITY)
      .linkColor(() => colours.muted).linkDirectionalArrowColor(() => colours.muted) // given again: the lines are recoloured
    for (const [id, item] of marks.current) {
      dropMarks(item) // `mark` makes what is still needed again, in the new colours
      mark(id, item)
    }
    const holder = pillBox.current
    if (holder) for (const pill of pills.current.values()) drop(holder, pill)
    pills.current = new Map()
    showPills()
  }, [colours, mark, dropMarks, showPills])

  // full screen (the height) and Hide details (the width) resize the drawing
  useEffect(() => {
    view.current.height = drawHeight
    view.current.narrow = narrow
    const made = graph.current
    if (!made) return
    made.width(width || mount.current?.clientWidth || 800).height(drawHeight)
    markAll() // the cards and pills keep their size on the screen
    showPills()
  }, [width, drawHeight, narrow, markAll, showPills])

  // Fit: back to the first picture, as 2D's Fit. Every ball with a kept place glides back to it in MOVE_MS
  // (held there on each frame, so the layout does not pull it elsewhere); at the end the middle node is pinned at
  // the centre again and the others are let go, standing still. The layout is not run again: nothing spreads out
  // afresh. Balls without a kept place (the layout has not settled yet) stay where they are. The camera moves
  // straight in front at the same time, as far away as the first picture asks (zoomToFit alone would keep the
  // angle the graph was turned to). Each ball's own place is its first one again (a ball dropped elsewhere since
  // forgets that place). Pressing it again starts the move again from where the balls are.
  const fit = () => {
    const made = graph.current
    if (!made) return
    stopGlide()
    const all = [...nodes.current.values()]
    const spots = firstSpots.current
    const items = all.filter((item) => spots.has(item.id))
    startCamera(made, all.map((item) => ({ ...item, ...spots.get(item.id) })), plan.current.unit, view.current.center) // the first picture's distance
    if (!items.length) return // no first picture yet: only the camera
    for (const item of items) homes.current.set(item.id, { ...(spots.get(item.id) as Spot) })
    relink.current()
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

  // Zoom in / out: the camera moves ZOOM_STEP of its distance towards (or away from) the point the graph turns
  // around, in one short smooth move; the direction it looks from stays. Never closer than ZOOM_NEAR, never
  // further than ZOOM_FAR.
  const zoom = (closer: boolean) => {
    const made = graph.current
    if (!made) return
    const at = made.cameraPosition() as Spot
    const target = (made.controls() as { target?: Spot } | undefined)?.target
    const to = target ? { x: target.x, y: target.y, z: target.z } : { ...MIDDLE }
    const from = { x: at.x - to.x, y: at.y - to.y, z: at.z - to.z }
    const far = Math.hypot(from.x, from.y, from.z)
    if (!(far > 0)) return
    const next = Math.min(ZOOM_FAR, Math.max(ZOOM_NEAR, far * (closer ? 1 - ZOOM_STEP : 1 / (1 - ZOOM_STEP))))
    const by = next / far
    made.cameraPosition({ x: to.x + from.x * by, y: to.y + from.y * by, z: to.z + from.z * by }, to, ZOOM_MS)
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
      <div ref={box} className="graph3d relative w-full min-w-0 overflow-hidden rounded-lg border border-border bg-muted">
        <div role="img" aria-label={`${describeGraph(data, centerLabel)} Drawn in 3D.`}>
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
        {/* over the drawing's top right corner (beside the picture, not inside it: a screen reader finds them) */}
        <div className="graph3d-zoom absolute right-2 flex flex-col gap-1" style={{ top: LEGEND + 8 }}>
          <Button type="button" variant="outline" size="icon-sm" onClick={() => zoom(true)} aria-label="Zoom in" title="Zoom in">
            <ZoomIn aria-hidden="true" />
          </Button>
          <Button type="button" variant="outline" size="icon-sm" onClick={() => zoom(false)} aria-label="Zoom out" title="Zoom out">
            <ZoomOut aria-hidden="true" />
          </Button>
          <Button type="button" variant="outline" size="icon-sm" onClick={fit} aria-label="Reset the view" title="Back to the starting view">
            <RotateCcw aria-hidden="true" />
          </Button>
        </div>
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
