// The look the 2D and the 3D Knowledge graph share: an icon per node type (a path that an ECharts symbol and a
// canvas Path2D both take), a link's plain words, a node's fact line and a name cut for its label card.
import { describe, expect, it } from 'vitest'
import { TYPE_ORDER } from '../components/graphData'
import type { GraphNode } from '../types'
import { ICON_BOX, LINK_WORDS, TYPE_ICONS, cutName, factLine, linkWords } from './graphLook'

const node = (extra: Partial<GraphNode> = {}): GraphNode =>
  ({ id: 'customer:1', type: 'customer', type_name: 'Customer', key: '1', label: 'Aurora', sub: '', amount: null, amount_text: '', ...extra })

/** Every number of a path, in the order it is written. */
const numbers = (d: string) => (d.match(/-?\d*\.?\d+/g) ?? []).map(Number)

describe('TYPE_ICONS', () => {
  it('has one icon for every node type', () => {
    expect(Object.keys(TYPE_ICONS).sort()).toEqual([...TYPE_ORDER].sort())
    expect(new Set(Object.values(TYPE_ICONS)).size).toBe(TYPE_ORDER.length)   // no two the same
  })

  it.each(TYPE_ORDER)('%s: a closed path of plain path commands inside the 24 x 24 box', (type) => {
    const d = TYPE_ICONS[type]
    expect(d).toMatch(/^M[\dMLHVCSAZmlhvcsaz .,-]+Z$/)                         // only path commands and numbers
    expect(d.length).toBeLessThan(500)                                         // a simple shape
    // every sub-path is closed (a filled shape): as many Z as M
    expect((d.match(/Z/g) ?? []).length).toBe((d.match(/M/g) ?? []).length)
    // each sub-path starts inside the box
    for (const start of d.match(/M-?[\d.]+[ ,-]?-?[\d.]+/g) ?? []) {
      const [x, y] = numbers(start)
      expect(x).toBeGreaterThanOrEqual(0)
      expect(x).toBeLessThanOrEqual(ICON_BOX)
      expect(y).toBeGreaterThanOrEqual(0)
      expect(y).toBeLessThanOrEqual(ICON_BOX)
    }
    expect(Math.max(...numbers(d).map(Math.abs))).toBeLessThanOrEqual(ICON_BOX)
  })
})

describe('linkWords', () => {
  it('names every link type of the graph in plain words', () => {
    expect(LINK_WORDS).toMatchObject({ BOUGHT: 'Bought', HANDLED_BY: 'Handled by', IN_STATE: 'In state', IN_CATEGORY: 'In category' })
    for (const type of ['BOUGHT', 'IN_CATEGORY', 'HANDLED_BY', 'IN_STATE', 'BUYS_AS', 'COVERED_BY', 'BUYS_LIKE']) {
      expect(linkWords(type), type).toBe(LINK_WORDS[type])
      expect(LINK_WORDS[type]).toMatch(/^[A-Z][a-z]+( [a-z]+)*$/)
    }
    expect(linkWords('BUYS_AS')).toBe('Buys as')
    expect(linkWords('COVERED_BY')).toBe('Covered by')
    expect(linkWords('BUYS_LIKE')).toBe('Buys like')
  })

  it('tidies a type it does not know', () => {
    expect(linkWords('SHIPS_TO')).toBe('Ships to')
    expect(linkWords('made  in_plant')).toBe('Made in plant')
    expect(linkWords('')).toBe('')
  })
})

describe('factLine', () => {
  it('writes the amount short, with INR in front', () => {
    expect(factLine(node({ amount: 64000000 }))).toBe('INR 6.4 Cr')
    expect(factLine(node({ amount: 29088275 }))).toBe('INR 2.9 Cr')
    expect(factLine(node({ amount: 9000000 }))).toBe('INR 90 L')
    expect(factLine(node({ amount: 17800000000 }))).toBe('INR 1,780 Cr')
    expect(factLine(node({ amount: 900 }))).toBe('INR 900')
    expect(factLine(node({ amount: -250000 }))).toBe('INR -2.5 L')              // more credit notes than sales
    expect(factLine(node({ amount: 5000, sub: 'Chennai' }))).toBe('INR 5 K')    // the amount comes first
  })

  it('without an amount: what a similar customer shares, else the second line, else a page\'s first words', () => {
    expect(factLine(node({ shared_products: 40, score_text: '38%' }))).toBe('40 shared · 38%')
    expect(factLine(node({ amount: 0, shared_products: 3 }))).toBe('3 shared')
    expect(factLine(node({ sub: 'Chennai, Tamil Nadu' }))).toBe('Chennai, Tamil Nadu')
    expect(factLine(node({ type: 'document', sub: 'product_catalogue.pdf', text: 'Trochoid pumps' }))).toBe('product_catalogue.pdf')
    expect(factLine(node({ type: 'document', text: 'Trochoid pumps are positive displacement pumps for oil' })))
      .toBe('Trochoid pumps are positive d…')
    expect(factLine(node())).toBe('')
    expect(factLine(node({ amount: 0 }))).toBe('')
  })
})

describe('cutName', () => {
  it('keeps a short name and cuts a long one with …', () => {
    expect(cutName('Priya Iyer')).toBe('Priya Iyer')
    expect(cutName('Aurora Hydraulics Private Limited')).toBe('Aurora Hydraulics Private…')
    expect(cutName('Aurora Hydraulics Private Limited').length).toBeLessThanOrEqual(26)
    expect(cutName('Aurora Hydraulics Private Limited', 12)).toBe('Aurora Hydr…')
    expect(cutName('abcdefghijklmnopqrstuvwxyz')).toBe('abcdefghijklmnopqrstuvwxyz')   // exactly 26: as it is
    expect(cutName('  two   spaces  ')).toBe('two spaces')
    expect(cutName('')).toBe('')
  })
})
