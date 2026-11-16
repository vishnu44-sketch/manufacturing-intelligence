// Where the Knowledge graph's nodes sit in 2D (pure: no React, no ECharts): the node in the middle at (0, 0), the
// others evenly spaced on a ring around it - with many nodes on two or more rings, each a step further out and half
// a step turned. A ring is an ellipse as wide as the drawing box allows (a label card is wider than it is tall, so
// the nodes on top need more room sideways than the ones at the sides need up and down).
// Every node is a "block": its circle with its label card under it. From the inside out each ring grows until its
// blocks touch nothing, so at normal size no card lies on another one and every ring is only as big as it needs to
// be. Of 1, 2, 3 ... rings (and a few ways of sharing the nodes out over them) the one drawn biggest in the box is
// taken (16-Nov: up to 30 nodes with their names fit a box of 1000 x 580 px). Positions are in px; the option
// scales them down when the box is smaller.
// Nodes already drawn keep their place: a new one goes into the widest free gap of a ring (the next ring out when
// there is none). Only when that would make the whole graph clearly smaller in its box than fresh rings would (or
// leave more cards out), all nodes are put on fresh rings.
// Drawn much smaller than that (a phone, 40 nodes and more, zoomed out) cards would lie on each other: only then, as
// the last way out, hiddenCards says which ones are left out - the smaller amounts first; the node in the middle
// keeps its card.

/** What the layout needs of a node: its circle (dot = the diameter) and its label card under it, in px. */
export interface Block { id: string; dot: number; width: number; height: number }
export type Spots = Map<string, [number, number]>
/** A box in px: [left, top, right, bottom]. */
export type Rect = [number, number, number, number]

export const CARD_GAP = 6 // px between a circle and its card
const ROOM_X = 10 // px kept free between two blocks, sideways ...
const ROOM_Y = 8 // ... and up and down
const FIRST_RING = 100 // the first ring's half height before it grows
const RING_STEP = 76 // from one ring to the next (a new node among drawn ones; how many nodes each ring gets)
const RING_GAP = 24 // a ring starts this much outside the one before it ...
const GROW = 0.015 // ... and grows by 1.5 % (at least GROW_PX) until nothing touches
const GROW_PX = 2
const MOST_ROUNDS = 200
const MOST_RINGS = 5
const PILL: [number, number] = [22, 14] // around the middle node's card: where the middle of a link's pill must not be (the
// pill is about 60 x 18 px and lies along its line, so about this much of it reaches towards the card)
const TOP = -Math.PI / 2
const whole = (n: number) => Math.round(n) + 0 // a whole px (and never -0)
const SLACK = 4 // px two cards may lie on each other before one is left out (see hiddenCards)
const REDO = 0.9 // new nodes among the drawn ones: under 90 % of the size fresh rings would have, fresh rings are made
const BETTER = 1.04 // one ring more is taken only when it is drawn at least 4 % bigger
// the first ring's weights tried when nodes are shared out over the rings (16-Nov: five ways, so that up to 39 nodes
// keep every card in a 1000 x 580 box; with three, 38 and 39 nodes lost two)
const SPLITS = [40, 70, FIRST_RING, 160, 220]
const ROOMS = [1, 2, 3] // the room between the blocks tried (times ROOM_X / ROOM_Y)

/** The box a block fills when its circle's centre is at (x, y). */
export function blockRect(block: Block, x: number, y: number): Rect {
  const half = Math.max(block.dot, block.width) / 2
  return [x - half, y - block.dot / 2, x + half, y + block.dot / 2 + (block.height > 0 ? CARD_GAP + block.height : 0)]
}

/** Whether two blocks touch (with the room kept free between them; room = how many times ROOM_X / ROOM_Y). */
export function touches(a: Rect, b: Rect, room = 1): boolean {
  const [x, y] = [ROOM_X * room, ROOM_Y * room]
  return a[0] < b[2] + x && b[0] < a[2] + x && a[1] < b[3] + y && b[1] < a[3] + y
}

/** The box around every block: [left, top, right, bottom]. */
export function extent(blocks: Block[], spots: Spots): Rect {
  const all: Rect = [Infinity, Infinity, -Infinity, -Infinity]
  for (const block of blocks) {
    const at = spots.get(block.id)
    if (!at) continue
    const rect = blockRect(block, at[0], at[1])
    all[0] = Math.min(all[0], rect[0]); all[1] = Math.min(all[1], rect[1])
    all[2] = Math.max(all[2], rect[2]); all[3] = Math.max(all[3], rect[3])
  }
  return Number.isFinite(all[0]) ? all : [0, 0, 0, 0]
}

/** How wide a ring is for its height: the box's own shape, between a circle and twice as wide as tall. */
export function ringAspect(box: { width: number; height: number }): number {
  const shape = box.height > 0 ? box.width / box.height : 1
  return Math.min(2, Math.max(1, Number.isFinite(shape) ? shape : 1))
}

/** n nodes over the rings: more on the outer ones, which are longer (inner: the first ring's weight - the
 *  smaller, the more go to the outer rings). */
function split(n: number, rings: number, inner = FIRST_RING): number[] {
  const weights = Array.from({ length: rings }, (_, j) => inner + j * RING_STEP)
  const total = weights.reduce((sum, w) => sum + w, 0)
  const counts = weights.map((w) => Math.floor((n * w) / total))
  let left = n - counts.reduce((sum, c) => sum + c, 0)
  for (let j = rings - 1; left > 0; j = (j + rings - 1) % rings, left -= 1) counts[j] += 1
  return counts
}

// the middle node's place as a box, and where a pill must not sit: on the middle node's card
interface Middle { at: [number, number]; rect: Rect; card: Rect | null }

function middleOf(block: Block | undefined, at: [number, number], pills: boolean): Middle | null {
  if (!block) return null
  const rect = blockRect(block, at[0], at[1])
  const card: Rect | null = pills && block.height > 0
    ? [at[0] - block.width / 2 - PILL[0], at[1] + block.dot / 2 + CARD_GAP - PILL[1], at[0] + block.width / 2 + PILL[0], rect[3] + PILL[1]]
    : null
  return { at, rect, card }
}

/** Whether a block may sit here: it touches none of the placed ones, and the pill on its line to the middle node
 *  (half way) does not land on the middle node's card. */
function free(rect: Rect, at: [number, number], placed: Rect[], middle: Middle | null, room = 1): boolean {
  if (middle) {
    if (touches(rect, middle.rect, room)) return false
    const half: [number, number] = [(at[0] + middle.at[0]) / 2, (at[1] + middle.at[1]) / 2]
    if (middle.card && half[0] > middle.card[0] && half[0] < middle.card[2] && half[1] > middle.card[1] && half[1] < middle.card[3]) return false
  }
  return placed.every((other) => !touches(rect, other, room))
}

/** The nodes on `rings` rings, from the inside out: each ring starts just outside the one before it and grows
 *  until its nodes touch nothing (neither each other nor the rings inside it), so every ring is only as big as it
 *  needs to be. room: how much room is kept between the blocks (see touches). */
function onRings(around: Block[], middle: Middle | null, rings: number, aspect: number, inner?: number, room = 1): Spots {
  const counts = split(around.length, rings, inner)
  const spots: Spots = new Map()
  const placed: Rect[] = []
  let next = 0
  let tall = FIRST_RING
  counts.forEach((count, j) => {
    const nodes = around.slice(next, next + count)
    next += count
    for (let round = 0; ; round += 1) {
      const mine: Rect[] = []
      const at: [number, number][] = []
      let fits = true
      nodes.forEach((block, i) => {
        // from the top, clockwise; every second ring half a step turned. The first ring too when its number is
        // even: then no node sits straight under the middle node, whose card hangs there
        const turned = j === 0 ? (count % 2 === 0 ? 0.5 : 0) : (j % 2) / 2
        const angle = TOP + ((i + turned) * 2 * Math.PI) / count
        const spot: [number, number] = [whole(aspect * tall * Math.cos(angle)), whole(tall * Math.sin(angle))]
        const rect = blockRect(block, spot[0], spot[1])
        if (fits && (!free(rect, spot, placed, middle, room) || mine.some((other) => touches(rect, other, room)))) fits = false
        mine.push(rect)
        at.push(spot)
      })
      if (fits || round >= MOST_ROUNDS) {
        nodes.forEach((block, i) => spots.set(block.id, at[i]))
        placed.push(...mine)
        break
      }
      tall += Math.max(GROW_PX, tall * GROW)
    }
    tall += RING_GAP // the next ring starts a little further out
  })
  return spots
}

/** How much of its normal size a layout keeps in this box (1 = all of it fits), the same sum as the option's
 *  frameOf: only the distances between the nodes' centres shrink - what sticks out of the centres' box (half a
 *  circle, the cards) keeps its size. (ECharts makes the centres' box 2 wide when they are all in a line.) */
export function scaleIn(blocks: Block[], spots: Spots, box: { width: number; height: number }): number {
  const at = blocks.map((block) => spots.get(block.id)).filter((spot): spot is [number, number] => Boolean(spot))
  if (at.length === 0) return 1
  let [minX, maxX] = [Math.min(...at.map((spot) => spot[0])), Math.max(...at.map((spot) => spot[0]))]
  let [minY, maxY] = [Math.min(...at.map((spot) => spot[1])), Math.max(...at.map((spot) => spot[1]))]
  if (maxX === minX) { minX -= 1; maxX += 1 }
  if (maxY === minY) { minY -= 1; maxY += 1 }
  const all = extent(blocks, spots)
  const out = [Math.max(0, minX - all[0]), Math.max(0, minY - all[1]), Math.max(0, all[2] - maxX), Math.max(0, all[3] - maxY)]
  return Math.max(0.15, Math.min(1, (box.width - out[0] - out[2]) / (maxX - minX), (box.height - out[1] - out[3]) / (maxY - minY)))
}

/** A new node among the ones already drawn: in the widest gap of a ring they sit on, else on the next ring out. */
function freeSlot(block: Block, origin: [number, number], aspect: number, rings: { tall: number; angles: number[] }[],
  placed: Rect[], middle: Middle | null): [number, number] {
  const spot = (tall: number, angle: number): [number, number] =>
    [whole(origin[0] + aspect * tall * Math.cos(angle)), whole(origin[1] + tall * Math.sin(angle))]
  for (const ring of rings) {
    const angles = [...ring.angles].sort((a, b) => a - b)
    let angle = TOP
    let widest = 0
    angles.forEach((from, i) => {
      const gap = i + 1 < angles.length ? angles[i + 1] - from : angles[0] + 2 * Math.PI - from
      if (gap > widest) { widest = gap; angle = from + gap / 2 }
    })
    const at = spot(ring.tall, angle)
    if (free(blockRect(block, at[0], at[1]), at, placed, middle)) {
      ring.angles.push(angle)
      return at
    }
  }
  // no gap wide enough: rings further out, tried all the way round
  let tall = rings.length ? Math.max(...rings.map((ring) => ring.tall)) : FIRST_RING - RING_STEP
  for (let round = 0; round < 40; round += 1) {
    tall += RING_STEP
    for (let step = 0; step < 24; step += 1) {
      const angle = TOP + (step * Math.PI) / 12
      const at = spot(tall, angle)
      if (free(blockRect(block, at[0], at[1]), at, placed, middle)) {
        rings.push({ tall, angles: [angle] })
        return at
      }
    }
  }
  return spot(tall, TOP)
}

/** Where every node goes. blocks = the nodes as they are drawn (circle and card); centre = the node in the middle
 *  (null: none); box = the room in px; kept = the nodes already drawn, which stay where they are. */
export function ringLayout(blocks: Block[], centre: string | null, box: { width: number; height: number },
  kept: Spots = new Map(), pills = true): Spots {
  const aspect = ringAspect(box)
  const middleBlock = blocks.find((block) => block.id === centre)
  const around = blocks.filter((block) => block !== middleBlock)
  const drawn = blocks.filter((block) => kept.has(block.id))

  // fresh rings: the best of 1, 2, 3 ... rings (the nodes shared out over them in a few ways, with the normal room
  // between the blocks and with twice as much) - the one with the fewest cards on each other when it is drawn in the
  // box, and of those the one drawn biggest (the fewest rings when that is about the same). (Drawn smaller, the room
  // between the blocks shrinks: more room at normal size can keep the cards apart then.)
  const fresh = (): Spots => {
    const middle = middleOf(middleBlock, [0, 0], pills)
    const ordered = middleBlock ? [middleBlock, ...around] : around
    let best: Spots = new Map()
    let bestOut = Infinity
    let bestScale = 0
    const mostRings = Math.max(1, Math.min(MOST_RINGS, Math.ceil(around.length / 6)))
    for (let rings = 1; rings <= mostRings && around.length > 0 && !(bestOut === 0 && bestScale >= 1); rings += 1) {
      for (const inner of rings > 1 ? SPLITS : [FIRST_RING]) {
        for (const room of ROOMS) {
          const spots = onRings(around, middle, rings, aspect, inner, room)
          if (middleBlock) spots.set(middleBlock.id, [0, 0])
          const scale = scaleIn(blocks, spots, box)
          const out = hiddenCards(ordered, spots, scale, 0).size
          if (out < bestOut || (out === bestOut && scale > bestScale * BETTER)) { best = spots; bestOut = out; bestScale = scale }
          if (scale >= 1) break // at normal size: more room changes nothing
        }
      }
    }
    if (middleBlock) best.set(middleBlock.id, [0, 0])
    return best
  }
  if (drawn.length === 0) return fresh()

  // some nodes are drawn already: they stay, the new ones take free places around the same middle
  const spots: Spots = new Map()
  for (const block of drawn) spots.set(block.id, kept.get(block.id) as [number, number])
  const origin: [number, number] = (middleBlock && spots.get(middleBlock.id)) || [0, 0]
  if (middleBlock) spots.set(middleBlock.id, origin)
  const middle = middleOf(middleBlock, origin, pills)
  const placed: Rect[] = []
  const rings: { tall: number; angles: number[] }[] = []
  for (const block of around) {
    const at = spots.get(block.id)
    if (!at) continue
    placed.push(blockRect(block, at[0], at[1]))
    // which ring it sits on (a node dragged far off makes a ring of its own)
    const [dx, dy] = [(at[0] - origin[0]) / aspect, at[1] - origin[1]]
    const tall = Math.hypot(dx, dy)
    if (tall < 1) continue
    const ring = rings.find((r) => Math.abs(r.tall - tall) <= 14)
    if (ring) ring.angles.push(Math.atan2(dy, dx))
    else rings.push({ tall, angles: [Math.atan2(dy, dx)] })
  }
  rings.sort((a, b) => a.tall - b.tall)
  for (const block of around) {
    if (spots.has(block.id)) continue
    const at = freeSlot(block, origin, aspect, rings, placed, middle)
    placed.push(blockRect(block, at[0], at[1]))
    spots.set(block.id, at)
    rings.sort((a, b) => a.tall - b.tall)
  }
  if (drawn.length < blocks.length) {
    const again = fresh()
    const [scale, scaleAgain] = [scaleIn(blocks, spots, box), scaleIn(blocks, again, box)]
    if (scale < scaleAgain * REDO || hiddenCards(blocks, spots, scale).size > hiddenCards(blocks, again, scaleAgain).size) return again
  }
  return spots
}

/** The nodes whose card is left out when the places are drawn at `scale` of their normal size (the circles and the
 *  cards keep their size, only the distances shrink): a card that would lie on a card already shown, or on another
 *  node's circle. blocks come in the order of who keeps its card first. slack: the px a card may lie on another one
 *  (0: none at all - how ringLayout picks its rings). */
export function hiddenCards(blocks: Block[], spots: Spots, scale: number, slack = SLACK): Set<string> {
  const hidden = new Set<string>()
  if (scale >= 1) return hidden // at normal size nothing touches (ringLayout)
  const at = (block: Block): [number, number] => {
    const spot = spots.get(block.id) ?? [0, 0]
    return [spot[0] * scale, spot[1] * scale]
  }
  const circles = blocks.map((block) => {
    const [x, y] = at(block)
    return { id: block.id, rect: [x - block.dot / 2, y - block.dot / 2, x + block.dot / 2, y + block.dot / 2] as Rect }
  })
  // (a card's size is a careful guess, a little too big: SLACK px of it may lie on a neighbour card, a bit less on a circle)
  const lies = (a: Rect, b: Rect, by: number) => a[0] + by < b[2] && b[0] + by < a[2] && a[1] + by < b[3] && b[1] + by < a[3]
  const shown: Rect[] = []
  for (const block of blocks) {
    if (block.height <= 0) continue
    const [x, y] = at(block)
    const top = y + block.dot / 2 + CARD_GAP
    const card: Rect = [x - block.width / 2, top, x + block.width / 2, top + block.height]
    if (shown.some((other) => lies(card, other, slack)) || circles.some((circle) => circle.id !== block.id && lies(card, circle.rect, Math.max(0, slack - 1)))) hidden.add(block.id)
    else shown.push(card)
  }
  return hidden
}
