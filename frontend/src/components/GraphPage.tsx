// Knowledge graph (every user): search a customer, product, category, sales person or state, and see who buys
// what, from whom and where - drawn from the NOP data live and read-only (0 AI tokens). Picking a search hit draws
// its neighbourhood; a click shows a node's details in the side panel (under the graph on a phone). A double-click
// (or Open) goes into a node: the graph shows only that node in the middle with its own links, and the path above
// the graph (Rekha › Northern Tech › ...) grows. A click on the node in the middle, or on a name in the path, goes
// back. Similar customers adds the customers who buy the same products. The FY filter draws the same node again for
// that year. ⛶ Full screen shows only the graph (and its details) on the whole screen - Esc comes back; Hide details
// gives the graph the panel's room too (kept in this browser). ECharts loads lazily. "3D view" draws the same graph
// in 3D (charts/Graph3D.tsx: its code is fetched only then; kept in this browser; a browser without WebGL stays 2D).
// The look is Tailwind CSS + shadcn/ui (Button, Card, Input, Skeleton, Spinner), in the theme's colour names only
// (bg-card, text-foreground, primary = the blue brand, destructive = red for errors), so the page follows the light
// and the dark theme on its own. Each top-level block has the
// class "ui-scope" (the small reset of src/tailwind.css); the page returns no wrapper of its own, because
// .content > * gets a transform animation in app.css and full screen (position: fixed) must not sit inside it.
import { ArrowRight, ChevronRight, CircleAlert, Info, Network, Search } from 'lucide-react'
import { type KeyboardEvent, type ReactNode, Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'
import { AuthError, api, problemText } from '../api'
import { Link } from '../router'
import type { GraphNode, GraphNodeReply, GraphPeriod, GraphSimilarReply } from '../types'
import { Loading } from './common'
import {
  EMPTY_GRAPH, type GraphData, MAX_NODES, NEIGHBOURS, TYPE_COLOURS, TYPE_NAMES, forgetGraphPage, graphReplies,
  groupTitle, loadGraphPage, mergeGraph, saveGraphPage, splitId,
} from './graphData'

const GraphChart = lazy(() => import('../charts/GraphChart'))
const Graph3D = lazy(() => import('../charts/Graph3D'))

// the small type styles the page repeats
const LABEL = 'block h-4 text-[11px] leading-4 font-semibold tracking-[.06em] uppercase text-muted-foreground'
const HINT = 'flex min-h-4 items-center gap-1.5 text-[11.5px] leading-4 text-muted-foreground'
const CAPTION = 'text-[10.5px] font-semibold tracking-[.07em] uppercase text-muted-foreground'
const ERROR_BOX = 'flex items-start gap-2 rounded-lg border border-destructive/20 bg-danger-soft px-3.5 py-2.5 text-[13px] leading-snug text-destructive'
// a name in the panel that selects that node: a button that reads like a link
const NODE_LINK = 'min-w-0 cursor-pointer rounded-sm text-left font-medium text-foreground [overflow-wrap:anywhere] '
  + 'hover:text-primary hover:underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/40'
// app.css styles every <select> outside a cascade layer: the properties it sets are marked important (!)
const SELECT = 'h-9 w-full cursor-pointer rounded-md! border! border-input! bg-card! px-2.5! py-0! text-[13px]! '
  + 'text-foreground! shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-primary! '
  + 'focus-visible:ring-3 focus-visible:ring-primary/15'

export const FY_CHOICES: [string, string][] = [['', 'All data'], ['2526', 'FY 2025-26'], ['2627', 'FY 2026-27']]
const SEARCH_WAIT = 250 // ms after the last key before the search runs
const PANEL_LINKS = 10 // links listed per group in the side panel

function tooMany(left: number, label: string): string {
  return left > 0 ? `The graph shows at most ${MAX_NODES} nodes: ${left} more links of ${label} were left out. Reset or search to start again.` : ''
}

/** The coloured dot of a node type (the same colours as the graph). */
function Dot({ node, className }: { node: GraphNode; className?: string }) {
  return <span aria-hidden="true" className={cn('inline-block size-2.5 flex-none rounded-full', className)}
    style={{ background: TYPE_COLOURS[node.type] }} />
}

function TypeDot({ node }: { node: GraphNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted px-2.5 py-1 text-[10.5px] leading-none font-semibold tracking-[.07em] uppercase text-muted-foreground">
      <Dot node={node} className="size-2" />
      {node.type_name || TYPE_NAMES[node.type]}
    </span>
  )
}

/** One number of the selected node (Net sales, Quantity, ...). */
function Fact({ label, wide, big, children }: { label: string; wide?: boolean; big?: boolean; children: ReactNode }) {
  return (
    <div className={cn('min-w-0 rounded-lg border border-border bg-muted px-3 py-2', wide && 'col-span-2')}>
      <dt className={CAPTION}>{label}</dt>
      <dd className={cn('m-0 mt-0.5 font-semibold text-heading tabular-nums [overflow-wrap:anywhere]',
        big ? 'text-[15px]' : 'text-[13px]')}>{children}</dd>
    </div>
  )
}

/** A heading and a list of linked nodes in the panel (the links of one type, or the similar customers). */
function LinkGroup({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <section className="mt-4">
      <div className={cn(CAPTION, 'mb-1.5')}>{title}</div>
      {children}
    </section>
  )
}

const GROUP_LIST = 'overflow-hidden rounded-lg border border-border divide-y divide-border'
const GROUP_ROW = 'flex items-baseline justify-between gap-2.5 px-3 py-1.5 text-[12.5px] transition-colors hover:bg-muted max-[700px]:flex-wrap'
const GROUP_VALUE = 'whitespace-nowrap text-xs text-muted-foreground tabular-nums'

export const SEARCH_HINT = 'Type a name, or a word like customer, product, category, sales person or state'
export const MAX_HITS = 50 // "Show more" stops here (the server never gives more)
const MORE_STEP = 10 // hits one "Show more" adds
export const AT_MAX = `Showing ${MAX_HITS} - type more to narrow`

/** The search box with its suggestions (arrow keys + Enter, or a click). No AI call while typing: a type word
 * ("customers") lists the top ones by net sales, a small spelling mistake gives "Did you mean" hits, and only when
 * nothing is found does "Ask the Assistant instead" offer the chat - it fills the question box, it does not send it.
 * The note says how many there are in all ("Top 10 of 4,982 customers ..."); "Show more" at the bottom of the
 * list (a click, or the arrow keys + Enter) adds 10 more of the same search, up to 50. */
function GraphSearch({ onPick }: { onPick: (node: GraphNode) => void }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<GraphNode[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0) // hits.length = the "Show more" row
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState('') // the reply's own line: 'Top 10 of 4,982 customers by net sales ...'
  const [missing, setMissing] = useState('') // the text nothing was found for (it offers "Ask the Assistant instead")
  const [total, setTotal] = useState<number | null>(null) // how many in all (null: close spellings, no pages)
  const [moreBusy, setMoreBusy] = useState(false)
  const [searched, setSearched] = useState('') // the text the hits shown are for
  const turn = useRef(0) // a new text: a "Show more" still running is ignored

  useEffect(() => {
    const text = q.trim()
    turn.current += 1
    setMoreBusy(false)
    setMissing('')
    if (text.length < 2) {
      setHits([])
      setTotal(null)
      setError('')
      setNote('')
      return
    }
    let gone = false
    const timer = window.setTimeout(() => {
      setBusy(true)
      api.graphSearch(text)
        .then((reply) => {
          if (gone) return
          setSearched(text)
          setHits(reply.results)
          setTotal(reply.fuzzy || reply.total === undefined ? null : reply.total)
          setActive(0)
          setNote(reply.results.length ? reply.note ?? '' : '')
          setMissing(reply.results.length ? '' : text)
          setError(reply.results.length ? '' : `Nothing found for "${text}".`)
        })
        .catch((err) => { if (!gone && !(err instanceof AuthError)) setError(problemText(err, 'The search did not work - please try again.')) })
        .finally(() => { if (!gone) setBusy(false) })
    }, SEARCH_WAIT)
    return () => { gone = true; window.clearTimeout(timer) }
  }, [q])

  // more to show: only for the hits of the text in the box now (not old hits while a new search waits)
  const left = total !== null && searched === q.trim() && total > hits.length
  const canMore = left && hits.length < MAX_HITS
  const atMax = left && hits.length >= MAX_HITS

  const showMore = () => {
    if (!canMore || moreBusy) return
    const mine = turn.current
    const text = searched
    const from = hits.length
    setMoreBusy(true)
    api.graphSearch(text, '', { offset: from, limit: Math.min(MORE_STEP, MAX_HITS - from) })
      .then((reply) => {
        if (mine !== turn.current) return
        setHits((old) => {
          const seen = new Set(old.map((n) => n.id))
          return [...old, ...reply.results.filter((n) => !seen.has(n.id))]
        })
        // nothing came: there is nothing more to show
        setTotal(reply.results.length && reply.total !== undefined ? reply.total : from)
        setActive((i) => (i >= from ? from : i)) // from the "Show more" row: on the first new hit
        if (reply.note) setNote(reply.note)
        setError('')
      })
      .catch((err) => { if (mine === turn.current && !(err instanceof AuthError)) setError(problemText(err, 'More could not be read - please try again.')) })
      .finally(() => { if (mine === turn.current) setMoreBusy(false) })
  }

  const pick = (node: GraphNode) => {
    setOpen(false)
    setQ('')
    setHits([])
    onPick(node)
  }

  const rows = hits.length + (canMore ? 1 : 0) // the hits, and the "Show more" row
  const keys = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' && rows) {
      event.preventDefault()
      setOpen(true)
      setActive((i) => (i + 1) % rows)
    } else if (event.key === 'ArrowUp' && rows) {
      event.preventDefault()
      setActive((i) => (i - 1 + rows) % rows)
    } else if (event.key === 'Enter' && hits.length) {
      event.preventDefault()
      if (canMore && active === hits.length) showMore()
      else pick(hits[Math.min(active, hits.length - 1)])
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  const showing = open && hits.length > 0
  const activeId = canMore && active === hits.length ? 'graph-hit-more' : `graph-hit-${Math.min(active, hits.length - 1)}`

  // the arrow keys keep the chosen row in sight (the list scrolls when it is long)
  useEffect(() => {
    if (showing) document.getElementById(activeId)?.scrollIntoView?.({ block: 'nearest' })
  }, [showing, activeId])
  return (
    <div className="flex min-w-0 flex-[1_1_340px] flex-col gap-1.5">
      <label className={LABEL} htmlFor="graph-q">Search</label>
      <div className="relative">
        <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input id="graph-q" type="text" role="combobox" autoComplete="off" value={q} maxLength={100}
          className="h-9 pl-9!"
          placeholder="A customer, product, category, sales person or state - e.g. Aurora"
          aria-autocomplete="list" aria-expanded={showing} aria-controls="graph-hits"
          aria-activedescendant={showing ? activeId : undefined}
          onChange={(event) => { setQ(event.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onKeyDown={keys} />
        {showing && (
          <div className="absolute inset-x-0 top-full z-30 mt-1.5 max-h-[360px] overflow-y-auto rounded-xl border border-border bg-popover p-1 text-popover-foreground shadow-[0_16px_36px_-12px_rgba(17,16,16,.22)] dark:shadow-[0_16px_36px_-12px_rgba(0,0,0,.6)]">
            {note && <div className={cn(CAPTION, 'px-2.5 pt-1.5 pb-1 normal-case tracking-normal text-[11px]')}>{note}</div>}
            <ul id="graph-hits" role="listbox" aria-label="Matching nodes">
              {hits.map((node, i) => (
                <li key={node.id} id={`graph-hit-${i}`} role="option" aria-selected={i === active}
                  className="flex cursor-pointer flex-wrap items-center gap-x-2.5 gap-y-0.5 rounded-lg px-2.5 py-2 transition-colors hover:bg-accent aria-selected:bg-accent"
                  onMouseDown={(event) => event.preventDefault()} onClick={() => pick(node)}>
                  <Dot node={node} />
                  {node.fuzzy && (
                    <span className="flex-none rounded-full border border-primary/20 bg-primary-soft px-1.5 py-px text-[10px] leading-4 font-semibold tracking-[.04em] text-primary uppercase">
                      Did you mean
                    </span>
                  )}
                  <span className="min-w-0 text-[13px] font-semibold text-foreground [overflow-wrap:anywhere]">{node.label}</span>
                  <span className="ml-auto text-[11.5px] text-muted-foreground [overflow-wrap:anywhere]">
                    {node.type_name}{node.sub ? ` · ${node.sub}` : ''}{node.amount_text ? ` · ${node.amount_text}` : ''}
                  </span>
                </li>
              ))}
              {canMore && (
                // a row of the list (not a button): the focus stays in the box, so the arrow keys reach it and
                // a click does not close the list (onMouseDown keeps the focus, as the hits do)
                <li id="graph-hit-more" role="option" aria-selected={active === hits.length} aria-busy={moreBusy || undefined}
                  className="flex cursor-pointer items-center justify-center gap-1.5 rounded-lg px-2.5 py-2 text-[12.5px] font-semibold text-primary transition-colors hover:bg-accent aria-selected:bg-accent"
                  onMouseDown={(event) => event.preventDefault()} onClick={showMore}>
                  {moreBusy && <Spinner className="size-3" />}
                  {moreBusy ? 'Loading more…' : 'Show more'}
                </li>
              )}
            </ul>
            {atMax && <div className={cn(CAPTION, 'px-2.5 pt-1 pb-1.5 text-center normal-case tracking-normal text-[11px]')}>{AT_MAX}</div>}
          </div>
        )}
      </div>
      <div className="flex min-h-4 flex-wrap items-center gap-x-2.5 gap-y-1">
        <div className={HINT} role="status">
          {busy && <Spinner className="size-3" />}
          {busy ? 'Searching…' : error || (q.trim() ? '' : SEARCH_HINT)}
        </div>
        {missing && !busy && (
          // only when nothing is found: the chat opens with the text in its box - nothing is sent (no AI tokens)
          // until the user presses Ask. app.css colours every <a> outside a cascade layer: hence the (!)
          <Link to={`/new?q=${encodeURIComponent(missing)}`}
            className={cn(buttonVariants({ variant: 'link', size: 'xs' }),
              'h-4 px-0 text-[11.5px] font-semibold text-primary! hover:text-primary!')}>
            Ask the Assistant instead
            <ArrowRight aria-hidden="true" className="size-3" />
          </Link>
        )}
      </div>
    </div>
  )
}

interface PanelProps {
  selected: GraphNode | null
  detail: GraphNodeReply | null
  loading: boolean
  error: string
  inMiddle: boolean // this node is the one in the middle of the graph now
  similar: GraphSimilarReply | null
  similarBusy: boolean
  onOpen: () => void
  onSimilar: () => void
  onSelect: (node: GraphNode) => void
}

/** The details of the selected node: its totals, its top links, and what can be done with it. */
function Panel({ selected, detail, loading, error, inMiddle, similar, similarBusy, onOpen, onSimilar, onSelect }: PanelProps) {
  if (!selected) {
    return (
      <div className="rounded-lg border border-dashed border-input px-4 py-6 text-center text-[12.5px] leading-relaxed text-muted-foreground">
        Click a node on the graph to see its details here.
      </div>
    )
  }
  const node = detail && detail.node.id === selected.id ? detail.node : selected
  const byId = new Map((detail?.neighbours ?? []).map((n) => [n.id, n]))
  const other = (source: string, target: string) => byId.get(source === node.id ? target : source)
  return (
    <>
      <TypeDot node={node} />
      <div className="mt-2.5 text-base leading-snug font-semibold text-heading [overflow-wrap:anywhere]">{node.label}</div>
      {node.sub && <div className="mt-0.5 text-[12.5px] text-muted-foreground [overflow-wrap:anywhere]">{node.sub}</div>}
      {detail && detail.node.id === node.id ? (
        <>
          <dl className="m-0 mt-3.5 grid grid-cols-2 gap-2">
            {node.amount_text && <Fact label="Net sales" wide big>INR {node.amount_text}</Fact>}
            {node.quantity_text !== undefined && node.type !== 'document' && <Fact label="Quantity">{node.quantity_text}</Fact>}
            {node.invoices_text !== undefined && <Fact label="Invoices">{node.invoices_text}</Fact>}
            {node.data_from && <Fact label="Lines dated" wide>{node.data_from} to {node.data_to}</Fact>}
          </dl>
          <div className="mt-2 text-xs leading-relaxed text-muted-foreground">{detail.period.text}</div>
          {node.text && (
            <blockquote className="mx-0 mt-3 mb-0 rounded-r-lg border-l-[3px] bg-muted px-3 py-2 text-xs leading-relaxed text-body"
              style={{ borderLeftColor: TYPE_COLOURS.document }}>
              {node.text}…
            </blockquote>
          )}
          {detail.notes.map((note) => <div key={note} className="mt-2 text-xs leading-relaxed text-muted-foreground">{note}</div>)}
          <div className="mt-3.5 flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" onClick={onOpen} disabled={inMiddle}>
              {inMiddle ? 'In the middle' : 'Open'}
            </Button>
            {node.type === 'customer' && (
              <Button type="button" variant="outline" size="sm" onClick={onSimilar} aria-busy={similarBusy || undefined}
                className={cn(similarBusy && 'pointer-events-none opacity-80')}>
                {similarBusy && <Spinner />}Similar customers
              </Button>
            )}
            {node.ask && (
              // app.css colours every <a> outside a cascade layer: the link's own colours are marked important (!)
              <Link to={`/new?q=${encodeURIComponent(node.ask)}`}
                className={cn(buttonVariants({ size: 'sm' }), 'text-primary-foreground! hover:text-primary-foreground!')}>
                Ask about this
              </Link>
            )}
          </div>
          {similar && similar.customer.id === node.id && (
            <LinkGroup title={<>Buys like this customer ({similar.products} products in {similar.period.label})</>}>
              {similar.similar.length ? (
                <ul className={GROUP_LIST}>
                  {similar.similar.map((friend) => (
                    <li key={friend.id} className={GROUP_ROW}>
                      <button type="button" className={NODE_LINK} onClick={() => onSelect(friend)}>{friend.label}</button>
                      <span className={GROUP_VALUE}>{friend.shared_products} shared · {friend.score_text}</span>
                    </li>
                  ))}
                </ul>
              ) : <div className="text-[12.5px] text-muted-foreground">No other customer bought the same products in this period.</div>}
            </LinkGroup>
          )}
          {detail.groups.filter((group) => group.shown > 0).map((group) => (
            <LinkGroup key={`${group.edge}-${group.type}`} title={groupTitle(group.edge, group.type, group.shown, group.total)}>
              <ul className={GROUP_LIST}>
                {detail.edges.filter((edge) => edge.type === group.edge && other(edge.source, edge.target)?.type === group.type)
                  .slice(0, PANEL_LINKS).map((edge) => {
                    const neighbour = other(edge.source, edge.target)
                    if (!neighbour) return null
                    const value = edge.amount_text ?? (edge.model ? `model ${edge.model}` : edge.mentions ? `${edge.mentions} mentions` : '')
                    return (
                      <li key={edge.id} className={GROUP_ROW}>
                        <button type="button" className={NODE_LINK} onClick={() => onSelect(neighbour)}>{neighbour.label}</button>
                        <span className={GROUP_VALUE}>{value}</span>
                      </li>
                    )
                  })}
              </ul>
            </LinkGroup>
          ))}
        </>
      ) : error ? (
        <div className={cn(ERROR_BOX, 'mt-3 text-[12.5px]')}>
          <CircleAlert aria-hidden="true" className="mt-px size-4 flex-none" />{error}
        </div>
      ) : loading ? (
        <div className="mt-3.5">
          <Loading>Reading its links…</Loading>
          <div className="mt-2 grid grid-cols-2 gap-2" aria-hidden="true">
            <Skeleton className="col-span-2 h-12" />
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </div>
        </div>
      ) : null}
    </>
  )
}

/** A node's own neighbourhood as the whole graph (the node first). */
function neighbourhood(reply: GraphNodeReply): { graph: GraphData; left: number } {
  return mergeGraph(EMPTY_GRAPH, [reply.node, ...reply.neighbours], reply.edges)
}

// after going back, the rest of a double-click (a 2nd click, the dblclick) must not go back or in again
const BACK_QUIET = 500 // ms
const PANEL_KEY = 'mi.graphPanel' // 'hidden' when the user hid the details panel
const FULL_ROOM = 150 // px of the screen above and under the graph in full screen (path, title, note)
const VIEW_KEY = 'mi.graphView' // '3d' when the user picked the 3D view
export const NO_WEBGL = '3D needs WebGL, which this browser does not have.'

/** Did the user hide the details panel in this browser? (No storage: shown.) */
function readPanelHidden(): boolean {
  try {
    return window.localStorage.getItem(PANEL_KEY) === 'hidden'
  } catch {
    return false
  }
}

/** Does this browser have WebGL? (Checked before the 3D code is fetched; the test context is let go at once.) */
export function hasWebGL(): boolean {
  try {
    const canvas = document.createElement('canvas')
    const gl = (canvas.getContext('webgl2') ?? canvas.getContext('webgl')) as WebGLRenderingContext | null
    if (!gl) return false
    gl.getExtension?.('WEBGL_lose_context')?.loseContext()
    return true
  } catch {
    return false
  }
}

/** The view to start in: 3D when the user picked it in this browser and WebGL is there. */
function readView(): { three: boolean; missing: boolean } {
  let wanted = false
  try {
    wanted = window.localStorage.getItem(VIEW_KEY) === '3d'
  } catch {
    // no storage: 2D
  }
  const three = wanted && hasWebGL()
  return { three, missing: wanted && !three }
}

export default function GraphPage() {
  // back on the page: the graph as the user left it (graphData.loadGraphPage), else an empty page
  const [saved] = useState(loadGraphPage)
  const [fy, setFy] = useState(saved?.fy ?? '')
  const [graph, setGraph] = useState<GraphData>(saved?.graph ?? EMPTY_GRAPH)
  const [trail, setTrail] = useState<GraphNode[]>(saved?.trail ?? []) // the nodes gone into: the last is in the middle
  const [selected, setSelected] = useState<GraphNode | null>(saved?.selected ?? null)
  const [detail, setDetail] = useState<GraphNodeReply | null>(saved?.detail ?? null)
  const [detailError, setDetailError] = useState('')
  const [loading, setLoading] = useState(false)
  const [similar, setSimilar] = useState<GraphSimilarReply | null>(saved?.similar ?? null)
  const [similarBusy, setSimilarBusy] = useState(false)
  const [period, setPeriod] = useState<GraphPeriod | null>(saved?.period ?? null)
  const [message, setMessage] = useState(saved?.message ?? '')
  const [error, setError] = useState('')
  const replies = useRef(graphReplies) // `${fy}|${id}` -> the API's reply (kept while the app is open)
  const turn = useRef(0) // only the latest request may change the page
  const drawn = useRef<GraphData>(saved?.graph ?? EMPTY_GRAPH) // the graph as it is now (Similar customers merge into it)
  const selectedId = useRef<string | null>(saved?.selected?.id ?? null)
  const wentBack = useRef({ at: 0, from: '' })
  const layout = useRef<HTMLDivElement>(null)
  const [panelHidden, setPanelHidden] = useState(readPanelHidden)
  const [full, setFull] = useState(false)
  const [screenHeight, setScreenHeight] = useState(() => window.innerHeight)
  const [startView] = useState(readView)
  const [three, setThree] = useState(startView.three) // the 3D view is shown
  const [noWebGL, setNoWebGL] = useState(startView.missing)

  const center = trail.length ? trail[trail.length - 1].id : null

  // keep the page as it is now, so leaving it and coming back (or a refresh) shows the same graph
  useEffect(() => {
    saveGraphPage(graph.nodes.length ? { fy, graph, trail, selected, detail, similar, period, message } : null)
  }, [fy, graph, trail, selected, detail, similar, period, message])

  const draw = useCallback((next: GraphData) => {
    drawn.current = next
    setGraph(next)
  }, [])

  const pickNode = useCallback((node: GraphNode | null) => {
    selectedId.current = node?.id ?? null
    setSelected(node)
  }, [])

  const fetchNode = useCallback((id: string, year: string) => {
    const cached = replies.current.get(`${year}|${id}`)
    if (cached) return Promise.resolve(cached)
    const [type, key] = splitId(id)
    return api.graphNode(type, key, year, NEIGHBOURS).then((reply) => {
      replies.current.set(`${year}|${id}`, reply)
      return reply
    })
  }, [])

  const failed = useCallback((err: unknown, fallback: string) => {
    if (!(err instanceof AuthError)) setError(problemText(err, fallback))
  }, [])

  /** The last node of the path in the middle, with only its own links (the graph before it goes away). */
  const goTo = useCallback((path: GraphNode[], year: string, fallback: string) => {
    const node = path[path.length - 1]
    const mine = ++turn.current
    setError('')
    setLoading(true)
    fetchNode(node.id, year)
      .then((reply) => {
        if (mine !== turn.current) return
        const { graph: next, left } = neighbourhood(reply)
        draw(next)
        setTrail([...path.slice(0, -1), reply.node])
        setSimilar(null)
        setMessage(tooMany(left, reply.node.label))
        setPeriod(reply.period)
        pickNode(reply.node)
        setDetail(reply)
        setDetailError('')
      })
      .catch((err) => { if (mine === turn.current) failed(err, fallback) })
      .finally(() => { if (mine === turn.current) setLoading(false) })
  }, [fetchNode, draw, pickNode, failed])

  /** A search hit: a new path that starts with it. */
  const start = useCallback((node: GraphNode) => {
    pickNode(node)
    setDetail(null)
    goTo([node], fy, 'The graph could not be drawn - please try again.')
  }, [fy, goTo, pickNode])

  /** A double-click or Open: into that node (a node already on the path: back to it). */
  const open = useCallback((id: string) => {
    if (id === center) return
    if (Date.now() - wentBack.current.at < BACK_QUIET && id === wentBack.current.from) return
    const node = graph.nodes.find((n) => n.id === id)
    if (!node) return
    const at = trail.findIndex((n) => n.id === id)
    goTo(at >= 0 ? trail.slice(0, at + 1) : [...trail, node], fy, `The links of ${node.label} could not be read.`)
  }, [center, graph, trail, fy, goTo])

  /** Back to the node at this place on the path (a click on the middle node: the one before it). */
  const back = useCallback((index: number) => {
    if (index < 0 || index >= trail.length - 1) return
    wentBack.current = { at: Date.now(), from: center ?? '' }
    goTo(trail.slice(0, index + 1), fy, 'The graph could not be drawn again.')
  }, [trail, center, fy, goTo])

  /** A click in the panel: the node's details (the graph stays as it is). */
  const select = useCallback((node: GraphNode) => {
    pickNode(node)
    setDetailError('')
    if (detail?.node.id === node.id) return
    setDetail(null)
    setLoading(true)
    fetchNode(node.id, fy)
      .then((reply) => { if (selectedId.current === node.id) setDetail(reply) })
      .catch((err) => {
        if (selectedId.current === node.id && !(err instanceof AuthError)) setDetailError(problemText(err, 'Its details could not be read.'))
      })
      .finally(() => setLoading(false))
  }, [detail, fetchNode, fy, pickNode])

  /** A click on the graph: the node in the middle goes back one step, any other node shows its details. */
  const clickNode = useCallback((id: string) => {
    if (id === center && trail.length > 1) {
      if (Date.now() - wentBack.current.at >= BACK_QUIET) back(trail.length - 2)
      return
    }
    const node = graph.nodes.find((n) => n.id === id)
    if (node) select(node)
  }, [center, trail, graph, back, select])

  const showSimilar = useCallback(() => {
    if (!selected || selected.type !== 'customer') return
    setSimilarBusy(true)
    api.graphSimilar(selected.key, fy)
      .then((reply) => {
        setSimilar(reply)
        const merged = mergeGraph(drawn.current, [reply.customer, ...reply.similar], reply.edges)
        draw(merged.graph)
        setMessage(tooMany(merged.left, reply.customer.label))
      })
      .catch((err) => failed(err, 'The similar customers could not be found.'))
      .finally(() => setSimilarBusy(false))
  }, [selected, fy, failed, draw])

  /** Another FY: the node in the middle drawn again with that year's numbers (the path stays). */
  const changeFy = (year: string) => {
    setFy(year)
    setSimilar(null)
    if (trail.length) goTo(trail, year, 'The graph could not be drawn for that year.')
  }

  const togglePanel = () => {
    const next = !panelHidden
    setPanelHidden(next)
    try {
      if (next) window.localStorage.setItem(PANEL_KEY, 'hidden')
      else window.localStorage.removeItem(PANEL_KEY)
    } catch {
      // storage blocked: hidden until the page is loaded again
    }
  }

  const rememberView = (is3d: boolean) => {
    try {
      if (is3d) window.localStorage.setItem(VIEW_KEY, '3d')
      else window.localStorage.removeItem(VIEW_KEY)
    } catch {
      // storage blocked: this view until the page is loaded again
    }
  }

  const toggleView = () => {
    if (!three && !hasWebGL()) {
      setNoWebGL(true)
      return
    }
    setNoWebGL(false)
    setThree(!three)
    rememberView(!three)
  }

  // the 3D view could not start WebGL after all: back to 2D, with the message
  const lost3d = useCallback(() => {
    setThree(false)
    setNoWebGL(true)
    rememberView(false)
  }, [])

  /** Full screen: the graph part on the whole page, and the browser's own full screen when it allows it. */
  const enterFull = () => {
    setFull(true)
    setScreenHeight(window.innerHeight)
    layout.current?.requestFullscreen?.()?.catch(() => {}) // not allowed: the page-wide view is enough
  }

  const exitFull = useCallback(() => {
    setFull(false)
    if (document.fullscreenElement) document.exitFullscreen?.()?.catch(() => {})
  }, [])

  // in full screen: Esc comes back (the browser's own Esc too), and the graph follows the screen's height
  useEffect(() => {
    if (!full) return
    const keys = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') exitFull() }
    const changed = () => {
      if (!document.fullscreenElement) setFull(false)
      setScreenHeight(window.innerHeight)
    }
    const resized = () => setScreenHeight(window.innerHeight)
    window.addEventListener('keydown', keys)
    document.addEventListener('fullscreenchange', changed)
    window.addEventListener('resize', resized)
    return () => {
      window.removeEventListener('keydown', keys)
      document.removeEventListener('fullscreenchange', changed)
      window.removeEventListener('resize', resized)
    }
  }, [full, exitFull])

  // leaving the page in full screen: the browser leaves it too
  useEffect(() => () => {
    if (document.fullscreenElement) document.exitFullscreen?.()?.catch(() => {})
  }, [])

  const reset = () => {
    exitFull()
    turn.current += 1
    forgetGraphPage()
    draw(EMPTY_GRAPH)
    setTrail([])
    pickNode(null)
    setDetail(null)
    setSimilar(null)
    setPeriod(null)
    setMessage('')
    setError('')
    setLoading(false)
  }

  const centerNode = graph.nodes.find((node) => node.id === center)
  const title = centerNode ? `${centerNode.label} · ${period?.label ?? ''}` : ''

  return (
    <>
      {/* the search card is above the graph (z-20), so its suggestion list opens over the graph */}
      <Card className="ui-scope relative z-20 flex flex-wrap items-start gap-x-4 gap-y-3 px-5 py-4 max-[760px]:px-3.5">
        <GraphSearch onPick={start} />
        <div className="flex flex-[0_0_180px] flex-col gap-1.5 max-[700px]:flex-[1_1_140px]">
          <label className={LABEL} htmlFor="graph-fy">Period</label>
          <select id="graph-fy" className={SELECT} value={fy} onChange={(event) => changeFy(event.target.value)}>
            {FY_CHOICES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <div className={HINT}>{period ? `${period.from} to ${period.to}` : 'Never after today'}</div>
        </div>
        {/* pt-[22px]: the height of a label and its gap, so the button lines up with the fields */}
        <div className="flex-none pt-[22px]">
          <Button type="button" variant="outline" className="h-9" onClick={reset} disabled={!graph.nodes.length && !error}>
            Reset
          </Button>
        </div>
      </Card>

      {error && (
        <div className={cn('ui-scope', ERROR_BOX)} role="alert">
          <CircleAlert aria-hidden="true" className="mt-px size-4 flex-none" />{error}
        </div>
      )}
      {message && (
        <div className="ui-scope flex items-start gap-2 rounded-lg border border-border bg-card px-3.5 py-2.5 text-[12.5px] leading-snug text-muted-foreground" role="status">
          <Info aria-hidden="true" className="mt-px size-4 flex-none text-info" />{message}
        </div>
      )}

      {graph.nodes.length ? (
        <div ref={layout}
          className={cn('graph-layout ui-scope grid items-start gap-3.5',
            panelHidden ? 'no-panel grid-cols-[minmax(0,1fr)]'
              : 'grid-cols-[minmax(0,1fr)_340px] max-[1100px]:grid-cols-[minmax(0,1fr)]',
            full && 'full fixed inset-0 z-[1000] m-0 overflow-auto bg-background px-4 py-3.5')}
          role={full ? 'dialog' : undefined} aria-label={full ? 'Knowledge graph, full screen' : undefined}>
          <div className="min-w-0">
            <nav className="graph-path mb-2.5 flex flex-wrap items-center gap-x-2.5 gap-y-1.5" aria-label="Path">
              {trail.length > 1 && (
                <Button type="button" variant="outline" size="sm" onClick={() => back(trail.length - 2)}>↩ Back</Button>
              )}
              <ol className="flex min-w-0 flex-wrap items-center gap-1 text-[13px]">
                {trail.map((node, i) => (
                  <li key={node.id} className="flex min-w-0 items-center gap-1">
                    {i > 0 && <ChevronRight aria-hidden="true" className="size-3.5 flex-none text-faint" />}
                    {i < trail.length - 1
                      ? (
                        <button type="button" onClick={() => back(i)}
                          className="cursor-pointer rounded-md px-1.5 py-0.5 text-left font-medium text-muted-foreground underline-offset-2 transition-colors [overflow-wrap:anywhere] outline-none hover:bg-accent hover:text-primary hover:underline focus-visible:ring-3 focus-visible:ring-ring/40">
                          {node.label}
                        </button>
                      )
                      : (
                        <b aria-current="step" className="rounded-md bg-primary-soft px-2 py-0.5 font-semibold text-primary [overflow-wrap:anywhere]">
                          {node.label}
                        </b>
                      )}
                  </li>
                ))}
              </ol>
              <span className="ml-auto flex flex-wrap gap-2">
                <Button type="button" variant="outline" size="sm" onClick={toggleView} aria-pressed={three}
                  title={three ? 'Back to the flat graph' : 'The same graph in 3D: drag to turn it'}>
                  {three ? '2D view' : '3D view'}
                </Button>
                <Button type="button" variant={full ? 'default' : 'outline'} size="sm" onClick={full ? exitFull : enterFull}>
                  {full ? 'Exit full screen' : '⛶ Full screen'}
                </Button>
                <Button type="button" variant="outline" size="sm" onClick={togglePanel} aria-expanded={!panelHidden}>
                  {panelHidden ? '« Show details' : 'Hide details »'}
                </Button>
              </span>
              <span className="basis-full text-xs text-muted-foreground">
                Double-click a dot to go into it{trail.length > 1 ? ' · click the dot in the middle to go back' : ''}
              </span>
              {noWebGL && (
                <span className="flex basis-full items-center gap-1.5 text-xs text-muted-foreground" role="status">
                  <Info aria-hidden="true" className="size-3.5 flex-none text-info" />{NO_WEBGL}
                </span>
              )}
            </nav>
            <Suspense fallback={<Loading>{three ? 'Loading the 3D view…' : 'Drawing the graph…'}</Loading>}>
              {three ? (
                <Graph3D data={graph} center={center} selected={selected?.id ?? null} title={title}
                  subtitle={period?.text ?? ''} onSelect={clickNode} onOpen={open} onNoWebGL={lost3d}
                  height={full ? Math.max(360, screenHeight - FULL_ROOM) : undefined} />
              ) : (
                <GraphChart data={graph} center={center} selected={selected?.id ?? null} title={title}
                  subtitle={period?.text ?? ''} onSelect={clickNode} onOpen={open}
                  height={full ? Math.max(360, screenHeight - FULL_ROOM) : undefined} />
              )}
            </Suspense>
          </div>
          {!panelHidden && (
            <aside aria-label="Node details"
              className={cn('min-w-0 overflow-y-auto rounded-xl border border-border bg-card p-4 text-card-foreground shadow-[0_10px_26px_-24px_rgba(17,16,16,.35)] dark:shadow-none',
                full ? 'max-h-[calc(100vh-28px)]' : 'max-h-[700px] max-[1100px]:max-h-none')}>
              <Panel selected={selected} detail={detail} loading={loading} error={detailError}
                inMiddle={selected?.id === center} similar={similar} similarBusy={similarBusy}
                onOpen={() => selected && open(selected.id)} onSimilar={showSimilar} onSelect={select} />
            </aside>
          )}
        </div>
      ) : loading ? (
        <Loading>Reading the links…</Loading>
      ) : !error ? (
        <Card className="ui-scope flex items-start gap-4 px-6 py-7 max-[700px]:flex-col max-[760px]:px-4">
          <span aria-hidden="true" className="flex size-11 flex-none items-center justify-center rounded-xl bg-primary-soft text-primary">
            <Network className="size-5.5" />
          </span>
          <div className="min-w-0">
            <div className="text-base font-semibold text-heading">Search for a starting point</div>
            <div className="mt-1.5 max-w-[720px] text-[13px] leading-relaxed text-muted-foreground">
              Type at least 2 letters of a customer, product, category, sales person or state above and pick one: its
              links are drawn from the NOP data - who buys what, from whom and where, and which company PDFs cover a
              product category. Double-click a dot to go into it, and click the dot in the middle to go back. The
              numbers are net sales (credit notes subtracted), never after today. This page only reads the data and
              never asks the AI.
            </div>
          </div>
        </Card>
      ) : null}
    </>
  )
}
