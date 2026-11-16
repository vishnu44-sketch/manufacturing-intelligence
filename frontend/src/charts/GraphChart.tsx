// The Knowledge graph drawing (loaded lazily with ECharts, like the answer charts): the nodes on rings around the
// node in the middle (graphOption.ts / graphLayout.ts: circles with an icon, label cards, pills on the links),
// Download PNG, a click selects a node (on the node in the middle: goes back), a double-click goes into a node.
// With the same node in the middle, nodes already drawn keep their place when new ones come in (their positions are
// read from the chart before the next option); another node in the middle is laid out afresh around it.
// The mouse wheel zooms only on the dots (the box around them, NEAR px wider): on the empty space around them the
// page scrolls as usual - in full screen too (05-Nov: "even in full screen only near the graph"). The three small
// buttons at the top right of the box zoom in, zoom out and reset the view; Fit (in the header) resets it too.
// The card around it is Tailwind CSS + shadcn/ui (Card, Button, Spinner), like the rest of the Knowledge graph page.
// The colours follow the theme (light / dark): when it changes the option is built again, the dots stay where they
// are and the view (the zoom, what is in the middle) stays as the user left it. The same when a node is selected in
// a graph with many links (its links then show their pills), when the box changes its size, and when a zoom makes
// room for cards that were left out (or takes it away).
import { Download, Maximize, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'
import type { GraphData } from '../components/graphData'
import { NARROW, downloadPng, pngName, readColours } from './chartOption'
import EChart from './EChart'
import type { EChartsType } from './echarts'
import './echartsGraph'
import { buildGraphOption, describeGraph, everyPill } from './graphOption'
import useThemeName from './useThemeName'
import './chart.css'

export interface GraphChartProps {
  data: GraphData
  center: string | null
  selected: string | null
  title: string // above the graph and in the PNG
  subtitle?: string // the period's dates, in the PNG
  onSelect: (id: string) => void
  onOpen: (id: string) => void
  height?: number // full screen: the graph as tall as the screen
}

const NEAR = 40 // px around the dots where the mouse wheel still zooms
export const ZOOM_STEP = 1.25 // one press of + (and of -: 1 / 1.25)
export const ROAM_WAIT = 160 // ms after the last zoom before the cards are looked at again

/** The node id of an ECharts mouse event ('' for an edge or the background). */
function nodeId(params: unknown): string {
  const p = params as { dataType?: string; data?: { id?: unknown } } | null
  return p && p.dataType === 'node' && typeof p.data?.id === 'string' ? p.data.id : ''
}

/** Where each node is drawn now (ECharts' own layout); empty when it cannot be read. */
function positions(chart: EChartsType | null): Map<string, [number, number]> {
  const found = new Map<string, [number, number]>()
  try {
    const model = (chart as unknown as { getModel?: () => any })?.getModel?.()
    const series = model?.getSeriesByIndex?.(0)
    const data = series?.getData?.()
    data?.each?.((index: number) => {
      const at = data.getItemLayout(index)
      if (Array.isArray(at) && Number.isFinite(at[0]) && Number.isFinite(at[1])) found.set(data.getId(index), [at[0], at[1]])
    })
  } catch {
    // a chart without a layout yet: every node gets a new place
  }
  return found
}

/** The zoom and the middle of the view as the user left them (ECharts keeps both on the series); {} when the
 *  graph was not zoomed or moved, or the chart cannot say. */
function viewOf(chart: EChartsType | null): { zoom?: number; at?: number[] } {
  try {
    const series = (chart?.getOption?.() as { series?: { zoom?: unknown; center?: unknown }[] } | undefined)?.series?.[0]
    const zoom = Number(series?.zoom)
    const at = series?.center
    return {
      ...(Number.isFinite(zoom) && zoom > 0 && zoom !== 1 ? { zoom } : {}),
      ...(Array.isArray(at) && at.length === 2 && at.every((n) => Number.isFinite(Number(n))) ? { at: at.map(Number) } : {}),
    }
  } catch {
    return {}
  }
}

/** Whether the option leaves a node's card out for want of room. */
function leavesCardsOut(option: unknown): boolean {
  const nodes = (option as { series?: { data?: { label?: { show?: boolean } }[] }[] })?.series?.[0]?.data
  return Array.isArray(nodes) && nodes.some((node) => node.label?.show === false)
}

interface Box { left: number; top: number; right: number; bottom: number }

/** The box around the dots on the screen now, in px of the chart (after any zoom and pan); null when unknown. */
function dotsBox(chart: EChartsType): Box | null {
  let box: Box | null = null
  try {
    for (const at of positions(chart).values()) {
      const [x, y] = chart.convertToPixel({ seriesIndex: 0 }, at) as number[]
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue
      box = box ? { left: Math.min(box.left, x), top: Math.min(box.top, y), right: Math.max(box.right, x), bottom: Math.max(box.bottom, y) }
        : { left: x, top: y, right: x, bottom: y }
    }
  } catch {
    return null
  }
  return box
}

// what the chart shows now: the next option keeps the dots' places and, for the same graph, the view
interface Shown { data: GraphData; center: string | null; fits: number; sized: boolean; narrow: boolean; zoom: number; cardsOut: boolean }

export default function GraphChart({
  data, center, selected, title, subtitle = '', onSelect, onOpen, height,
}: GraphChartProps) {
  const theme = useThemeName()
  const colours = useMemo(() => readColours(theme), [theme])
  const chart = useRef<EChartsType | null>(null)
  const handlers = useRef({ onSelect, onOpen })
  handlers.current = { onSelect, onOpen }
  const [width, setWidth] = useState(0)
  const narrow = width > 0 && width < NARROW
  const tall = height ?? (narrow ? 440 : 580)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [fits, setFits] = useState(0) // each Fit / reset: a new option (zoom 1, the dots in the middle where they are now)
  const [zooms, setZooms] = useState(0) // a zoom that changes which cards have room: a new option, the view kept
  const box = useRef<HTMLDivElement>(null)
  const shown = useRef<Shown | null>(null) // set once an option is given to the chart
  const roamTimer = useRef<number | undefined>(undefined)

  // with many links only the selected node's links carry their pills: there a selection makes a new option. With
  // few links every pill shows and the selected node is drawn by ECharts itself (selectedMode), so a click never
  // draws the graph again
  const pillsOf = everyPill(data.edges.length, narrow) ? null : selected

  const option = useMemo(() => {
    const last = shown.current
    // the same node in the middle: the dots stay where they are (not when the box's width is first known, or a
    // phone's width comes or goes: the rings are made for the box)
    const sameMiddle = last !== null && last.center === center && last.sized === width > 0 && last.narrow === narrow
    // the same graph drawn again (the theme, a selection, the box's size, a zoom): the view stays as the user left
    // it; new nodes, another node in the middle and Fit start at normal zoom, in the middle
    const sameView = sameMiddle && last.data === data && last.fits === fits
    return buildGraphOption(data, colours, {
      center, narrow, width, height: tall, selected: pillsOf,
      positions: sameMiddle ? positions(chart.current) : new Map(),
      ...(sameView ? viewOf(chart.current) : {}),
    })
  }, [data, colours, center, narrow, width, tall, fits, zooms, pillsOf])

  useEffect(() => {
    const zoom = Number((option as { series?: { zoom?: unknown }[] }).series?.[0]?.zoom)
    shown.current = { data, center, fits, sized: width > 0, narrow, zoom: Number.isFinite(zoom) && zoom > 0 ? zoom : 1, cardsOut: leavesCardsOut(option) }
  }, [option]) // eslint-disable-line react-hooks/exhaustive-deps -- the values this option was built from

  // the panel or a search can select a node too: show it selected on the graph (again after each new option)
  useEffect(() => {
    const index = data.nodes.findIndex((node) => node.id === selected)
    if (chart.current && index >= 0) chart.current.dispatchAction({ type: 'select', seriesIndex: 0, dataIndex: index })
  }, [selected, data, option])

  // a wheel away from the dots never reaches ECharts (it listens inside this box), so the page scrolls instead
  // of the graph zooming out. Nothing is prevented here: the browser scrolls as usual.
  useEffect(() => {
    const outer = box.current
    if (!outer) return
    const wheel = (event: Event) => {
      const made = chart.current
      const dots = made && dotsBox(made)
      if (!made || !dots) return // where the dots are is not known: ECharts zooms, as before
      const rect = (made.getDom?.() ?? outer).getBoundingClientRect()
      const { clientX, clientY } = event as MouseEvent
      const x = clientX - rect.left
      const y = clientY - rect.top
      const near = x >= dots.left - NEAR && x <= dots.right + NEAR && y >= dots.top - NEAR && y <= dots.bottom + NEAR
      if (!near) event.stopPropagation()
    }
    const how = { capture: true, passive: true }
    outer.addEventListener('wheel', wheel, how)
    outer.addEventListener('mousewheel', wheel, how) // older browsers
    return () => {
      outer.removeEventListener('wheel', wheel, how)
      outer.removeEventListener('mousewheel', wheel, how)
    }
  }, [])

  const onReady = useCallback((made: EChartsType | null) => {
    chart.current = made
    window.clearTimeout(roamTimer.current)
    made?.on('dblclick', (params: unknown) => {
      const id = nodeId(params)
      if (id) handlers.current.onOpen(id)
    })
    // after a zoom (the wheel, a pinch, the buttons): zoomed in, cards left out for want of room may fit now;
    // zoomed out, cards may lie on each other. Only then the option is built again, a moment after the last zoom
    made?.on('graphroam', () => {
      window.clearTimeout(roamTimer.current)
      roamTimer.current = window.setTimeout(() => {
        const last = shown.current
        if (!last || !chart.current) return
        const change = (viewOf(chart.current).zoom ?? 1) / last.zoom
        if (change < 0.96 || (change > 1.04 && last.cardsOut)) setZooms((n) => n + 1)
      }, ROAM_WAIT)
    })
  }, [])
  useEffect(() => () => window.clearTimeout(roamTimer.current), [])

  const onClick = useCallback((params: unknown) => {
    const id = nodeId(params)
    if (id) handlers.current.onSelect(id)
  }, [])

  // + and -: ECharts' own zoom (what the wheel does), around the middle of the box
  const zoomBy = (factor: number) => {
    const made = chart.current
    if (!made) return
    const size = box.current?.getBoundingClientRect()
    made.dispatchAction({
      type: 'graphRoam', seriesIndex: 0, zoom: factor,
      originX: (made.getWidth?.() || size?.width || 0) / 2, originY: (made.getHeight?.() || size?.height || 0) / 2,
    })
  }
  const fit = () => setFits((n) => n + 1)

  const save = () => {
    if (!chart.current) return
    setSaving(true)
    setSaveError('')
    downloadPng(chart.current, pngName(title || 'knowledge_graph'), title, subtitle, colours)
      .catch(() => setSaveError('The PNG could not be made in this browser.'))
      .finally(() => setSaving(false))
  }

  const centerLabel = data.nodes.find((node) => node.id === center)?.label ?? 'the search'
  const selectedLabel = data.nodes.find((node) => node.id === selected)?.label
  return (
    <Card className="px-4 pt-3 pb-3 max-[700px]:px-2.5">
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-0 text-[13.5px] font-semibold text-heading [overflow-wrap:anywhere]">{title}</div>
        <span className="ml-auto flex items-center gap-1.5 max-[700px]:ml-0">
          <Button type="button" variant="outline" size="sm" onClick={fit} title="Back in the middle at normal zoom">
            <Maximize aria-hidden="true" />Fit
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={save} aria-busy={saving || undefined}
            className={cn(saving && 'pointer-events-none opacity-80')}>
            {saving ? <Spinner /> : <Download aria-hidden="true" />}Download PNG
          </Button>
        </span>
      </div>
      {/* the drawing box: a soft, very light background (the app's --surface-2); the zoom buttons sit on it, outside
          the picture (role="img" hides what is inside it from screen readers) */}
      <div className="relative w-full min-w-0 rounded-lg border border-border bg-muted">
        <div ref={box} className="w-full min-w-0" role="img" aria-label={describeGraph(data, centerLabel)}>
          <EChart option={option} height={tall} onReady={onReady} onWidth={setWidth} onClick={onClick} />
        </div>
        <div className="absolute top-2 right-2 z-10 flex flex-col gap-1">
          <Button type="button" variant="outline" size="icon-sm" aria-label="Zoom in" title="Zoom in" onClick={() => zoomBy(ZOOM_STEP)}>
            <ZoomIn aria-hidden="true" />
          </Button>
          <Button type="button" variant="outline" size="icon-sm" aria-label="Zoom out" title="Zoom out" onClick={() => zoomBy(1 / ZOOM_STEP)}>
            <ZoomOut aria-hidden="true" />
          </Button>
          <Button type="button" variant="outline" size="icon-sm" aria-label="Reset the view" title="Back in the middle at normal zoom" onClick={fit}>
            <RotateCcw aria-hidden="true" />
          </Button>
        </div>
      </div>
      {saveError && (
        <div className="mt-2 rounded-lg border border-destructive/20 bg-danger-soft px-3 py-2 text-[12.5px] text-destructive" role="alert">{saveError}</div>
      )}
      <div className="mt-2 text-xs leading-relaxed text-muted-foreground">
        {selectedLabel ? `Selected: ${selectedLabel}. ` : ''}Click a node for its details; double-click it (or use Open) to
        go into it; click the node in the middle to go back. Drag to move; scroll on the graph, pinch or use the + and −
        buttons to zoom; Fit puts it back in the middle.
      </div>
    </Card>
  )
}
