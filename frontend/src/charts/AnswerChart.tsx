// The chart above an answer's rows table: drawn in the browser with Apache ECharts from the rows the app
// already has (0 AI tokens). The kind is the one the question asked for ("as a line chart"), else the one
// pickChart finds best for the rows (or no chart: then this renders nothing); there is no menu to change it.
// When the asked kind does not fit the rows, pickChart draws its best kind and a note says why. A catch-all
// group ("Not classified") that holds most of the total is hidden from the chart (never from the table) so
// the other groups can be compared; a button shows it again.
// Drawn with Tailwind + shadcn/ui (it shows only on the Ask page); chart.css is still loaded for the
// ECharts tooltip. The colours follow the theme (light / dark): when it changes the chart is drawn again.
import { useEffect, useMemo, useRef, useState } from 'react'
import { ChartColumnBig, Download, Table2 } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Segmented, SegmentedItem } from '../components/ui/segmented'
import type { Cell, Header } from '../types'
import { ANIMATION_MS, buildOption, catchAllText, chartSubtitle, cutText, describe, downloadPng, NARROW, pngName, readColours } from './chartOption'
import EChart from './EChart'
import type { EChartsType } from './echarts'
import { type ChartKind, pickChart } from './pickChart'
import useThemeName from './useThemeName'
import './chart.css'

export { describe }

export interface AnswerChartProps {
  headers: Header[]
  rows: Cell[][]
  title?: string // shown above the chart and in the PNG
  onShowTable?: () => void // the "Table" button (the table itself stays in AnswerCard)
  kind?: ChartKind | null // the kind the question asked for ("as a treemap"); null = pickChart's best kind
}

export default function AnswerChart({ headers, rows, title = '', onShowTable, kind = null }: AnswerChartProps) {
  const [hide, setHide] = useState<boolean | null>(null) // the catch-all group: null = hidden when it is over 70%
  const pick = useMemo(() => pickChart(headers, rows, kind, hide), [headers, rows, kind, hide])
  const theme = useThemeName()
  const colours = useMemo(() => readColours(theme), [theme])
  const [width, setWidth] = useState(0)
  const narrow = width > 0 && width < NARROW
  const built = useMemo(() => (pick ? buildOption(pick, colours, narrow, width) : null), [pick, colours, narrow, width])
  const chart = useRef<EChartsType | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const drawnAt = useRef(0) // when the chart last got a new option (it grows in for ANIMATION_MS)
  useEffect(() => { drawnAt.current = Date.now() }, [built])

  if (!pick || !built) return null
  const catchAll = pick.catchAll

  const save = () => {
    if (!chart.current) return
    setSaving(true)
    setSaveError('')
    const run = () => {
      if (!chart.current) { setSaving(false); return }
      downloadPng(chart.current, pngName(title || `${pick.amount} by ${pick.x}`), title, chartSubtitle(pick), colours)
        .catch(() => setSaveError('The PNG could not be made in this browser.'))
        .finally(() => setSaving(false))
    }
    // the PNG shows the finished chart: a chart still growing in is saved when it is done
    const animated = (built.option as { animation?: boolean }).animation === true
    const wait = animated ? drawnAt.current + ANIMATION_MS + 100 - Date.now() : 0
    if (wait > 0) window.setTimeout(run, wait)
    else run()
  }

  const note = 'mt-1.5 text-[12.5px] text-muted-foreground'
  const topNote = 'mb-1.5 text-[12.5px] text-muted-foreground'
  return (
    <div className="min-w-0 rounded-xl border border-border bg-card px-4 pt-3 pb-2.5 text-card-foreground shadow-[0_10px_26px_-24px_rgba(17,16,16,.35)] dark:shadow-none max-[700px]:px-2.5">
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-2">
        {title && <div className="min-w-0 text-[13.5px] font-semibold text-heading [overflow-wrap:anywhere]">{title}</div>}
        <span className="ml-auto flex flex-wrap items-center gap-1.5 max-[700px]:ml-0">
          {catchAll && (
            <Button type="button" variant="outline" size="sm" onClick={() => setHide(!catchAll.hidden)}>
              {catchAll.hidden ? 'Show' : 'Hide'} {cutText(catchAll.name, 24)}
            </Button>
          )}
          {onShowTable && (
            <Segmented aria-label="Show the answer as">
              <SegmentedItem pressed><ChartColumnBig aria-hidden="true" />Chart</SegmentedItem>
              <SegmentedItem pressed={false} onClick={onShowTable}><Table2 aria-hidden="true" />Table</SegmentedItem>
            </Segmented>
          )}
          <Button type="button" variant="outline" size="sm" onClick={save} disabled={saving}>
            <Download aria-hidden="true" className="size-3.5" />
            {saving ? 'Saving…' : 'Download PNG'}
          </Button>
        </span>
      </div>
      {pick.fallback && <div className={topNote} role="status">{pick.fallback}</div>}
      {catchAll?.hidden && (
        <div className={topNote}>
          {catchAllText(catchAll)} is hidden so the other categories can be compared -{' '}
          <button type="button" className="rounded-xs font-semibold text-primary underline underline-offset-2 hover:text-primary-hover focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
            onClick={() => setHide(false)}>Show it</button>
        </div>
      )}
      <div className="w-full min-w-0" role="img" aria-label={describe(pick)}>
        <EChart option={built.option} height={built.height} onReady={(made) => { chart.current = made }} onWidth={setWidth}
          onClick={built.onClick} />
      </div>
      {pick.note && <div className={note}>Showing the {pick.note} rows - all of them are in the table.</div>}
      {pick.seriesNote && <div className={note}>Showing the {pick.seriesNote} - all of them are in the table.</div>}
      {saveError && <div className="mt-1.5 text-[12.5px] text-destructive" role="alert">{saveError}</div>}
    </div>
  )
}
