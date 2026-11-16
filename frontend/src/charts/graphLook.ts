// The look the 2D and the 3D Knowledge graph share (pure: no React, no ECharts, no three.js): the white icon inside
// each node's circle, the plain words on a link's pill, and the texts of a node's label card (its name, cut when
// long, and one small fact line under it).
// The icons are SVG path `d` strings on a 24 x 24 box, drawn as filled shapes (the holes - windows, the pin's eye -
// are sub-paths that run the other way round, so the usual "nonzero" fill leaves them open). They work as an
// ECharts symbol ('path://' + d) and on a canvas (new Path2D(d), then fill).
import type { GraphNode } from '../types'
import { shortIndian } from './pickChart'

export const ICON_BOX = 24 // the icons are drawn on a 24 x 24 box

export const TYPE_ICONS: Record<GraphNode['type'], string> = {
  // a building with windows
  customer: 'M4 21V4a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v5h4a1 1 0 0 1 1 1v11Z' +
    'M7 6v2h2V6ZM10 6v2h2V6ZM7 10v2h2v-2ZM10 10v2h2v-2ZM7 14v2h2v-2ZM10 14v2h2v-2ZM16 12v2h2v-2ZM16 16v2h2v-2Z',
  // a box seen from a corner: its lid and its two sides
  product: 'M12 2l9 5-9 5-9-5ZM3 9.2l8 4.5V22l-8-4.5ZM21 9.2v8.3L13 22v-8.3Z',
  // a price tag with its hole
  category: 'M3 4a1 1 0 0 1 1-1h7.6a1 1 0 0 1 .7.3l8.4 8.4a1 1 0 0 1 0 1.4l-7.6 7.6a1 1 0 0 1-1.4 0L3.3 12.3a1 1 0 0 1-.3-.7Z' +
    'M7.5 6a1.5 1.5 0 0 0 0 3a1.5 1.5 0 0 0 0-3Z',
  // a person: head and shoulders
  sales_person: 'M12 3a4 4 0 0 1 0 8a4 4 0 0 1 0-8ZM4 21a8 8 0 0 1 16 0Z',
  // a map pin
  state: 'M12 2a7 7 0 0 1 7 7c0 5-7 13-7 13S5 14 5 9a7 7 0 0 1 7-7ZM12 6.5a2.5 2.5 0 0 0 0 5a2.5 2.5 0 0 0 0-5Z',
  // two arrows, one each way (goods out, money in)
  sale_type: 'M3 7h12V4l6 4.5-6 4.5v-3H3ZM21 17H9v3l-6-4.5L9 11v3h12Z',
  // a page with lines of text
  document: 'M6 2h8l5 5v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1ZM8 11v1.5h8V11ZM8 14.5V16h8v-1.5ZM8 18v1.5h5V18Z',
}

/** A link's type in plain words (the pill on the line). */
export const LINK_WORDS: Record<string, string> = {
  BOUGHT: 'Bought',
  HANDLED_BY: 'Handled by',
  IN_STATE: 'In state',
  IN_CATEGORY: 'In category',
  BUYS_AS: 'Buys as', // customer -> sale type (Domestic / Export / Service)
  COVERED_BY: 'Covered by', // category / product -> a PDF page
  BUYS_LIKE: 'Buys like', // customer -> a similar customer
}

/** 'BOUGHT' -> 'Bought'; a type not in the list is tidied: 'SHIPS_TO' -> 'Ships to'. */
export function linkWords(type: string): string {
  const known = LINK_WORDS[type]
  if (known) return known
  const words = (type ?? '').trim().toLowerCase().split(/[_\s]+/).filter(Boolean).join(' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** A name short enough for a label card: 'Aurora Hydraulics Private Limited' -> 'Aurora Hydraulics Private…'. */
export function cutName(name: string, max = 26): string {
  const text = (name ?? '').trim().replace(/\s+/g, ' ')
  return text.length > max ? `${text.slice(0, Math.max(1, max - 1)).trimEnd()}…` : text
}

/** The small line under a node's name: its net sales short ('INR 6.4 Cr') when it has an amount; else what a
 *  similar customer shares ('40 shared · 38%'), else its second line (the place, the product code, a page's
 *  file), else a document page's first words; '' when the node carries none of these. */
export function factLine(node: GraphNode): string {
  if (typeof node.amount === 'number' && Number.isFinite(node.amount) && node.amount !== 0) return `INR ${shortIndian(node.amount)}`
  const shared = [node.shared_products === undefined ? '' : `${node.shared_products} shared`, node.score_text ?? ''].filter(Boolean)
  if (shared.length) return shared.join(' · ')
  if (node.sub) return cutName(node.sub, 30)
  if (node.text) return cutName(node.text, 30)
  return ''
}
