// Where the Knowledge graph's nodes sit in 2D: the middle node at (0, 0), the others evenly on rings that grow
// until no block (a circle with its card) touches another; drawn nodes keep their place and new ones take free
// places; which cards are left out when the rings are drawn smaller.
import { describe, expect, it } from 'vitest'
import { type Block, type Spots, blockRect, extent, hiddenCards, ringAspect, ringLayout, touches } from './graphLayout'

const BOX = { width: 1000, height: 640 }
const block = (id: string, width = 120): Block => ({ id, dot: 36, width, height: 40 })
const blocks = (count: number): Block[] => [{ id: 'mid', dot: 72, width: 220, height: 58 }, ...Array.from({ length: count }, (_, i) => block(`n${i}`))]

function clashes(all: Block[], spots: Spots): string[] {
  const rects = all.map((b) => ({ id: b.id, rect: blockRect(b, ...(spots.get(b.id) as [number, number])) }))
  return rects.flatMap((a, i) => rects.slice(i + 1).filter((b) => touches(a.rect, b.rect)).map((b) => `${a.id}/${b.id}`))
}

describe('ringLayout', () => {
  it('puts the middle node at (0, 0) and a single node above it', () => {
    const spots = ringLayout(blocks(1), 'mid', BOX)
    expect(spots.get('mid')).toEqual([0, 0])
    const [x, y] = spots.get('n0') as [number, number]
    expect(x).toBe(0)
    expect(y).toBeLessThan(-100)
    expect(ringLayout([block('only')], 'only', BOX).get('only')).toEqual([0, 0])
    expect(ringLayout([], null, BOX).size).toBe(0)
  })

  it.each([2, 5, 9, 14, 25, 40, 90])('%i nodes: a place for each, no block touches another', (count) => {
    const all = blocks(count)
    const spots = ringLayout(all, 'mid', BOX)
    expect(spots.size).toBe(count + 1)
    expect(clashes(all, spots)).toEqual([])
  })

  it('a ring is as wide as the box allows: wider than tall in a wide box, a circle in a tall one', () => {
    expect(ringAspect({ width: 1000, height: 640 })).toBeCloseTo(1.5625)
    expect(ringAspect({ width: 2000, height: 600 })).toBe(2)
    expect(ringAspect({ width: 300, height: 600 })).toBe(1)
    const wide = extent(blocks(6), ringLayout(blocks(6), 'mid', BOX))
    expect(wide[2] - wide[0]).toBeGreaterThan(wide[3] - wide[1])
  })

  it('each ring is only as big as it needs to be: up to 30 small blocks fit a 1000 x 580 box, none left out', () => {
    const room = { width: 1000 - 24, height: 580 - 52 }
    for (const count of [5, 12, 20, 26, 30]) {
      const all: Block[] = [{ id: 'mid', dot: 66, width: 250, height: 58 },
        ...Array.from({ length: count }, (_, i) => ({ id: `n${i}`, dot: 30, width: 108, height: 27 }))]
      const spots = ringLayout(all, 'mid', room, new Map(), false)
      expect(clashes(all, spots), `${count}`).toEqual([])
      const box = extent(all, spots)
      const scale = Math.min(1, room.width / (box[2] - box[0]), room.height / (box[3] - box[1]))
      expect(scale, `${count}`).toBeGreaterThan(0.85)                              // (nearly) at normal size
      expect(hiddenCards(all, spots, scale).size, `${count}`).toBe(0)
    }
  })

  it('without a node in the middle the nodes still sit on a ring', () => {
    const all = Array.from({ length: 6 }, (_, i) => block(`n${i}`))
    const spots = ringLayout(all, null, BOX)
    expect(spots.size).toBe(6)
    expect(clashes(all, spots)).toEqual([])
  })

  it('nodes already drawn keep their place and a new one takes the widest gap of their ring', () => {
    const before = blocks(4)
    const kept = ringLayout(before, 'mid', BOX)
    const after = [...before, block('new', 60)]
    const spots = ringLayout(after, 'mid', BOX, kept)
    for (const b of before) expect(spots.get(b.id), b.id).toEqual(kept.get(b.id))
    expect(clashes(after, spots)).toEqual([])
    // on the same ring as the others: as far from the middle (the ring's height)
    const aspect = ringAspect(BOX)
    const far = (id: string) => Math.hypot((spots.get(id) as [number, number])[0] / aspect, (spots.get(id) as [number, number])[1])
    expect(Math.abs(far('new') - far('n0'))).toBeLessThan(3)
  })

  it('a dragged node stays where it was dropped when nothing new comes in', () => {
    const all = blocks(5)
    const kept = ringLayout(all, 'mid', BOX)
    kept.set('n2', [333, -77])
    expect(ringLayout(all, 'mid', BOX, kept).get('n2')).toEqual([333, -77])
  })

  it('new nodes that would make the graph much smaller in its box put everything on fresh rings', () => {
    const before = blocks(3)
    const kept = ringLayout(before, 'mid', BOX)
    kept.set('n0', [3000, 0])                                                      // dragged far away
    const after = [...before, block('new')]
    const spots = ringLayout(after, 'mid', BOX, kept)
    expect(spots.get('n0')).not.toEqual([3000, 0])
    expect(clashes(after, spots)).toEqual([])
  })
})

describe('hiddenCards', () => {
  it('leaves no card out at normal size, and more of them the smaller the rings are drawn', () => {
    const all = blocks(25)
    const spots = ringLayout(all, 'mid', BOX)
    expect(hiddenCards(all, spots, 1).size).toBe(0)
    const some = hiddenCards(all, spots, 0.5)
    const more = hiddenCards(all, spots, 0.25)
    expect(some.size).toBeGreaterThan(0)
    expect(more.size).toBeGreaterThan(some.size)
  })

  it('a card that would lie on another node\'s circle is left out too', () => {
    const all = [block('a'), block('b')]
    const spots: Spots = new Map([['a', [0, 0]], ['b', [0, 40]]])                    // b's circle sits where a's card is
    expect([...hiddenCards(all, spots, 0.99)]).toEqual(['a'])
  })
})
