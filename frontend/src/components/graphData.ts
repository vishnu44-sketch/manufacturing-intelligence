// The Knowledge graph's data on the page (pure: no React, no ECharts): the nodes and edges drawn so far, how a
// new node's neighbourhood is merged in (no duplicates, at most MAX_NODES nodes), and the names and colours of the
// node and edge types. The node type colours have no red or yellow, and are the same in the light and the dark
// theme: middle tones that read on a white box and on a dark one.
import type { GraphEdge, GraphNode, GraphNodeReply, GraphNodeType, GraphPeriod, GraphSimilarReply } from '../types'

export const MAX_NODES = 150 // more than this is hard to read: the rest is left out with a message
export const NEIGHBOURS = 25 // the top neighbours of each edge type the API sends

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export const EMPTY_GRAPH: GraphData = { nodes: [], edges: [] }

export const TYPE_ORDER: GraphNodeType[] = ['customer', 'product', 'category', 'sales_person', 'state', 'sale_type', 'document']

export const TYPE_COLOURS: Record<GraphNodeType, string> = {
  customer: '#2563EB', // blue
  product: '#16A34A', // green
  category: '#F97316', // orange
  sales_person: '#7C3AED', // purple
  state: '#0D9488', // teal
  sale_type: '#38BDF8', // light blue
  document: '#84CC16', // light green
}

export const TYPE_NAMES: Record<GraphNodeType, string> = {
  customer: 'Customer', product: 'Product', category: 'Category', sales_person: 'Sales person',
  state: 'State / country', sale_type: 'Sale type', document: 'Document',
}

const TYPE_PLURALS: Record<GraphNodeType, string> = {
  customer: 'customers', product: 'products', category: 'categories', sales_person: 'sales people',
  state: 'states / countries', sale_type: 'sale types', document: 'document pages',
}

export const EDGE_NAMES: Record<string, string> = {
  BOUGHT: 'Bought', IN_CATEGORY: 'In category', HANDLED_BY: 'Handled by', IN_STATE: 'In state / country',
  BUYS_AS: 'Buys as', COVERED_BY: 'Covered by', BUYS_LIKE: 'Buys like',
}

/** 'Bought · products (25 of 453)': the heading of one group of links in the side panel. */
export function groupTitle(edge: string, type: GraphNodeType, shown: number, total: number): string {
  const count = shown < total ? `top ${shown} of ${total}` : String(total)
  return `${EDGE_NAMES[edge] ?? edge} · ${TYPE_PLURALS[type]} (${count})`
}

/** 'customer:16' -> ['customer', '16']; 'category:Trochoid pumps' -> ['category', 'Trochoid pumps']. */
export function splitId(id: string): [GraphNodeType, string] {
  const at = id.indexOf(':')
  return [id.slice(0, at) as GraphNodeType, id.slice(at + 1)]
}

/** The graph with these nodes and edges added: a node already drawn keeps its place (its numbers are updated
 *  when the new copy has them), a new one is added while there is room (MAX_NODES), an edge only when both of
 *  its ends are drawn. left = how many new nodes did not fit. */
export function mergeGraph(graph: GraphData, nodes: GraphNode[], edges: GraphEdge[], most = MAX_NODES):
  { graph: GraphData; left: number } {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]))
  let left = 0
  for (const node of nodes) {
    const old = byId.get(node.id)
    if (old) {
      byId.set(node.id, node.amount === null && old.amount !== null ? { ...node, ...old } : { ...old, ...node })
    } else if (byId.size < most) {
      byId.set(node.id, node)
    } else {
      left += 1
    }
  }
  const seen = new Set(graph.edges.map((edge) => edge.id))
  const added = edges.filter((edge) => {
    if (seen.has(edge.id) || !byId.has(edge.source) || !byId.has(edge.target)) return false
    seen.add(edge.id)
    return true
  })
  return { graph: { nodes: [...byId.values()], edges: [...graph.edges, ...added] }, left }
}

// ---------- the page as the user left it (04-Nov, Vishnu: "if I move to another page it is gone") ----------
// Kept while the user moves around the app, and in this browser tab's sessionStorage so a page refresh keeps it
// too. Reset, sign-out and a lost sign-in forget it - another person signing in in the same tab never sees it.

export interface SavedGraphPage {
  fy: string
  graph: GraphData
  trail: GraphNode[] // the nodes gone into (double-click): the last one is in the middle
  selected: GraphNode | null
  detail: GraphNodeReply | null
  similar: GraphSimilarReply | null
  period: GraphPeriod | null
  message: string
}

const SAVE_KEY = 'mi.graphPage.v2' // v2: the path (a v1 page, saved before it, is not read)
let saved: SavedGraphPage | null | undefined // undefined = not read from sessionStorage yet
// the API's node replies (`${fy}|${id}`): coming back to the page does not ask for them again
export const graphReplies = new Map<string, GraphNodeReply>()

/** The page as the user left it, or null. */
export function loadGraphPage(): SavedGraphPage | null {
  if (saved === undefined) {
    try {
      const raw = window.sessionStorage.getItem(SAVE_KEY)
      saved = raw ? (JSON.parse(raw) as SavedGraphPage) : null
    } catch {
      saved = null // storage blocked or a broken value: start empty
    }
  }
  return saved
}

/** Keeps the page as it is now (null = nothing to keep). */
export function saveGraphPage(page: SavedGraphPage | null): void {
  saved = page
  try {
    if (page) window.sessionStorage.setItem(SAVE_KEY, JSON.stringify(page))
    else window.sessionStorage.removeItem(SAVE_KEY)
  } catch {
    // storage full or blocked: still kept in memory while the app is open
  }
}

/** Forgets the page and its cached replies (Reset, sign-out, a lost sign-in, tests). */
export function forgetGraphPage(): void {
  saveGraphPage(null)
  graphReplies.clear()
}
