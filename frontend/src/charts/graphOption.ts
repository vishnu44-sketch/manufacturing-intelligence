// The ECharts option of the Knowledge graph (pure: no React): a 'graph' series with a force layout. A node's
// colour is its type (with a legend), its size its net sales (a log scale, between MIN_SIZE and MAX_SIZE), an
// edge's width its amount. Only the biggest nodes, the centre and the selected one carry a label; the hovered one
// shows its label too. The tooltip gives the full name, the type and the amounts as the app writes them.
// Texts, the tooltip's box and the rings follow the theme (colours); the node type colours are the same in both.
import { EDGE_NAMES, type GraphData, TYPE_COLOURS, TYPE_NAMES, TYPE_ORDER } from '../components/graphData'
import type { GraphEdge, GraphNode } from '../types'
import { type Colours, FONT, cutText, escapeHtml } from './chartOption'
import type { EChartsCoreOption } from './echarts'

export const MIN_SIZE = 12
export const MAX_SIZE = 48
export const DOCUMENT_SIZE = 18
export const LABELLED = 12 // the biggest nodes that always show their name
export const MONEY_EDGES = new Set(['BOUGHT', 'HANDLED_BY', 'IN_STATE', 'BUYS_AS', 'IN_CATEGORY'])
export const LINK_OPACITY = 0.45 // a link's strength (2D and 3D)
export const LINK_OPACITY_DARK = 0.65

export interface GraphView {
  center?: string | null
  selected?: string | null
  narrow?: boolean
  positions?: Map<string, [number, number]> // where the nodes already drawn are (they stay there)
}

/** A node's size on a log scale between the smallest and the biggest amount drawn: a sale type of 1,780 crore and
 *  a product of 20 lakh are on one graph, so a straight scale would leave every product a dot. */
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

export function buildGraphOption(data: GraphData, colours: Colours, view: GraphView = {}): EChartsCoreOption {
  const byId = new Map(data.nodes.map((node) => [node.id, node]))
  const amounts = data.nodes.filter((n) => n.type !== 'document' && (n.amount ?? 0) > 0).map((n) => n.amount as number)
  const biggest = Math.max(0, ...amounts)
  const smallest = amounts.length ? Math.min(...amounts) : 1
  const biggestEdge = Math.max(0, ...data.edges.filter((e) => MONEY_EDGES.has(e.type)).map((e) => Math.abs(e.amount ?? 0)))
  const labelled = new Set([...data.nodes].sort((a, b) => (b.amount ?? 0) - (a.amount ?? 0)).slice(0, LABELLED).map((n) => n.id))
  if (view.center) labelled.add(view.center)
  if (view.selected) labelled.add(view.selected)
  const present = TYPE_ORDER.filter((type) => data.nodes.some((node) => node.type === type))
  const narrow = Boolean(view.narrow)

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
    }],
    series: [{
      // roamTrigger 'global': drag and zoom anywhere on the chart; GraphChart keeps the wheel off the empty space
      type: 'graph', layout: 'force', roam: true, roamTrigger: 'global', draggable: true, top: narrow ? 56 : 40, bottom: 10,
      selectedMode: 'single',
      categories: TYPE_ORDER.map((type) => ({ name: TYPE_NAMES[type], itemStyle: { color: TYPE_COLOURS[type] } })),
      force: { repulsion: narrow ? [80, 220] : [120, 420], edgeLength: narrow ? [40, 110] : [60, 180], gravity: 0.08, friction: 0.15 },
      label: { position: 'right', fontSize: narrow ? 10 : 11, color: colours.ink, formatter: (p: { name: string }) => cutText(p.name, narrow ? 18 : 28) },
      labelLayout: { hideOverlap: true },
      emphasis: { focus: 'adjacency', label: { show: true }, lineStyle: { opacity: 0.9 } },
      select: { itemStyle: { borderColor: colours.ink, borderWidth: 3 }, label: { show: true, fontWeight: 600 } },
      // on dark the thin links need a bit more strength to be seen
      lineStyle: { color: 'source', opacity: colours.dark ? LINK_OPACITY_DARK : LINK_OPACITY, curveness: 0.06 },
      edgeSymbol: ['none', 'arrow'], edgeSymbolSize: 5,
      data: data.nodes.map((node) => {
        const at = view.positions?.get(node.id)
        return {
          id: node.id, name: node.label, value: node.amount ?? 0, category: TYPE_ORDER.indexOf(node.type),
          symbol: node.type === 'document' ? 'roundRect' : 'circle', symbolSize: nodeSize(node, biggest, smallest),
          label: { show: labelled.has(node.id) },
          ...(at ? { x: at[0], y: at[1] } : {}),
          // the node in the middle: a white ring with a soft shadow; on dark a light ring with a glow
          ...(node.id === view.center ? { itemStyle: colours.dark
            ? { borderColor: colours.ink, borderWidth: 2, shadowBlur: 12, shadowColor: 'rgba(255,255,255,.35)' }
            : { borderColor: '#fff', borderWidth: 2, shadowBlur: 8, shadowColor: 'rgba(0,0,0,.25)' } } : {}),
        }
      }),
      links: data.edges.map((edge) => ({
        source: edge.source, target: edge.target, edgeId: edge.id, value: Math.abs(edge.amount ?? 0),
        lineStyle: {
          width: edgeWidth(edge, biggestEdge),
          ...(MONEY_EDGES.has(edge.type) ? {} : { type: 'dashed', color: edge.type === 'BUYS_LIKE' ? TYPE_COLOURS.customer : TYPE_COLOURS.document }),
        },
      })),
    }],
  }
}
