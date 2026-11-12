// The ECharts option for a ChartPick (pure: no React, no ECharts import), the sentence screen readers get
// (describe), the app's colours (light and dark: readColours) and the PNG download. The axis shows short Indian numbers (1.2 Cr, 35 L,
// 12 K); the tooltip the value as the table shows it (money also short: "6.36 Cr (63,648,019.00)") and
// column names written for people ("Net sales (INR)"). Lines, bars and the donut get a soft "3D" look
// (fades, shadows, rounded bars) and grow in when they appear (not with reduced motion).
import type { EChartsCoreOption, EChartsType } from './echarts'
import { type CatchAll, type ChartPick, type ChartPoint, shortIndian } from './pickChart'

export type ThemeName = 'light' | 'dark'

export type Colours = {
  dark: boolean // the dark theme
  series: string[]; ink: string; muted: string; line: string; low: string; high: string; up: string; down: string; total: string
  surface: string // the card a chart sits on: the tooltip's box, the thin line between slices, a dark PNG's background
  box: string // the Knowledge graph's drawing box (the 3D scene behind the balls)
}

/** The theme now: <html data-theme="dark"> is dark, anything else light (the menu's switch sets the attribute). */
export function themeName(): ThemeName {
  return typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'
}

// the chart colours (12-Nov: the blue brand first; still no red / yellow): blue, teal, amber, violet, green, cyan,
// rose - neighbours stay apart for colour-blind readers too; the last 3 (brown, indigo, lime) for a pivot with
// many series. The dark theme has its own, lighter steps of the same colours, in the same order. The first one
// is the app's --brand (styles/app.css) in both themes; the constants here are its values there.
const SERIES_LIGHT = ['#0B5FB3', '#0D9488', '#D97706', '#7C3AED', '#16A34A', '#0891B2', '#DB2777',
  '#B45309', '#4F46E5', '#65A30D']
const SERIES_DARK = ['#4C9AFF', '#12A594', '#CC7F08', '#9B7BF0', '#1FA850', '#2B9BD3', '#E85A9B',
  '#B8692F', '#6D74EE', '#74A324']

// the app's variables for a card (--surface) and for a quiet box on it (--surface-2: Tailwind's bg-muted)
const SURFACE_NAMES = ['--surface']
const BOX_NAMES = ['--surface-2']

export const FONT = "Poppins, 'Segoe UI', sans-serif"
export const NARROW = 480 // px: a phone

const HEX = /^#[0-9a-f]{6}$/i

/** The chart colours for a theme: the series palette above (its first colour is the app's --brand); the text,
 *  grid and surface colours from the app (styles/app.css has light and dark values). Where a variable is empty
 *  (the tests, a page without the stylesheet) the theme's own constants are used. */
export function readColours(theme: ThemeName = themeName()): Colours {
  const dark = theme === 'dark'
  const css = typeof window === 'undefined' ? null : getComputedStyle(document.documentElement)
  const token = (name: string, fallback: string) => css?.getPropertyValue(name).trim() || fallback
  // a colour the charts fade and shade must be #rrggbb: anything else (rgb(), a colour name) -> the constant
  const hex = (names: string[], fallback: string) => {
    for (const name of names) {
      const value = token(name, '')
      if (HEX.test(value)) return value
      if (/^#[0-9a-f]{3}$/i.test(value)) return `#${[...value.slice(1)].map((c) => c + c).join('')}`
    }
    return fallback
  }
  const series = dark ? SERIES_DARK : SERIES_LIGHT
  return {
    dark,
    series: [hex(['--brand'], series[0]), ...series.slice(1)],
    ink: token('--ink', dark ? '#E6EAF2' : '#212529'),
    muted: token('--muted', dark ? '#9AA6B8' : '#5F6873'),
    line: hex(['--line'], dark ? '#263042' : '#E3E6EB'),
    low: dark ? '#1B2E4A' : '#E0F2FE', // the heatmap: light blue to dark blue ...
    high: dark ? '#60A5FA' : '#1D4ED8', // ... on dark: from a dark blue (near the card) up to a bright one
    up: dark ? '#1FA850' : '#16A34A', // waterfall: an increase is green ...
    down: dark ? '#E0802B' : '#F97316', // ... a decrease orange
    // the waterfall's total and the treemap's category band (white text on it): the heading colour, which is
    // near white on dark - there a slate that still carries white text
    total: dark ? '#5B6878' : token('--head', '#32353A'),
    surface: hex(SURFACE_NAMES, dark ? '#171D2B' : '#fff'),
    box: hex(BOX_NAMES, dark ? '#1C2333' : '#F8F9FB'),
  }
}

// the soft shadows of the "3D" look: black shadows hardly show on a dark card, so they are stronger there
const shadows = (colours: Colours) => (colours.dark
  ? { tip: 'rgba(0,0,0,.7)', slice: 'rgba(0,0,0,.45)', lifted: 'rgba(0,0,0,.65)' }
  : { tip: 'rgba(17,16,16,.35)', slice: 'rgba(17,16,16,.16)', lifted: 'rgba(17,16,16,.28)' })

export function cutText(text: string, most: number): string {
  return text.length > most ? `${text.slice(0, most - 1)}…` : text
}

/** Text for the HTML tooltip (a name in the data may hold < or &). */
export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string)
}

const KIND_TITLES: Record<ChartPick['kind'], string> = {
  line: 'Line chart', area: 'Area chart', stackedArea: 'Stacked area chart', bar: 'Bar chart',
  hbar: 'Horizontal bar chart', stacked: 'Stacked bar chart', grouped: 'Grouped bar chart', pie: 'Donut chart',
  treemap: 'Treemap', heatmap: 'Heatmap', scatter: 'Scatter chart', funnel: 'Funnel chart', radar: 'Radar chart',
  waterfall: 'Waterfall chart',
}

const money = (n: number) => n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

// the unit at the end of a column name, written for people: sales_inr -> "Sales (INR)", margin_pct -> "Margin (%)"
const UNITS = new Map([['inr', 'INR'], ['usd', 'USD'], ['jpy', 'JPY'], ['pct', '%'], ['percent', '%']])
const CAPITALS = new Set(['gst', 'fy', 'id', 'po', 'sku', 'hsn', 'uom'])

/** A column name as people say it: 'net_sales_inr' -> 'Net sales (INR)', 'qty' -> 'Quantity',
 *  'margin_pct' -> 'Margin (%)'. A name already written for people ('Net Sales') stays as it is. */
export function friendlyName(name: string): string {
  const raw = (name ?? '').trim()
  if (!raw.includes('_') && raw !== raw.toLowerCase()) return raw
  const words = raw.toLowerCase().split(/[_\s]+/).filter(Boolean)
  if (words.length === 0) return raw
  const unitName = words.length > 1 ? UNITS.get(words[words.length - 1]) : undefined
  if (unitName) words.pop()
  const text = words.map((w) => (w === 'qty' ? 'quantity' : w === 'pct' ? 'percent' : CAPITALS.has(w) ? w.toUpperCase() : w)).join(' ')
  return text.charAt(0).toUpperCase() + text.slice(1) + (unitName ? ` (${unitName})` : '')
}

// money columns: their tooltip shows the short form too (6.36 Cr); counts, quantities and % do not
const MONEY_NAME = /(_inr|_jpy|_usd|value|sales|amount|revenue|total|price|cost)/i
const NOT_MONEY = /(qty|quantity|count|pct|percent|share|ratio|(^|_)rate($|_)|growth|^no_of|^num_)/i
export const isMoney = (name: string) => MONEY_NAME.test(name) && !NOT_MONEY.test(name)

/** A value written short for a label or the tooltip, a bit more exact than the axis: 63648019 -> '6.36 Cr',
 *  2462000 -> '24.6 L', 950 -> '950', 0 -> '0'. */
export function shortValue(n: number): string {
  if (n === 0) return '0'
  const abs = Math.abs(n)
  const [size, unitName] = abs >= 1e7 ? [1e7, ' Cr'] : abs >= 1e5 ? [1e5, ' L'] : abs >= 1e3 ? [1e3, ' K'] : [1, '']
  const scaled = n / size
  const places = Math.abs(scaled) >= 100 ? 0 : Math.abs(scaled) >= 10 ? 1 : 2
  return scaled.toLocaleString('en-IN', { maximumFractionDigits: places }) + unitName
}

/** A value in the tooltip: money short and in full ('6.36 Cr (63,648,019.00)'), anything else as the table
 *  shows it; 0 is '0', no value is '-'. text = the value as the table shows it. */
export function tipValue(value: number | null, text = '', moneyValue = true): string {
  if (value === null) return text || '-'
  if (value === 0) return '0'
  const full = text || money(value)
  return moneyValue && Math.abs(value) >= 1000 ? `${shortValue(value)} (${full})` : full
}

/** A label on a bar or at the end of a line: the short value ('6.36 Cr'). */
const valueLabel = (params: { value?: unknown }) => {
  const v = Array.isArray(params.value) ? params.value[params.value.length - 1] : params.value
  return typeof v === 'number' ? shortValue(v) : ''
}

// the "3D" look: a colour faded, or mixed with white (amount > 0) or black (amount < 0)
function rgb(colour: string): number[] | null {
  const m = /^#([0-9a-f]{6})$/i.exec(colour.trim())
  if (!m) return null
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}
export function fade(colour: string, alpha: number): string {
  const c = rgb(colour)
  return c ? `rgba(${c.join(',')},${alpha})` : colour
}
export function shade(colour: string, amount: number): string {
  const c = rgb(colour)
  if (!c) return colour
  const to = amount > 0 ? 255 : 0
  return `#${c.map((v) => Math.round(v + (to - v) * Math.abs(amount)).toString(16).padStart(2, '0')).join('')}`
}
/** A gradient top to bottom (vertical) or left to right. */
const gradient = (vertical: boolean, stops: [number, string][]) => ({
  type: 'linear', x: 0, y: 0, x2: vertical ? 0 : 1, y2: vertical ? 1 : 0,
  colorStops: stops.map(([offset, color]) => ({ offset, color })),
})

/** The arrows and the page number of a legend too long for one row, in the theme's colours. */
const legendPages = (colours: Colours) => ({
  pageIconColor: colours.muted, pageIconInactiveColor: colours.line, pageTextStyle: { color: colours.muted },
})

/** How long a line draws itself / bars grow when the chart appears. */
export const ANIMATION_MS = 700

/** False when the person asked for less motion (prefers-reduced-motion), or the browser cannot say. */
export function wantsMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' &&
    !window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** A share for a label: '97%', '4.6%', '<0.1%'. */
export function percent(share: number): string {
  if (share > 0 && share < 0.1) return '<0.1%'
  return `${share >= 10 ? Math.round(share) : Number(share.toFixed(1))}%`
}

/** 'Not classified (398 Cr, 97% of the total)' */
export function catchAllText(c: CatchAll): string {
  return `${c.name} (${shortIndian(c.total)}, ${percent(c.share)} of the total)`
}

/** The line under the PNG's title: which group the chart leaves out ('' when none). */
export function chartSubtitle(pick: ChartPick): string {
  return pick.catchAll?.hidden ? `${catchAllText(pick.catchAll)} is hidden.` : ''
}

/** The highest value drawn: of the first series, or of every cell after a pivot (with its series name). */
function peak(pick: ChartPick, word = 'highest'): string {
  let best: { label: string; text: string; value: number } | null = null
  for (const p of pick.data) {
    const values = pick.group ? p.values : p.values.slice(0, 1)
    values.forEach((v, i) => {
      if (v !== null && (best === null || v > best.value)) {
        best = { label: pick.group ? `${p.label} ${pick.ys[i]}` : p.label, text: p.texts[i], value: v }
      }
    })
  }
  const found = best as { label: string; text: string } | null
  return found ? `${word} ${found.label} ${found.text}` : 'no values'
}

/** One sentence for screen readers: what is drawn and its highest point (and the group it hides). */
export function describe(pick: ChartPick): string {
  const hidden = chartSubtitle(pick)
  return hidden ? `${sentence(pick)} ${hidden}` : sentence(pick)
}

function sentence(pick: ChartPick): string {
  const subject = `${pick.amount} by ${pick.x}${pick.group ? ` and ${pick.group}` : ''}`
  const n = pick.data.length
  const name = KIND_TITLES[pick.kind]
  const note = pick.note ? ` (${pick.note})` : ''
  switch (pick.kind) {
    case 'pie': {
      const total = pick.data.reduce<number>((sum, p) => sum + (p.values[0] ?? 0), 0)
      const parts = pick.data.map((p) => `${p.label} ${Math.round(((p.values[0] ?? 0) / total) * 100)}%`)
      return `Donut chart of ${subject}: ${parts.join(', ')}.`
    }
    case 'line': case 'area': case 'stackedArea':
      return `${name} of ${subject}, ${n} points from ${pick.data[0].label} to ${pick.data[n - 1].label}, ${peak(pick)}.`
    case 'treemap':
      return `Treemap of ${subject}, ${n} boxes${note}, ${peak(pick, 'largest')}.`
    case 'heatmap':
      return `Heatmap of ${subject}, ${n} rows by ${pick.ys.length} columns${note}, ${peak(pick)}.`
    case 'scatter':
      return `Scatter chart of ${pick.ys[1]} against ${pick.ys[0]}, one point per ${pick.x}, ${n} points.`
    case 'funnel':
      return `Funnel chart of ${subject}: ${pick.data.map((p) => `${p.label} ${p.texts[0]}`).join(', ')}.`
    case 'radar':
      return `Radar chart of ${subject}, ${n} spokes, ${peak(pick)}.`
    case 'waterfall': {
      const total = pick.data.reduce<number>((sum, p) => sum + (p.values[0] ?? 0), 0)
      return `Waterfall chart of ${subject}, ${n} steps, total ${money(total)}.`
    }
    default:
      return `${name} of ${subject}, ${n} bars${note}, ${peak(pick)}.`
  }
}

// the tooltip's rows: a colour key, the name, the value as the table shows it
type TipRow = { colour: string; name: string; text: string }
function tipHtml(label: string, rows: TipRow[], extra = ''): string {
  const lines = rows.map((r) =>
    `<div class="chart-tip-row"><span class="chart-key" style="background:${r.colour}"></span>` +
    `<span class="chart-tip-name">${escapeHtml(r.name)}</span><b>${escapeHtml(r.text)}</b></div>`)
  return `<div class="chart-tip-label">${escapeHtml(label)}</div>${lines.join('')}${extra}`
}

type Param = { dataIndex: number; seriesIndex: number; color?: string; data?: unknown; name?: string }
const first = (params: unknown): Param => (Array.isArray(params) ? params[0] : params) as Param

// a treemap label: 11px text on 14px lines, 5px padding, about 6.6px a letter
const LABEL_LINE = 14
const LABEL_PAD = 5
const LABEL_CHAR = 6.6

/** Whether a treemap label fits its box: one line high at least, and as wide as its lines that fit (a long name
 *  may end in "…" after 6 letters). A smaller box shows no label - its tooltip still has everything. */
export function labelFits(box: { width: number; height: number }, text: string): boolean {
  const room = Math.floor((box.height - 2 * LABEL_PAD) / LABEL_LINE)
  if (room < 1) return false
  const widest = Math.max(...text.split('\n').slice(0, room).map((line) => Math.min(line.length, 7)))
  return box.width - 2 * LABEL_PAD >= widest * LABEL_CHAR
}

/** What buildOption gives: the option, the chart's height, and what a click does (the treemap's drill-down). */
export type Built = { option: EChartsCoreOption; height: number; onClick?: (params: unknown, chart: EChartsType) => void }

/** The option and the height of the chart for this pick. narrow = a phone; width = the box's width in px
 *  (0 = not known yet); animate = the line draws itself, bars grow, a donut opens (off for reduced motion). */
const MANY_POINTS = 16 // a line with more points than this is drawn straight, with small dots (a FY of months stays smooth)
const MAX_DOTS_NARROW = 31 // on a phone: a line with more points than this has no dots (a line has at most 60 points)

export function buildOption(pick: ChartPick, colours: Colours, narrow: boolean, width = 0, animate = wantsMotion()): Built {
  const n = pick.data.length
  const s = pick.ys.length
  const palette = colours.series
  const colourOf = (i: number) => palette[i % palette.length]
  const labels = pick.data.map((p) => p.label)
  const boxWidth = width || (narrow ? 360 : 800)
  const legend = s > 1 && !['heatmap', 'treemap', 'scatter'].includes(pick.kind)
  // names for people: a column name 'net_sales_inr' -> 'Net sales (INR)'; after a pivot the series are values
  // of the rows (Domestic, CREDIT_NOTE) and stay as they are
  const seriesName = (i: number) => (pick.group ? pick.ys[i] : friendlyName(pick.ys[i]))
  const amountName = (i: number) => friendlyName(pick.group ? pick.amount : pick.ys[i])
  const moneyAt = (i: number) => isMoney(pick.group ? pick.amount : pick.ys[i])
  const valueAt = (p: ChartPoint, i: number) => tipValue(p.values[i], p.texts[i], moneyAt(i))
  const moving = animate && ['line', 'area', 'stackedArea', 'bar', 'hbar', 'stacked', 'grouped', 'pie'].includes(pick.kind)
  const shadow = shadows(colours)
  const tooltip = {
    confine: true,
    backgroundColor: colours.surface,
    borderColor: colours.line,
    padding: [8, 10],
    textStyle: { color: colours.ink, fontSize: 12, fontFamily: FONT },
    extraCssText: `border-radius:10px;box-shadow:0 8px 22px -12px ${shadow.tip};max-width:340px;white-space:normal;`,
  }
  const base: EChartsCoreOption = {
    animation: moving,
    ...(moving ? { animationDuration: ANIMATION_MS, animationEasing: 'cubicOut', animationDurationUpdate: 300,
      animationEasingUpdate: 'cubicOut' } : {}),
    color: palette,
    textStyle: { fontFamily: FONT },
    ...(legend ? {
      legend: {
        type: 'scroll', bottom: 0, icon: 'rect', itemWidth: 10, itemHeight: 10, itemGap: 14,
        textStyle: { color: colours.ink, fontSize: 12 }, ...legendPages(colours),
      },
    } : {}),
  }
  const grid = { left: 8, right: 18, top: 14, bottom: legend ? 34 : 8, containLabel: true }
  const legendSpace = legend ? 28 : 0
  const valueAxis = (extra: object = {}) => ({
    type: 'value',
    axisLabel: { color: colours.muted, fontSize: 11, formatter: (v: number) => shortIndian(v) },
    splitLine: { lineStyle: { color: colours.line } },
    axisLine: { show: false }, axisTick: { show: false },
    ...extra,
  })
  const categoryAxis = (most: number, extra: object = {}) => ({
    type: 'category', data: labels,
    axisLabel: { color: colours.muted, fontSize: 11, formatter: (text: string) => cutText(String(text), most) },
    axisLine: { lineStyle: { color: colours.line } }, axisTick: { show: false },
    ...extra,
  })
  // one row per series for the category under the pointer, as the table shows it
  const axisTip = {
    ...tooltip,
    trigger: 'axis',
    axisPointer: { type: pick.kind === 'line' || pick.kind === 'area' || pick.kind === 'stackedArea' ? 'line' : 'shadow',
      lineStyle: { color: colours.muted, type: 'dashed' }, shadowStyle: { color: fade(colours.line, 0.6) } },
    formatter: (params: unknown) => {
      const point = pick.data[first(params).dataIndex]
      return point ? tipHtml(point.label, pick.ys.map((_, i) => ({ colour: colourOf(i), name: seriesName(i), text: valueAt(point, i) }))) : ''
    },
  }

  switch (pick.kind) {
    case 'line': case 'area': case 'stackedArea': {
      const stackedArea = pick.kind === 'stackedArea'
      // a soft fade under each line (lighter with several lines), the last value written at the end of the
      // line - for up to 3 lines (1 on a phone), moved apart when they would touch
      const fadeTop = stackedArea ? 0.7 : pick.kind === 'area' ? 0.35 : s > 1 ? 0.12 : 0.25
      const fadeBottom = stackedArea ? 0.35 : 0
      const endLabels = !stackedArea && s <= (narrow ? 1 : 3)
      // 12-Nov: 31 days, 10 of them with no sales, drawn smooth looked like sales rising and falling over 2-3
      // days. Many points (more than 16): straight lines and a small dot on each point, so a peak is one day.
      // On a phone more than 31 points get no dots: they would only make a thick band there.
      const many = n > MANY_POINTS
      const dots = !narrow || n <= MAX_DOTS_NARROW
      const option = {
        ...base, tooltip: axisTip,
        grid: { ...grid, right: endLabels ? (narrow ? 52 : 64) : grid.right },
        xAxis: categoryAxis(narrow ? 8 : 14, { boundaryGap: false, axisLabel: { color: colours.muted, fontSize: 11,
          hideOverlap: true, formatter: (text: string) => cutText(String(text), narrow ? 8 : 14) } }),
        yAxis: valueAxis(),
        series: pick.ys.map((_, i) => {
          const colour = colourOf(i)
          return {
            type: 'line', name: seriesName(i), data: pick.data.map((p) => p.values[i]), smooth: many ? false : 0.35,
            symbol: dots ? 'circle' : 'none', symbolSize: many ? (narrow ? 4 : 5) : (narrow ? 6 : 8), showSymbol: dots,
            itemStyle: { color: colour, borderColor: colours.surface, borderWidth: many ? 1 : 2 },
            lineStyle: { width: s > 1 ? 2 : 2.5, color: colour, shadowBlur: 8, shadowColor: fade(colour, 0.35), shadowOffsetY: 3 },
            areaStyle: { color: gradient(true, [[0, fade(colour, fadeTop)], [1, fade(colour, fadeBottom)]]) },
            emphasis: { focus: 'series', lineStyle: { width: s > 1 ? 2.5 : 3 } },
            ...(endLabels ? {
              endLabel: { show: true, color: colour, fontSize: narrow ? 10 : 11, fontWeight: 600, distance: 6, formatter: valueLabel },
              labelLayout: { moveOverlap: 'shiftY' },
            } : {}),
            ...(stackedArea ? { stack: 'total' } : {}),
          }
        }),
      }
      return { option, height: (narrow ? 240 : 300) + legendSpace }
    }

    case 'bar': case 'hbar': case 'stacked': case 'grouped': {
      const stacked = pick.kind === 'stacked'
      const negative = pick.data.some((p) => p.values.some((v) => v !== null && v < 0))
      const horizontal = pick.horizontal || (narrow && n > 5)
      const labelChars = narrow ? 12 : 22
      // rounded at the outer end (not stacked: the segments would be rounded in the middle), light at the end
      // and darker at the axis, a soft shadow; the value on each bar only when there are few bars
      const radius = negative || stacked ? 0 : horizontal ? [0, 6, 6, 0] : [6, 6, 0, 0]
      const barLabels = !stacked && !negative && s <= (narrow ? 1 : 2) && n <= (narrow ? 8 : 12)
      const series = pick.ys.map((_, i) => {
        const colour = colourOf(i)
        const [light, dark] = [shade(colour, 0.22), shade(colour, -0.12)]
        return {
          type: 'bar', name: seriesName(i), data: pick.data.map((p) => p.values[i]),
          stack: stacked ? 'total' : undefined, barMaxWidth: 36, barGap: '10%',
          itemStyle: {
            borderRadius: radius,
            color: horizontal ? gradient(false, [[0, dark], [1, light]]) : gradient(true, [[0, light], [1, dark]]),
            ...(stacked ? {} : { shadowBlur: 6, shadowColor: fade(colour, 0.28), shadowOffsetY: 2 }),
          },
          emphasis: { focus: stacked ? 'series' : 'none', itemStyle: stacked ? {} : { shadowBlur: 12, shadowColor: fade(colour, 0.4) } },
          ...(barLabels ? { label: { show: true, position: horizontal ? 'right' : 'top', distance: 4, color: colours.ink,
            fontSize: narrow ? 10 : 11, fontWeight: 500, formatter: valueLabel } } : {}),
        }
      })
      const barGrid = barLabels ? (horizontal ? { ...grid, right: narrow ? 48 : 56 } : { ...grid, top: 24 }) : grid
      const option = horizontal
        ? { ...base, grid: barGrid, tooltip: axisTip, xAxis: valueAxis(), series,
          yAxis: categoryAxis(labelChars, { inverse: true, axisLabel: {
            color: colours.muted, fontSize: 11, interval: 0, formatter: (text: string) => cutText(String(text), labelChars) } }) }
        : { ...base, grid: barGrid, tooltip: axisTip, yAxis: valueAxis(), series,
          xAxis: categoryAxis(narrow ? 8 : 14, { axisLabel: {
            color: colours.muted, fontSize: 11, interval: 0, hideOverlap: true,
            formatter: (text: string) => cutText(String(text), narrow ? 8 : 14) } }) }
      const perBar = 12 * (stacked ? 1 : s) + 14
      const height = horizontal ? Math.max(220, n * perBar + 50) : narrow ? 240 : 300
      return { option, height: height + legendSpace }
    }

    case 'waterfall': {
      // a step starts where the last one ended: an invisible base bar + the step; the total at the end
      let running = 0
      const bases: number[] = []
      const steps: { value: number; itemStyle: { color: string } }[] = []
      for (const p of pick.data) {
        const v = p.values[0] ?? 0
        bases.push(Math.min(running, running + v))
        steps.push({ value: Math.abs(v), itemStyle: { color: v >= 0 ? colours.up : colours.down } })
        running += v
      }
      bases.push(0)
      steps.push({ value: running, itemStyle: { color: colours.total } })
      const all = [...labels, 'Total']
      const option = {
        ...base, grid,
        tooltip: {
          ...tooltip, trigger: 'item',
          formatter: (params: unknown) => {
            const i = first(params).dataIndex
            if (i >= pick.data.length) {
              return tipHtml('Total', [{ colour: colours.total, name: amountName(0), text: tipValue(running, money(running), moneyAt(0)) }])
            }
            const total = pick.data.slice(0, i + 1).reduce<number>((sum, p) => sum + (p.values[0] ?? 0), 0)
            const v = pick.data[i].values[0] ?? 0
            return tipHtml(pick.data[i].label, [{ colour: v >= 0 ? colours.up : colours.down, name: amountName(0), text: valueAt(pick.data[i], 0) }],
              `<div class="chart-tip-row mut">Running total ${escapeHtml(money(total))}</div>`)
          },
        },
        xAxis: { ...categoryAxis(narrow ? 8 : 12), data: all, axisLabel: {
          color: colours.muted, fontSize: 11, interval: 0, rotate: n > 6 ? 30 : 0,
          formatter: (text: string) => cutText(String(text), narrow ? 8 : 12) } },
        yAxis: valueAxis(),
        series: [
          { type: 'bar', stack: 'w', silent: true, data: bases, itemStyle: { color: 'transparent' }, tooltip: { show: false } },
          { type: 'bar', stack: 'w', name: amountName(0), data: steps, barMaxWidth: 40 },
        ],
      }
      return { option, height: narrow ? 260 : 320 }
    }

    case 'pie': {
      const total = pick.data.reduce<number>((sum, p) => sum + (p.values[0] ?? 0), 0)
      const share = (v: number | null) => (total > 0 ? ((v ?? 0) / total) * 100 : 0)
      const option = {
        ...base,
        legend: {
          type: 'scroll', bottom: 0, icon: 'rect', itemWidth: 10, itemHeight: 10, itemGap: 14,
          textStyle: { color: colours.ink, fontSize: 12 }, ...legendPages(colours),
          formatter: (name: string) => {
            const point = pick.data.find((p) => p.label === name)
            return `${name} · ${percent(share(point?.values[0] ?? 0))}`
          },
        },
        tooltip: {
          ...tooltip, trigger: 'item',
          formatter: (params: unknown) => {
            const { dataIndex } = first(params)
            const point = pick.data[dataIndex]
            return tipHtml(point.label, [{ colour: colourOf(dataIndex), name: amountName(0), text: valueAt(point, 0) }],
              `<div class="chart-tip-row mut">${share(point.values[0]).toFixed(1)}% of the total</div>`)
          },
        },
        series: [{
          type: 'pie', name: amountName(0), radius: narrow ? ['36%', '56%'] : ['45%', '68%'], center: ['50%', '45%'], padAngle: 1,
          avoidLabelOverlap: true,
          // name and % beside the slices big enough for them; the legend lists every slice
          minShowLabelAngle: 10,
          label: { show: true, color: colours.ink, fontSize: 11, lineHeight: 14,
            formatter: (params: { dataIndex: number }) => {
              const point = pick.data[params.dataIndex]
              return `${cutText(point.label, narrow ? 12 : 22)}\n${percent(share(point.values[0]))}`
            } },
          labelLine: { show: true, length: 6, length2: 8, lineStyle: { color: colours.muted } },
          // a thin line in the card's colour (white; dark on dark) between the slices and a soft shadow; the
          // slice under the pointer lifts a little
          itemStyle: { borderColor: colours.surface, borderWidth: narrow ? 1 : 1.5, shadowBlur: 10, shadowOffsetY: 3,
            shadowColor: shadow.slice },
          emphasis: { scale: true, scaleSize: narrow ? 4 : 7,
            itemStyle: { shadowBlur: 22, shadowOffsetY: 6, shadowColor: shadow.lifted } },
          data: pick.data.map((p) => ({ name: p.label, value: p.values[0] })),
        }],
      }
      return { option, height: narrow ? 300 : 320 }
    }

    case 'treemap': {
      // a pivot is nested: a box per category (its name on a dark band), inside it a box per series (one colour
      // each); a click on a category shows only it (ECharts' drill-down), the breadcrumb goes back to "All"
      const nested = s > 1
      const height = narrow ? 300 : 360
      const sizeOf = (p: ChartPoint) => (nested ? p.values : p.values.slice(0, 1))
        .reduce<number>((sum, v) => sum + (v !== null && v > 0 ? v : 0), 0)
      const total = pick.data.reduce<number>((sum, p) => sum + sizeOf(p), 0)
      const share = (v: number | null) => (total > 0 ? ((v ?? 0) / total) * 100 : 0)
      const mut = (text: string) => `<div class="chart-tip-row mut">${escapeHtml(text)}</div>`
      const ofTotal = (v: number | null) => mut(`${percent(share(v))} of the shown total`)
      // a category's band only when its box is about 70px wide or more (8 letters), else the tooltip names it;
      // the name alone when its amount and % do not fit too
      const side = (v: number) => Math.sqrt((share(v) / 100) * boxWidth * height)
      const bandText = (name: string, v: number) => `${name}   ${shortIndian(v)} · ${percent(share(v))}`
      const band = (p: ChartPoint) => side(sizeOf(p)) < 70 ? { upperLabel: { show: false } }
        : bandText(p.label, sizeOf(p)).length * LABEL_CHAR + 10 > side(sizeOf(p)) ? { upperLabel: { formatter: '{b}' } } : {}
      const node = (p: ChartPoint, i: number) => nested
        ? {
          id: `c${i}`, name: p.label, itemStyle: { color: colours.total }, // the category's band: dark, its name in white
          ...band(p),
          tip: tipHtml(p.label,
            pick.ys.map((_, j) => ({ colour: colourOf(j), name: seriesName(j), text: valueAt(p, j) })).filter((_, j) => (p.values[j] ?? 0) > 0),
            `<div class="chart-tip-row"><span class="chart-tip-name">Total</span><b>${escapeHtml(tipValue(sizeOf(p), money(sizeOf(p)), moneyAt(0)))}</b></div>` +
            ofTotal(sizeOf(p)) + mut('Click to zoom in')),
          children: pick.ys.map((_, j) => ({
            name: seriesName(j), value: p.values[j], itemStyle: { color: colourOf(j) }, category: `c${i}`,
            tip: tipHtml(`${p.label} · ${seriesName(j)}`, [{ colour: colourOf(j), name: amountName(j), text: valueAt(p, j) }], ofTotal(p.values[j])),
          })).filter((child) => child.value !== null && child.value > 0),
        }
        : { name: p.label, value: p.values[0], itemStyle: { color: colourOf(i) },
          tip: tipHtml(p.label, [{ colour: colourOf(i), name: amountName(0), text: valueAt(p, 0) }], ofTotal(p.values[0])) }
      const option = {
        ...base,
        tooltip: { ...tooltip, trigger: 'item', formatter: (params: unknown) => String((first(params).data as { tip?: string })?.tip ?? '') },
        series: [{
          // ECharts' own zoomToNode only scales the boxes and centres the one clicked (half of it off the chart),
          // so a click drills down here (onClick: treemapRootToNode, as the breadcrumb does)
          type: 'treemap', name: 'All', roam: false, nodeClick: false,
          leafDepth: nested ? 2 : null, // the breadcrumb shows where the chart is ("All"), not the box in the middle
          breadcrumb: nested
            ? { show: true, left: 0, right: 0, bottom: 0, height: 22, emptyItemWidth: 20,
              itemStyle: { color: colours.line, borderColor: colours.line, textStyle: { color: colours.ink, fontSize: 11 } },
              emphasis: { itemStyle: { color: colours.low, textStyle: { color: colours.high } } } }
            : { show: false },
          left: 0, right: 0, top: 0, bottom: nested ? 30 : 0, squareRatio: 0.9,
          // name / amount / % of the shown total; the lines that do not fit are left off, and a box too small
          // for one line shows no label (labelLayout: font size 0), so no cut "Tro" or "Co" is left
          label: { show: true, color: '#fff', fontSize: 11, lineHeight: LABEL_LINE, padding: LABEL_PAD, overflow: 'truncate',
            formatter: (params: { name: string; value: number }) =>
              `${params.name}\n${shortIndian(Number(params.value))}\n${percent(share(Number(params.value)))}` },
          // (the breadcrumb's items have no dataIndex: left alone)
          labelLayout: (params: { dataIndex?: number; rect: { width: number; height: number }; text: string }) =>
            (params.dataIndex == null || labelFits(params.rect, params.text) ? {} : { fontSize: 0 }),
          itemStyle: { borderColor: colours.surface, borderWidth: 1, gapWidth: 2 },
          // nested: the root (no band), the categories (a dark band with the name), the series inside them
          levels: nested
            ? [{ itemStyle: { borderWidth: 0, gapWidth: 3 }, upperLabel: { show: false } },
              { itemStyle: { borderColor: colours.total, borderWidth: 2, gapWidth: 1 },
                upperLabel: { show: true, height: 20, color: '#fff', fontSize: 11, fontWeight: 600, overflow: 'truncate',
                  formatter: (params: { name: string; value: number }) => bandText(params.name, Number(params.value)) } },
              { itemStyle: { borderColor: colours.surface, borderWidth: 1 } }]
            : undefined,
          data: pick.data.map(node).filter((item) => ('children' in item ? item.children.length > 0 : (item.value ?? 0) > 0)),
        }],
      }
      // a click on a category (or a box in it) shows only that category; the breadcrumb's clicks have no data
      const onClick = (params: unknown, chart: EChartsType) => {
        const data = (params as { data?: { id?: string; category?: string } }).data
        const id = data?.category ?? data?.id
        if (id) chart.dispatchAction({ type: 'treemapRootToNode', seriesIndex: 0, targetNodeId: id })
      }
      return { option, height: height + (nested ? 30 : 0), onClick: nested ? onClick : undefined }
    }

    case 'heatmap': {
      // a table of colours: rows = the categories, columns = the series; a missing pair stays empty
      const values = pick.data.flatMap((p) => p.values).filter((v): v is number => v !== null)
      const cells: [number, number, number][] = []
      pick.data.forEach((p, row) => p.values.forEach((v, col) => { if (v !== null) cells.push([col, row, v]) }))
      const labelChars = narrow ? 12 : 22
      // the column names on top: tilted when they do not fit side by side (the tooltip has the full names)
      const rowLabel = Math.min(labelChars, Math.max(...labels.map((l) => l.length))) * LABEL_CHAR
      const perColumn = (boxWidth - rowLabel - 24) / Math.max(s, 1)
      const columnChars = narrow ? 8 : 14
      const columns = pick.ys.map((_, i) => seriesName(i))
      const tilt = Math.min(columnChars, Math.max(...columns.map((y) => y.length))) * LABEL_CHAR + 8 > perColumn
      const option = {
        ...base,
        grid: { left: 8, right: 12, top: 8, bottom: 44, containLabel: true },
        tooltip: {
          ...tooltip, trigger: 'item',
          formatter: (params: unknown) => {
            const [col, row] = (first(params).data as [number, number, number])
            const point = pick.data[row]
            return tipHtml(`${point.label} · ${columns[col]}`, [{ colour: colours.high, name: amountName(col), text: valueAt(point, col) }])
          },
        },
        xAxis: { type: 'category', data: columns, position: 'top', splitArea: { show: false },
          axisLabel: { color: colours.muted, fontSize: 11, interval: 0, rotate: tilt ? 45 : 0, hideOverlap: true,
            formatter: (t: string) => cutText(String(t), tilt ? 12 : columnChars) },
          axisLine: { show: false }, axisTick: { show: false } },
        yAxis: { type: 'category', data: labels, inverse: true,
          axisLabel: { color: colours.muted, fontSize: 11, interval: 0, formatter: (t: string) => cutText(String(t), labelChars) },
          axisLine: { show: false }, axisTick: { show: false } },
        visualMap: {
          type: 'continuous', min: Math.min(0, ...values), max: Math.max(...values, 1), calculable: false,
          orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 12, itemHeight: narrow ? 120 : 180,
          inRange: { color: [colours.low, colours.high] }, textStyle: { color: colours.muted, fontSize: 11 },
          formatter: (v: number) => shortIndian(v),
        },
        series: [{
          type: 'heatmap', data: cells,
          // no label colour: ECharts picks one that reads on the cell
          label: { show: cells.length <= 60, fontSize: 10, formatter: (p: { data: [number, number, number] }) => shortIndian(p.data[2]) },
          itemStyle: { borderColor: colours.surface, borderWidth: 2 },
          emphasis: { itemStyle: { borderColor: colours.ink, borderWidth: 1 } },
        }],
      }
      return { option, height: Math.max(200, n * 30 + 90) }
    }

    case 'scatter': {
      const option = {
        ...base,
        grid: { left: 12, right: 24, top: 18, bottom: 28, containLabel: true },
        tooltip: {
          ...tooltip, trigger: 'item',
          formatter: (params: unknown) => {
            const point = pick.data[(first(params).data as { i: number }).i]
            return tipHtml(point.label, pick.ys.map((_, i) => ({ colour: colourOf(0), name: seriesName(i), text: valueAt(point, i) })))
          },
        },
        xAxis: valueAxis({ name: seriesName(0), nameLocation: 'middle', nameGap: 26, nameTextStyle: { color: colours.ink, fontSize: 11 }, scale: true }),
        yAxis: valueAxis({ name: seriesName(1), nameTextStyle: { color: colours.ink, fontSize: 11, align: 'left' }, scale: true }),
        series: [{
          type: 'scatter', symbolSize: 10, itemStyle: { opacity: 0.8 },
          data: pick.data.flatMap((p, i) => (p.values[0] !== null && p.values[1] !== null ? [{ name: p.label, value: [p.values[0], p.values[1]], i }] : [])),
        }],
      }
      return { option, height: narrow ? 280 : 320 }
    }

    case 'funnel': {
      const option = {
        ...base,
        tooltip: {
          ...tooltip, trigger: 'item',
          formatter: (params: unknown) => {
            const { dataIndex } = first(params)
            const point = pick.data[dataIndex]
            return tipHtml(point.label, [{ colour: colourOf(dataIndex), name: amountName(0), text: valueAt(point, 0) }])
          },
        },
        series: [{
          type: 'funnel', sort: 'descending', gap: 2, left: '4%', top: 8, bottom: 8, width: narrow ? '48%' : '58%',
          minSize: '8%', label: { show: true, position: 'right', color: colours.ink, fontSize: 11,
            formatter: (p: { name: string; value: number }) => `${cutText(p.name, narrow ? 14 : 24)}  ${shortIndian(p.value)}` },
          labelLine: { lineStyle: { color: colours.muted } },
          itemStyle: { borderColor: colours.surface, borderWidth: 1 },
          data: pick.data.map((p) => ({ name: p.label, value: p.values[0] })),
        }],
      }
      return { option, height: Math.max(240, n * 34 + 40) }
    }

    case 'radar': {
      const top = Math.max(...pick.data.flatMap((p) => p.values.map((v) => v ?? 0)), 1)
      const option = {
        ...base,
        tooltip: {
          ...tooltip, trigger: 'item',
          formatter: (params: unknown) => {
            const j = first(params).dataIndex
            return tipHtml(seriesName(j), pick.data.map((p) => ({ colour: colourOf(j), name: p.label, text: valueAt(p, j) })))
          },
        },
        radar: {
          indicator: pick.data.map((p) => ({ name: cutText(p.label, narrow ? 10 : 16), max: top * 1.05 })),
          radius: narrow ? '55%' : '65%', center: ['50%', legend ? '46%' : '50%'],
          axisName: { color: colours.muted, fontSize: 11 },
          splitLine: { lineStyle: { color: colours.line } }, splitArea: { show: false },
          axisLine: { lineStyle: { color: colours.line } },
        },
        series: [{
          type: 'radar', symbolSize: 4,
          data: pick.ys.map((_, j) => ({ name: seriesName(j), value: pick.data.map((p) => p.values[j] ?? 0), areaStyle: { opacity: 0.12 } })),
        }],
      }
      return { option, height: (narrow ? 300 : 340) + legendSpace }
    }
  }
}

/** The colours of a saved PNG: a white page with dark text in the light theme (as always); in the dark theme
 *  the dark card with its light text, because the chart itself is drawn with light text there. */
export type Paper = { background: string; ink: string; muted: string }
export function pngPaper(colours?: Colours): Paper {
  return colours?.dark ? { background: colours.surface, ink: colours.ink, muted: colours.muted }
    : { background: '#fff', ink: '#212529', muted: '#6C757D' }
}

/** Saves the chart as a PNG (ECharts draws it at twice the size, on white - on the dark card in the dark theme),
 *  with the title on top and the subtitle (the hidden group) under it. colours = the ones the chart is drawn with. */
export async function downloadPng(chart: EChartsType, fileName: string, title: string, subtitle = '', colours?: Colours): Promise<void> {
  const paper = pngPaper(colours)
  return downloadImage(chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: paper.background }), fileName, title, subtitle, paper)
}

/** Saves a PNG (a data URL, drawn at twice the size) with the title and subtitle on top - the 3D graph uses it too. */
export async function downloadImage(url: string, fileName: string, title: string, subtitle = '', paper: Paper = pngPaper()): Promise<void> {
  const png = title || subtitle ? await withTitle(url, title, subtitle, paper) : url
  const link = document.createElement('a')
  link.href = png
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  link.remove()
}

async function withTitle(url: string, title: string, subtitle: string, paper: Paper): Promise<string> {
  const image = new Image()
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve()
    image.onerror = () => reject(new Error('the chart could not be drawn'))
    image.src = url
  })
  const scale = 2
  const pad = 16 * scale
  const titleHeight = ([title, subtitle].filter(Boolean).length * 22 + 8) * scale
  const canvas = document.createElement('canvas')
  canvas.width = image.width + pad * 2
  canvas.height = image.height + titleHeight + pad * 2
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('no canvas')
  ctx.fillStyle = paper.background
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = paper.ink
  ctx.textBaseline = 'middle'
  if (title) {
    ctx.font = `600 ${14 * scale}px ${FONT}`
    ctx.fillText(cutText(title, 90), pad, pad + 10 * scale)
  }
  if (subtitle) {
    ctx.fillStyle = paper.muted
    ctx.font = `${12 * scale}px ${FONT}`
    ctx.fillText(cutText(subtitle, 110), pad, pad + (title ? 32 : 10) * scale)
  }
  ctx.drawImage(image, pad, pad + titleHeight)
  return canvas.toDataURL('image/png')
}

/** A file name from the title: 'Net sales by month' -> 'Net_sales_by_month.png'. */
export function pngName(text: string): string {
  return `${text.replace(/[^\w-]+/g, '_').slice(0, 60) || 'chart'}.png`
}
