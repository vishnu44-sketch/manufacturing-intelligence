// The ECharts options of the Insights page (pure: no React, no ECharts import, so the tests can check them):
// - the sales forecast: the last 12 actual sales months as a solid line, then the 3 forecast months as a dashed
//   line that starts at the last actual month, over a soft band from the low to the high estimate (two stacked
//   lines: an invisible one up to "low", and a filled one of "high - low" on top of it);
// - the customer groups: a donut of the customers in each group (the tooltip adds the group's sales).
// Colours come from readColours (the app's light / dark theme), never written here.
import type { InsightsForecast, InsightsSegment } from '../types'
import type { EChartsCoreOption } from './echarts'
import { ANIMATION_MS, type Colours, FONT, escapeHtml, fade, shortValue } from './chartOption'
import { shortIndian } from './pickChart'

/** Money for a chart label or tooltip: 'INR 6.36 Cr', 'INR 24.6 L'. */
export const inrShort = (n: number) => `INR ${shortValue(n)}`

const tooltipBox = (colours: Colours) => ({
  confine: true,
  backgroundColor: colours.surface,
  borderColor: colours.line,
  padding: [8, 10],
  textStyle: { color: colours.ink, fontSize: 12, fontFamily: FONT },
  extraCssText: `border-radius:10px;box-shadow:0 8px 22px -12px ${colours.dark ? 'rgba(0,0,0,.7)' : 'rgba(17,16,16,.35)'};max-width:300px;white-space:normal;`,
})

const motion = (animate: boolean) => (animate
  ? { animation: true, animationDuration: ANIMATION_MS, animationEasing: 'cubicOut' as const }
  : { animation: false })

/** A row of the tooltip: a colour key, the name and the value. */
const tipRow = (colour: string, name: string, value: string) =>
  `<div style="display:flex;align-items:center;gap:6px;margin-top:3px"><span style="width:8px;height:8px;border-radius:2px;background:${colour}"></span>`
  + `<span>${escapeHtml(name)}</span><b style="margin-left:auto;padding-left:12px">${escapeHtml(value)}</b></div>`

/** The four series of the forecast chart and its month names (the tests check these). */
export function forecastSeries(forecast: InsightsForecast) {
  const history = forecast.history ?? []
  const months = forecast.months ?? []
  const n = history.length
  const labels = [...history.map((h) => h.month), ...months.map((m) => m.month)]
  const gap = (count: number) => Array.from({ length: count }, () => null as number | null)
  const lastActual = n ? history[n - 1].actual : null
  // the forecast line and the band start at the last actual month, so the dashed line joins the solid one
  const join = (value: number | null) => (n ? [...gap(n - 1), value] : [])
  return {
    labels,
    actual: [...history.map((h) => h.actual), ...gap(months.length)],
    forecast: [...join(lastActual), ...months.map((m) => m.forecast)],
    low: [...join(lastActual), ...months.map((m) => m.low)],
    band: [...join(0), ...months.map((m) => Math.max(0, m.high - m.low))],
  }
}

export function forecastOption(forecast: InsightsForecast, colours: Colours, narrow: boolean, animate: boolean): EChartsCoreOption {
  const { labels, actual, forecast: ahead, low, band } = forecastSeries(forecast)
  const n = (forecast.history ?? []).length
  const months = forecast.months ?? []
  const actualColour = colours.series[0]
  const aheadColour = colours.series[1]
  return {
    ...motion(animate),
    textStyle: { fontFamily: FONT },
    grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true },
    legend: {
      top: 0, right: 0, itemWidth: 18, itemHeight: 8, itemGap: 14, textStyle: { color: colours.muted, fontSize: 11.5 },
      data: [
        { name: 'Actual', icon: 'roundRect' },
        { name: 'Forecast', icon: 'roundRect' },
        { name: 'Likely range', icon: 'rect' },
      ],
    },
    tooltip: {
      ...tooltipBox(colours),
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: colours.muted, type: 'dashed' } },
      formatter: (params: unknown) => {
        const first = (Array.isArray(params) ? params[0] : params) as { dataIndex?: number } | undefined
        const i = first?.dataIndex ?? -1
        if (i < 0 || i >= labels.length) return ''
        let html = `<b>${escapeHtml(labels[i])}</b>`
        if (i < n) html += tipRow(actualColour, 'Actual', inrShort(actual[i] ?? 0))
        else {
          const m = months[i - n]
          html += tipRow(aheadColour, 'Forecast', inrShort(m.forecast))
          html += tipRow(fade(aheadColour, 0.35), 'Likely range', `${shortValue(m.low)} – ${shortValue(m.high)}`)
        }
        return html
      },
    },
    xAxis: {
      type: 'category', data: labels, boundaryGap: false,
      axisLabel: { color: colours.muted, fontSize: 11, hideOverlap: true, formatter: (text: string) => (narrow ? String(text).slice(0, 3) : String(text)) },
      axisLine: { lineStyle: { color: colours.line } }, axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: colours.muted, fontSize: 11, formatter: (v: number) => shortIndian(v) },
      splitLine: { lineStyle: { color: colours.line } }, axisLine: { show: false }, axisTick: { show: false },
    },
    series: [
      {
        // the bottom of the band: an invisible line up to the low estimate
        name: 'Low', type: 'line', data: low, stack: 'band', symbol: 'none', silent: true, connectNulls: false,
        lineStyle: { opacity: 0 }, tooltip: { show: false }, emphasis: { disabled: true },
      },
      {
        name: 'Likely range', type: 'line', data: band, stack: 'band', symbol: 'none', silent: true,
        lineStyle: { opacity: 0 }, itemStyle: { color: fade(aheadColour, 0.35) },
        areaStyle: { color: fade(aheadColour, colours.dark ? 0.22 : 0.16) }, tooltip: { show: false }, emphasis: { disabled: true },
      },
      {
        name: 'Actual', type: 'line', data: actual, smooth: 0.3, symbol: 'circle', symbolSize: narrow ? 5 : 7,
        itemStyle: { color: actualColour, borderColor: colours.surface, borderWidth: 2 },
        lineStyle: { width: 2.5, color: actualColour },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: fade(actualColour, 0.16) }, { offset: 1, color: fade(actualColour, 0) }] } },
      },
      {
        name: 'Forecast', type: 'line', data: ahead, smooth: 0.3, symbol: 'circle', symbolSize: narrow ? 5 : 7,
        itemStyle: { color: aheadColour, borderColor: colours.surface, borderWidth: 2 },
        lineStyle: { width: 2.5, color: aheadColour, type: 'dashed' },
      },
    ],
  }
}

/** The donut of the customer groups: customers per group; the tooltip adds the sales. */
export function segmentsOption(segments: InsightsSegment[], colours: Colours, narrow: boolean, animate: boolean): EChartsCoreOption {
  const total = segments.reduce((sum, s) => sum + (s.customers || 0), 0)
  return {
    ...motion(animate),
    color: colours.series,
    textStyle: { fontFamily: FONT },
    tooltip: {
      ...tooltipBox(colours),
      trigger: 'item',
      formatter: (params: unknown) => {
        const p = params as { dataIndex?: number; color?: string }
        const s = segments[p.dataIndex ?? -1]
        if (!s) return ''
        const share = total > 0 ? Math.round((s.customers / total) * 100) : 0
        return `<b>${escapeHtml(s.segment_name)}</b>`
          + tipRow(String(p.color ?? colours.series[0]), 'Customers', `${s.customers.toLocaleString('en-IN')} (${share}%)`)
          + tipRow(String(p.color ?? colours.series[0]), 'Sales', inrShort(s.sales_inr))
      },
    },
    series: [{
      type: 'pie', name: 'Customers', radius: narrow ? ['48%', '78%'] : ['52%', '80%'], center: ['50%', '50%'],
      avoidLabelOverlap: true, label: { show: false }, labelLine: { show: false },
      itemStyle: { borderColor: colours.surface, borderWidth: 2, borderRadius: 4 },
      emphasis: { scale: true, scaleSize: 4 },
      data: segments.map((s) => ({ name: s.segment_name, value: s.customers })),
    }],
    // the total in the middle of the ring is HTML laid over the chart (InsightsChart), so no title component
  }
}
