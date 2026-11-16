// The ECharts option of the Knowledge graph (pure: no React): a 'graph' series whose nodes sit on rings around the
// node in the middle (graphLayout.ts gives the places; nothing wobbles). The look (15-Nov, graphLook.ts):
//  - a node is a circle in its type's colour (with a legend) with a white icon of its type inside; the node in the
//    middle is a bigger circle in the app's blue with a soft ring around it. Circle and icon are one small SVG
//    picture, so the icon stays in its circle when the graph is zoomed or a node is dragged;
//  - under each node a label card (the card's colour, rounded, a soft shadow): its name in bold, cut with … when
//    long, and one small fact line (the middle node: up to two);
//  - the links are thin straight grey lines (a document or "buys like" link dashed), each with a small pill that
//    names it in plain words. With more than PILL_LINKS links the pills show only on the links of the node under
//    the pointer and of the selected node, so they stay readable.
// Every node around the middle one has the same circle (16-Nov), its size chosen by how many nodes are drawn
// (nodeSizeFor), and a name on its card: with many nodes a compact card (the short name only; the fact line under
// the pointer and on the selected node). The amount is in the fact line, the tooltip and the details panel - the
// tooltip gives the full name, the type and the amounts as the app writes them. (nodeSize, by net sales, is the 3D
// view's.) Every colour is the theme's (colours).
import { type GraphData, TYPE_COLOURS, TYPE_NAMES, TYPE_ORDER, EDGE_NAMES } from '../components/graphData'
import type { GraphEdge, GraphNode } from '../types'
import { type Colours, FONT, cutText, escapeHtml, fade } from './chartOption'
import type { EChartsCoreOption } from './echarts'
import { type Block, CARD_GAP, type Spots, extent, hiddenCards, ringLayout } from './graphLayout'
import { ICON_BOX, TYPE_ICONS, cutName, factLine, linkWords } from './graphLook'

export const MIN_SIZE = 12
export const MAX_SIZE = 48
export const DOCUMENT_SIZE = 18
export const PILL_LINKS = 14 // with more links than this, a link's pill shows only for the hovered / selected node
export const MONEY_EDGES = new Set(['BOUGHT', 'HANDLED_BY', 'IN_STATE', 'BUYS_AS', 'IN_CATEGORY'])
export const LINK_OPACITY = 0.45 // a link's strength (2D and 3D)
export const LINK_OPACITY_DARK = 0.65

export interface GraphView {
  center?: string | null
  selected?: string | null // with many links: its links carry their pills
  narrow?: boolean
  width?: number // the drawing box in px (0 / none: not known yet)
  height?: number
  positions?: Spots // where the nodes already drawn are (they stay there)
  zoom?: number // the zoom and the middle of the view to keep (a rebuild that is not a new graph); zoomed in,
  // cards left out for want of room come back
  at?: number[]
}

/** A node's size on a log scale between the smallest and the biggest amount drawn: a sale type of 1,780 crore and
 *  a product of 20 lakh are on one graph, so a straight scale would leave every product a dot. (The 3D view's; the
 *  2D view draws every node around the middle one the same size: nodeSizeFor.) */
export function nodeSize(node: GraphNode, biggest: number, smallest = 1): number {
  if (node.type === 'document') return DOCUMENT_SIZE
  const amount = node.amount ?? 0
  if (amount <= 0 || biggest <= 0) return MIN_SIZE
  const low = Math.log10(Math.max(1, Math.min(smallest, biggest)))
  const high = Math.log10(Math.max(1, biggest))
  const share = high > low ? (Math.log10(Math.max(1, Math.min(amount, biggest))) - low) / (high - low) : 1
  return Math.round(MIN_SIZE + (MAX_SIZE - MIN_SIZE) * Math.max(0, share))
}

/** An edge's width: 1 to 8 px by its amount; a document or "buys like" link is a thin dashed line. */
export function edgeWidth(edge: GraphEdge, biggest: number): number {
  if (!MONEY_EDGES.has(edge.type) || edge.amount === undefined || biggest <= 0) return 1.2
  return Math.round((1 + 7 * Math.sqrt(Math.min(1, Math.abs(edge.amount) / biggest))) * 10) / 10
}

/** One sentence for screen readers. */
export function describeGraph(data: GraphData, centerLabel: string): string {
  const types = TYPE_ORDER.map((type) => [type, data.nodes.filter((n) => n.type === type).length] as const)
    .filter(([, n]) => n > 0).map(([type, n]) => `${n} ${TYPE_NAMES[type].toLowerCase()}`)
  return `Knowledge graph around ${centerLabel}: ${data.nodes.length} nodes (${types.join(', ')}) and ${data.edges.length} links.`
}

export function nodeTip(node: GraphNode): string {
  const rows = [`<div class="chart-tip-label">${escapeHtml(node.label)}</div>`,
    `<div class="chart-tip-row"><span class="chart-key" style="background:${TYPE_COLOURS[node.type]}"></span>` +
    `<span class="chart-tip-name">${escapeHtml(node.type_name || TYPE_NAMES[node.type])}</span>` +
    (node.amount_text ? `<b>${escapeHtml(node.amount_text)}</b>` : '') + '</div>']
  if (node.sub) rows.push(`<div class="chart-tip-row"><span class="chart-tip-name">${escapeHtml(node.sub)}</span></div>`)
  return rows.join('')
}

export function edgeTip(edge: GraphEdge, byId: Map<string, GraphNode>): string {
  const name = (id: string) => escapeHtml(cutText(byId.get(id)?.label ?? id, 40))
  const facts: [string, string | undefined][] = [
    ['Net sales', edge.amount_text], ['Quantity', edge.quantity_text], ['Invoices', edge.invoices_text],
    ['Mentions', edge.mentions === undefined ? undefined : String(edge.mentions)], ['Model', edge.model],
    ['Through its category', edge.through], ['Shared products', edge.shared_products === undefined ? undefined : String(edge.shared_products)],
    ['Overlap', edge.score_text],
  ]
  return `<div class="chart-tip-label">${name(edge.source)} → ${name(edge.target)}</div>` +
    `<div class="chart-tip-row"><span class="chart-tip-name">${escapeHtml(EDGE_NAMES[edge.type] ?? edge.type)}</span></div>` +
    facts.filter(([, value]) => value).map(([label, value]) =>
      `<div class="chart-tip-row"><span class="chart-tip-name">${label}</span><b>${escapeHtml(String(value))}</b></div>`).join('')
}


// ---------- the 2D look: circles with an icon, label cards, pills ----------

export const FULL_CARDS = 15 // up to this many nodes around the middle one, every card has its fact line
/** The circle of every node around the middle one in 2D, in px (16-Nov: "one small one big - can we use all same
 *  size, dynamic depending how many we have"): the same for all of them, whatever their amount - a document and a
 *  "buys like" customer too - and chosen by how many there are: up to 10 big, up to 25 medium, more small (a phone:
 *  up to 10 medium, more small). The amount is in the card's fact line, the tooltip and the details panel. */
export function nodeSizeFor(count: number, narrow = false): number {
  if (narrow) return count <= 10 ? 36 : 30
  return count <= 10 ? 44 : count <= 25 ? 36 : 30
}

/** How the cards around the middle node look: 'full' = the name and the fact line; 'compact' = the short name
 *  only, the fact line shows under the pointer and on the selected node (more than FULL_CARDS nodes, or a phone). */
export type CardMode = 'full' | 'compact'
export function cardModeFor(count: number, narrow = false): CardMode {
  return !narrow && count <= FULL_CARDS ? 'full' : 'compact'
}

/** How a graph of this many nodes is drawn: the more nodes, the shorter the names and the smaller the circles and
 *  cards (a phone always gets the small ones), so the rings stay near the size of the box. The middle node is
 *  always clearly the biggest. */
export interface Look {
  card: CardMode
  nameMax: number // the letters of a name on a card
  nameSize: number // px
  factSize: number
  dot: number // the circle of every node around the middle one (nodeSizeFor)
  middle: number // the middle node's picture (its circle and the soft ring around it)
  middleMax: number
  middleSize: number
}

export function lookFor(around: number, narrow = false): Look {
  const same = { card: cardModeFor(around, narrow), dot: nodeSizeFor(around, narrow) }
  if (narrow) return { ...same, nameMax: 12, nameSize: 10, factSize: 9, middle: 58, middleMax: 18, middleSize: 12 }
  if (around > 25) return { ...same, nameMax: 14, nameSize: 10, factSize: 9, middle: 66, middleMax: 30, middleSize: 12 }
  if (around > FULL_CARDS) return { ...same, nameMax: 16, nameSize: 11, factSize: 10, middle: 72, middleMax: 30, middleSize: 13 }
  if (around > 10) return { ...same, nameMax: 18, nameSize: 11, factSize: 10, middle: 72, middleMax: 34, middleSize: 13 }
  return { ...same, nameMax: 26, nameSize: 11, factSize: 10, middle: 84, middleMax: 34, middleSize: 13 }
}

const CARD_PAD: [number, number] = [5, 9] // inside a card: up / down, left / right
const nameLine = (size: number) => size + 5
const factLineHeight = (size: number) => size + 4

/** The texts of a node's label card: its name (cut) and its fact line; the middle node gets a second small line
 *  (its place or code, else its type) where there is room for it (not on a phone). */
export function cardOf(node: GraphNode, middle: boolean, look: Look, narrow = false): { name: string; facts: string[] } {
  const most = middle ? look.middleMax : look.nameMax
  const fact = cutName(factLine(node), most + 4)
  const facts = fact ? [fact] : []
  if (middle && !narrow) {
    const second = cutName(node.sub || node.type_name || TYPE_NAMES[node.type], most + 6)
    if (second && second !== fact) facts.push(second)
  }
  return { name: cutName(node.label, most), facts }
}

// in a label { } start and end a style, so a name must not hold them
const plain = (text: string) => text.replace(/\{/g, '(').replace(/\}/g, ')')

/** About how wide a text is drawn, in px (the canvas is not asked: the option stays pure). Capitals and digits are
 *  wide, thin letters and spaces narrow; a little too wide rather than too narrow. */
export function textWidth(text: string, size: number, bold = false): number {
  let em = 0
  for (const letter of text) em += /[A-Z0-9MWmw@&%…]/.test(letter) ? 0.7 : /[\s.,:;'|!iljtf·()-]/.test(letter) ? 0.34 : 0.58
  return Math.ceil(em * size * (bold ? 1.05 : 1))
}

const pictures = new Map<string, string>()

/** A node's picture: a circle in this colour with its type's icon in white; ring = the middle node's soft ring
 *  around it. An SVG as an ECharts image symbol ('image://…'), drawn sharp at any size. */
export function nodePicture(type: GraphNode['type'], colour: string, ring = false): string {
  const key = `${type}|${colour}|${ring}`
  let picture = pictures.get(key)
  if (!picture) {
    const disc = ring ? 25 : 32 // the circle's radius on the picture's 64 x 64 box
    const side = disc * 1.12 // the icon's box
    const scale = side / ICON_BOX
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="192" height="192" viewBox="0 0 64 64">' +
      (ring ? `<circle cx="32" cy="32" r="32" fill="${colour}" fill-opacity="0.2"/>` : '') +
      `<circle cx="32" cy="32" r="${disc}" fill="${colour}"/>` +
      `<path transform="translate(${32 - side / 2} ${32 - side / 2}) scale(${scale})" fill="#fff" d="${TYPE_ICONS[type]}"/></svg>`
    picture = `image://data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
    pictures.set(key, picture)
  }
  return picture
}

/** A link's width in 2D: thin (1 to 2.4 px by its amount). */
export function thinWidth(edge: GraphEdge, biggest: number): number {
  return MONEY_EDGES.has(edge.type) ? Math.round((1 + (edgeWidth(edge, biggest) - 1) * 0.2) * 10) / 10 : 1
}

/** Whether every link shows its pill: up to PILL_LINKS links (a phone: 6). With more, only the links of the node
 *  under the pointer and of the selected node do. */
export function everyPill(links: number, narrow = false): boolean {
  return links <= (narrow ? 6 : PILL_LINKS)
}

const EDGE_ROOM = 12 // px kept free at the box's sides and bottom

/** Where the series sits in the box so that the layout's px are the screen's px (ECharts fits the box around the
 *  nodes' centres into this frame): in the middle of the room under the legend, smaller only when the rings with
 *  their cards do not fit. */
export function frameOf(blocks: Block[], spots: Spots, box: { width: number; height: number }, top: number):
  { left: number; top: number; width?: number; height?: number; right?: number; bottom?: number; scale: number } {
  const at = blocks.map((block) => spots.get(block.id)).filter((spot): spot is [number, number] => Boolean(spot))
  if (at.length === 0) return { left: EDGE_ROOM, right: EDGE_ROOM, top, bottom: EDGE_ROOM, scale: 1 }
  let [minX, maxX] = [Math.min(...at.map((spot) => spot[0])), Math.max(...at.map((spot) => spot[0]))]
  let [minY, maxY] = [Math.min(...at.map((spot) => spot[1])), Math.max(...at.map((spot) => spot[1]))]
  // one node, or all in a line: ECharts makes such a box 2 wide
  if (maxX === minX) { minX -= 1; maxX += 1 }
  if (maxY === minY) { minY -= 1; maxY += 1 }
  const all = extent(blocks, spots)
  // what sticks out of the centres' box (half a circle, the cards): it is not scaled
  const out = [Math.max(0, minX - all[0]), Math.max(0, minY - all[1]), Math.max(0, all[2] - maxX), Math.max(0, all[3] - maxY)]
  const room = { width: box.width - 2 * EDGE_ROOM, height: box.height - top - EDGE_ROOM }
  const scale = Math.max(0.15, Math.min(1, (room.width - out[0] - out[2]) / (maxX - minX), (room.height - out[1] - out[3]) / (maxY - minY)))
  const [width, height] = [(maxX - minX) * scale, (maxY - minY) * scale]
  const round = (n: number) => Math.round(n * 10) / 10
  return {
    left: round(EDGE_ROOM + Math.max(0, (room.width - width - out[0] - out[2]) / 2) + out[0]),
    top: round(top + Math.max(0, (room.height - height - out[1] - out[3]) / 2) + out[1]),
    width: round(width), height: round(height), scale,
  }
}

export function buildGraphOption(data: GraphData, colours: Colours, view: GraphView = {}): EChartsCoreOption {
  const byId = new Map(data.nodes.map((node) => [node.id, node]))
  const biggestEdge = Math.max(0, ...data.edges.filter((e) => MONEY_EDGES.has(e.type)).map((e) => Math.abs(e.amount ?? 0)))
  const present = TYPE_ORDER.filter((type) => data.nodes.some((node) => node.type === type))
  const narrow = Boolean(view.narrow)
  const centre = view.center && byId.has(view.center) ? view.center : null
  const look = lookFor(data.nodes.length - (centre ? 1 : 0), narrow)
  const brand = colours.series[0]
  const shadow = colours.dark ? 'rgba(0,0,0,.55)' : 'rgba(17,16,16,.16)'
  const pills = everyPill(data.edges.length, narrow)

  // every node as it is drawn: its circle (the same size for all but the middle one), its card's text and the room
  // both take. A compact card (many nodes, a phone) has the short name only; under the pointer and when selected
  // it shows the whole card (`fullCards`) - the amount is in the tooltip too
  const cards = new Map<string, string>()
  const fullCards = new Map<string, string>()
  const blocks: Block[] = data.nodes.map((node) => {
    const middle = node.id === centre
    const card = cardOf(node, middle, look, narrow)
    const facts = middle || look.card === 'full' ? card.facts : []
    const nameSize = middle ? look.middleSize : look.nameSize
    const name = `{${middle ? 'big' : 'name'}|${plain(card.name)}}`
    cards.set(node.id, [name, ...facts.map((fact) => `{fact|${plain(fact)}}`)].join('\n'))
    fullCards.set(node.id, [name, ...card.facts.map((fact) => `{fact|${plain(fact)}}`)].join('\n'))
    const dot = middle ? look.middle : look.dot
    return {
      id: node.id, dot,
      width: Math.max(textWidth(card.name, nameSize, true), ...facts.map((fact) => textWidth(fact, look.factSize))) + 2 * CARD_PAD[1] + 2,
      height: nameLine(nameSize) + facts.length * factLineHeight(look.factSize) + 2 * CARD_PAD[0] + 2,
    }
  })
  const dots = new Map(blocks.map((block) => [block.id, block.dot]))
  const box = { width: view.width || (narrow ? 360 : 900), height: view.height || (narrow ? 440 : 580) }
  const top = narrow ? 56 : 40 // the legend's room
  // (with few links every pill shows: the rings keep the pills off the middle node's card)
  const spots = ringLayout(blocks, centre,
    { width: box.width - 2 * EDGE_ROOM, height: box.height - top - EDGE_ROOM }, view.positions, pills)
  const { scale, ...frame } = frameOf(blocks, spots, box, top)
  // the last way out, when even the rings drawn smaller do not fit (a phone, 40 nodes and more, zoomed out): cards
  // that would lie on each other are left out - the middle node, the selected one and the bigger amounts keep
  // theirs, the others show it under the pointer (and when zoomed in far enough)
  const first = (node: GraphNode) => (node.id === centre ? 2 : node.id === view.selected ? 1 : 0)
  const order = [...data.nodes].sort((a, b) => first(b) - first(a) || (b.amount ?? 0) - (a.amount ?? 0)).map((node) => node.id)
  const blockOf = new Map(blocks.map((block) => [block.id, block]))
  const hidden = hiddenCards(order.map((id) => blockOf.get(id) as Block), spots, scale * (view.zoom || 1))
  const fullCard = (p: { data?: { id?: string } }) => fullCards.get(p.data?.id ?? '') ?? ''

  return {
    animationDurationUpdate: 300,
    textStyle: { fontFamily: FONT },
    tooltip: {
      trigger: 'item', confine: true, enterable: false,
      backgroundColor: colours.surface, borderColor: colours.line, textStyle: { color: colours.ink, fontSize: 12, fontFamily: FONT },
      formatter: (params: { dataType?: string; data?: { id?: string; edgeId?: string } }) => {
        if (params.dataType === 'edge') {
          const edge = data.edges.find((e) => e.id === params.data?.edgeId)
          return edge ? edgeTip(edge, byId) : ''
        }
        const node = byId.get(params.data?.id ?? '')
        return node ? nodeTip(node) : ''
      },
    },
    legend: [{
      data: present.map((type) => TYPE_NAMES[type]), top: 0, left: 'center', icon: 'circle', itemWidth: 10, itemHeight: 10,
      itemGap: narrow ? 8 : 14, textStyle: { color: colours.muted, fontSize: narrow ? 10 : 11, fontFamily: FONT },
      inactiveColor: colours.line,
      // the zoom buttons sit at the top right of the box: the legend keeps off them
      ...(view.width ? { width: Math.max(140, view.width - 110) } : {}),
    }],
    series: [{
      // layout 'none': the nodes sit where graphLayout put them (x / y). roamTrigger 'global': drag and zoom
      // anywhere on the chart; GraphChart keeps the wheel off the empty space
      type: 'graph', layout: 'none', roam: true, roamTrigger: 'global', draggable: true, ...frame,
      scaleLimit: { min: 0.25, max: 5 },
      ...(view.zoom ? { zoom: view.zoom } : {}), ...(view.at ? { center: view.at } : {}),
      selectedMode: 'single',
      categories: TYPE_ORDER.map((type) => ({ name: TYPE_NAMES[type], itemStyle: { color: TYPE_COLOURS[type] } })),
      symbolKeepAspect: true,
      itemStyle: { shadowBlur: 5, shadowOffsetY: 2, shadowColor: shadow },
      // the label card under each node: the name in bold, the fact line small and quiet
      label: {
        show: true, position: 'bottom', distance: CARD_GAP, align: 'center',
        formatter: (p: { data?: { id?: string } }) => cards.get(p.data?.id ?? '') ?? '',
        backgroundColor: colours.surface, borderColor: colours.line, borderWidth: 1, borderRadius: 8,
        padding: [CARD_PAD[0], CARD_PAD[1]], shadowBlur: 8, shadowOffsetY: 2, shadowColor: shadow,
        rich: {
          name: { fontFamily: FONT, fontSize: look.nameSize, fontWeight: 600, color: colours.head, lineHeight: nameLine(look.nameSize), align: 'center' },
          big: { fontFamily: FONT, fontSize: look.middleSize, fontWeight: 700, color: colours.head, lineHeight: nameLine(look.middleSize), align: 'center' },
          fact: { fontFamily: FONT, fontSize: look.factSize, color: colours.muted, lineHeight: factLineHeight(look.factSize), align: 'center' },
        },
      },
      // (no labelLayout / hideOverlap here: in ECharts 6 it also takes the links' pills and puts them in the wrong
      // place. The cards that would lie on each other are left out by hiddenCards instead.)
      // the pill on a link: its plain words, turned along the line
      edgeLabel: {
        show: pills, position: 'insideMiddle', formatter: (p: { data?: { kind?: string } }) => linkWords(p.data?.kind ?? ''),
        fontFamily: FONT, fontSize: narrow ? 9 : 10, color: colours.muted, opacity: 1, // (else it fades with its line)
        backgroundColor: colours.surface, borderColor: colours.line, borderWidth: 1, borderRadius: 9, padding: [3, 7],
      },
      // under the pointer: the whole card (with a compact card: its fact line too)
      emphasis: { focus: 'adjacency', label: { show: true, formatter: fullCard }, edgeLabel: { show: true, color: colours.ink }, lineStyle: { opacity: 0.95 } },
      // the selected node: a glow in the app's blue around its circle and a blue edge on its whole card
      select: { itemStyle: { shadowBlur: 16, shadowOffsetY: 0, shadowColor: brand }, label: { show: true, formatter: fullCard, borderColor: brand, borderWidth: 2 } },
      // thin, straight and grey; on dark a bit more strength to be seen
      lineStyle: { color: colours.muted, opacity: colours.dark ? 0.6 : 0.42, curveness: 0, width: 1 },
      edgeSymbol: ['none', 'none'],
      data: data.nodes.map((node) => {
        const middle = node.id === centre
        const at = spots.get(node.id) ?? [0, 0]
        return {
          id: node.id, name: node.label, value: node.amount ?? 0, category: TYPE_ORDER.indexOf(node.type),
          symbol: nodePicture(node.type, middle ? brand : TYPE_COLOURS[node.type], middle), symbolSize: dots.get(node.id),
          x: at[0], y: at[1],
          // the node in the middle: the app's blue with a soft glow, and a bigger card
          ...(middle ? {
            itemStyle: { shadowBlur: 14, shadowOffsetY: 3, shadowColor: fade(brand, colours.dark ? 0.5 : 0.35) },
            label: { padding: [CARD_PAD[0] + 1, CARD_PAD[1] + 2], borderRadius: 10 },
          } : hidden.has(node.id) ? { label: { show: false } } : {}),
        }
      }),
      links: data.edges.map((edge) => ({
        source: edge.source, target: edge.target, edgeId: edge.id, kind: edge.type, value: Math.abs(edge.amount ?? 0),
        lineStyle: { width: thinWidth(edge, biggestEdge), ...(MONEY_EDGES.has(edge.type) ? {} : { type: 'dashed' }) },
        // many links: the selected node's ones still carry their pill
        ...(!pills && view.selected && (edge.source === view.selected || edge.target === view.selected) ? { label: { show: true } } : {}),
      })),
    }],
  }
}
