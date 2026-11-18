// A chart of the Insights page (loaded lazily with ECharts, like the answer charts): the sales forecast or the
// donut of the customer groups. The options are built in insightsOption.ts; the colours follow the theme (light /
// dark) - when it changes the chart is drawn again. Screen readers get a sentence (label) instead of the picture.
import { useMemo, useState } from 'react'
import type { InsightsForecast, InsightsSegment } from '../types'
import { NARROW, readColours, wantsMotion } from './chartOption'
import EChart from './EChart'
import { forecastOption, segmentsOption } from './insightsOption'
import useThemeName from './useThemeName'
import './chart.css'

export type InsightsChartProps =
  | { kind: 'forecast'; forecast: InsightsForecast; label: string; height?: number }
  | { kind: 'segments'; segments: InsightsSegment[]; label: string; height?: number; centre?: string }

export default function InsightsChart(props: InsightsChartProps) {
  const theme = useThemeName()
  const colours = useMemo(() => readColours(theme), [theme])
  const [width, setWidth] = useState(0)
  const narrow = width > 0 && width < NARROW
  const height = props.height ?? (props.kind === 'forecast' ? (narrow ? 230 : 280) : 210)
  const data = props.kind === 'forecast' ? props.forecast : props.segments
  const option = useMemo(
    () => (props.kind === 'forecast'
      ? forecastOption(data as InsightsForecast, colours, narrow, wantsMotion())
      : segmentsOption(data as InsightsSegment[], colours, narrow, wantsMotion())),
    [props.kind, data, colours, narrow],
  )
  return (
    <div className="relative w-full min-w-0" role="img" aria-label={props.label} data-chart={props.kind}>
      <EChart option={option} height={height} onWidth={setWidth} />
      {props.kind === 'segments' && props.centre && (
        // the number of customers in the middle of the ring
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center leading-tight">
          <span className="text-[20px] font-semibold text-heading tabular-nums">{props.centre}</span>
          <span className="text-[11px] text-muted-foreground">customers</span>
        </div>
      )}
    </div>
  )
}
