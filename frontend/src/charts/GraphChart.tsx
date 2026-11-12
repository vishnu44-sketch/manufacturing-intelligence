// The Knowledge graph drawing (loaded lazily with ECharts, like the answer charts): the force-layout graph,
// Download PNG, a click selects a node (on the node in the middle: goes back), a double-click goes into a node.
// With the same node in the middle, nodes already drawn keep their place when new ones come in (their positions are
// read from the chart before the next option); another node in the middle is laid out afresh around it.
// The mouse wheel zooms only on the dots (the box around them, NEAR px wider): on the empty space around them the
// page scrolls as usual - in full screen too (05-Nov: "even in full screen only near the graph"). Fit puts the graph
// back in the middle.
// The card around it is Tailwind CSS + shadcn/ui (Card, Button, Spinner), like the rest of the Knowledge graph page.
// The colours follow the theme (light / dark): when it changes the option is built again, the dots stay where they are.
import { Download, Maximize } from 'lucide-react'
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
import { buildGraphOption, describeGraph } from './graphOption'
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
    // a chart without a layout yet: the force layout places every node
  }
  return found
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

export default function GraphChart({
  data, center, selected, title, subtitle = '', onSelect, onOpen, height,
}: GraphChartProps) {
  const theme = useThemeName()
  const colours = useMemo(() => readColours(theme), [theme])
  const chart = useRef<EChartsType | null>(null)
  const handlers = useRef({ onSelect, onOpen })
  handlers.current = { onSelect, onOpen }
  const lastCenter = useRef(center)
  const [width, setWidth] = useState(0)
  const narrow = width > 0 && width < NARROW
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [fits, setFits] = useState(0) // each Fit: a new option (zoom 1, the dots in the middle where they are now)
  const box = useRef<HTMLDivElement>(null)

  // the selected node is drawn by ECharts itself (selectedMode), so a click never lays the graph out again
  const option = useMemo(() => {
    const same = lastCenter.current === center
    lastCenter.current = center
    return buildGraphOption(data, colours, { center, narrow, positions: same ? positions(chart.current) : new Map() })
  }, [data, colours, center, narrow, fits])

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
    made?.on('dblclick', (params: unknown) => {
      const id = nodeId(params)
      if (id) handlers.current.onOpen(id)
    })
  }, [])
  const onClick = useCallback((params: unknown) => {
    const id = nodeId(params)
    if (id) handlers.current.onSelect(id)
  }, [])

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
          <Button type="button" variant="outline" size="sm" onClick={() => setFits((n) => n + 1)}
            title="Back in the middle at normal zoom">
            <Maximize aria-hidden="true" />Fit
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={save} aria-busy={saving || undefined}
            className={cn(saving && 'pointer-events-none opacity-80')}>
            {saving ? <Spinner /> : <Download aria-hidden="true" />}Download PNG
          </Button>
        </span>
      </div>
      <div ref={box} className="w-full min-w-0 rounded-lg border border-border bg-muted" role="img"
        aria-label={describeGraph(data, centerLabel)}>
        <EChart option={option} height={height ?? (narrow ? 440 : 580)} onReady={onReady} onWidth={setWidth} onClick={onClick} />
      </div>
      {saveError && (
        <div className="mt-2 rounded-lg border border-destructive/20 bg-danger-soft px-3 py-2 text-[12.5px] text-destructive" role="alert">{saveError}</div>
      )}
      <div className="mt-2 text-xs leading-relaxed text-muted-foreground">
        {selectedLabel ? `Selected: ${selectedLabel}. ` : ''}Click a node for its details; double-click it (or use Open) to
        go into it; click the node in the middle to go back. Drag to move; scroll on the graph or pinch to zoom; Fit puts it back in the middle.
      </div>
    </Card>
  )
}
