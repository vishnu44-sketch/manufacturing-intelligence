// A chart the AI made (POST /api/questions/<id>/chart): an ECharts option sent as plain JSON - data, never
// code. The server already checked it (portal/charts.py); here it is checked once more: only the allowed
// top-level keys are kept and the tooltip draws text only (no HTML). Drawn with the same ECharts box.
// Drawn with Tailwind + shadcn/ui like the answer chart (it shows only on the Ask page). The AI sends no colours
// for the texts, so the theme's are filled in (themed): on dark its labels and axes would be dark on dark.
import { useMemo, useRef, useState } from 'react'
import { Download } from 'lucide-react'
import { Button } from '../components/ui/button'
import { type Colours, downloadPng, FONT, NARROW, pngName, readColours } from './chartOption'
import EChart from './EChart'
import type { EChartsCoreOption, EChartsType } from './echarts'
import './echartsAi'
import useThemeName from './useThemeName'
import './chart.css'

// the same list as portal/charts.py ALLOWED_KEYS
export const ALLOWED_KEYS = ['series', 'xAxis', 'yAxis', 'title', 'legend', 'tooltip', 'grid', 'visualMap', 'dataset',
  'radar', 'polar', 'angleAxis', 'radiusAxis', 'color']

type Json = Record<string, unknown>

const isObject = (value: unknown): value is Json => Boolean(value) && typeof value === 'object' && !Array.isArray(value)

/** `own` over `defaults`, one level deep: what the AI set stays, the theme fills in the rest. */
function under(defaults: Json, own: unknown): Json {
  if (!isObject(own)) return defaults
  const merged: Json = { ...defaults, ...own }
  for (const key of Object.keys(defaults)) {
    if (isObject(defaults[key]) && isObject(own[key])) merged[key] = { ...(defaults[key] as Json), ...(own[key] as Json) }
  }
  return merged
}

/** One part of the option (an object, or a list of them) with the theme's colours under the AI's own. */
const each = (part: unknown, defaults: Json) => (Array.isArray(part) ? part.map((item) => under(defaults, item)) : under(defaults, part))

// series whose labels stand beside the shape, on the card: they get the theme's text colour. (A label inside
// a shape - a treemap, a sunburst - is left to ECharts, which picks one that reads on the shape's colour.)
const LABEL_BESIDE = new Set(['sankey', 'tree', 'graph', 'pie', 'funnel', 'radar'])

/** The theme's colours for the texts and lines the AI gave no colour: axes, legend, title, tooltip, labels. */
function themed(option: Json, colours: Colours): void {
  const text = { color: colours.ink }
  const soft = { color: colours.muted }
  const line = { lineStyle: { color: colours.line } }
  option.textStyle = { fontFamily: FONT, color: colours.ink }
  const axis = { axisLabel: soft, nameTextStyle: soft, axisLine: line, splitLine: line }
  for (const key of ['xAxis', 'yAxis', 'angleAxis', 'radiusAxis']) if (key in option) option[key] = each(option[key], axis)
  if ('legend' in option) option.legend = each(option.legend, { textStyle: text, pageTextStyle: soft, pageIconColor: colours.muted, pageIconInactiveColor: colours.line })
  if ('title' in option) option.title = each(option.title, { textStyle: text, subtextStyle: soft })
  if ('visualMap' in option) option.visualMap = each(option.visualMap, { textStyle: soft })
  if ('radar' in option) option.radar = each(option.radar, { axisName: soft, axisLine: line, splitLine: line, splitArea: { show: false } })
  if (Array.isArray(option.series)) {
    option.series = option.series.map((one) => (isObject(one) && LABEL_BESIDE.has(String(one.type))
      ? under({ label: text }, one) : one))
  }
  const tip = { backgroundColor: colours.surface, borderColor: colours.line, textStyle: text }
  option.tooltip = each(option.tooltip, tip)
}

/** The AI's option with only the allowed keys, the app's colours and font, and a text-only tooltip. With
 *  colours (the theme's): the texts and lines the AI gave no colour get them. */
export function safeOption(raw: Json, palette: string[], colours?: Colours): EChartsCoreOption {
  const option: Json = { color: palette, textStyle: { fontFamily: FONT } }
  for (const key of ALLOWED_KEYS) if (key in raw) option[key] = raw[key]
  const textTip = (tip: unknown) => ({ ...(tip && typeof tip === 'object' ? tip : {}), renderMode: 'richText', confine: true })
  option.tooltip = Array.isArray(option.tooltip) ? option.tooltip.map(textTip) : textTip(option.tooltip ?? { trigger: 'item' })
  if (colours) themed(option, colours)
  return option as EChartsCoreOption
}

export interface AiChartProps {
  option: Json
  title?: string
  kind: string // what was asked for: 'sankey diagram'
  tokens: number | null
  recorded: boolean // the tokens were added to the question's own count
}

export default function AiChart({ option, title = '', kind, tokens, recorded }: AiChartProps) {
  const theme = useThemeName()
  const colours = useMemo(() => readColours(theme), [theme])
  const safe = useMemo(() => safeOption(option, colours.series, colours), [option, colours])
  const chart = useRef<EChartsType | null>(null)
  const [width, setWidth] = useState(0)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const height = width > 0 && width < NARROW ? 300 : 380

  const save = () => {
    if (!chart.current) return
    setSaving(true)
    setSaveError('')
    downloadPng(chart.current, pngName(title || kind), title, '', colours)
      .catch(() => setSaveError('The PNG could not be made in this browser.'))
      .finally(() => setSaving(false))
  }

  const used = tokens == null ? '' : ` · ${tokens.toLocaleString('en-US')} AI tokens${recorded ? " (added to this question's tokens)" : ''}`
  return (
    <div className="min-w-0 rounded-xl border border-border bg-card px-4 pt-3 pb-2.5 text-card-foreground shadow-[0_10px_26px_-24px_rgba(17,16,16,.35)] dark:shadow-none max-[700px]:px-2.5">
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-0 text-[13.5px] font-semibold text-heading [overflow-wrap:anywhere]">
          {title ? `${title} - ` : ''}{kind} <span className="chip info ml-1.5 align-middle">AI</span>
        </div>
        <span className="ml-auto flex flex-wrap items-center gap-1.5 max-[700px]:ml-0">
          <Button type="button" variant="outline" size="sm" onClick={save} disabled={saving}>
            <Download aria-hidden="true" className="size-3.5" />
            {saving ? 'Saving…' : 'Download PNG'}
          </Button>
        </span>
      </div>
      <div className="w-full min-w-0" role="img" aria-label={`A ${kind} made by the AI from the answer's rows.`}>
        <EChart option={safe} height={height} onReady={(made) => { chart.current = made }} onWidth={setWidth} />
      </div>
      <div className="mt-1.5 text-[12.5px] text-muted-foreground">Made by the AI from the answer's rows{used}. Check it against the table.</div>
      {saveError && <div className="mt-1.5 text-[12.5px] text-destructive" role="alert">{saveError}</div>}
    </div>
  )
}
