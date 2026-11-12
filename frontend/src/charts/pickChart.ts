// Decides from the answer rows (as the table shows them) whether a chart helps and which one:
// a line for a time series, a donut for a few parts of a whole, stacked bars for 2 labels + an amount
// (the rows are pivoted), bars for names + amounts - or the kind the question asks for when it fits.
// Pure (no React, no ECharts): the rows are display strings, so the numbers are parsed back here. 0 AI tokens.
import type { Cell, Header } from '../types'

export type ChartKind =
  | 'line' | 'area' | 'stackedArea'
  | 'bar' | 'hbar' | 'stacked' | 'grouped'
  | 'pie' | 'treemap' | 'heatmap' | 'scatter' | 'funnel' | 'radar' | 'waterfall'

/** The names on the chart-type buttons / menu. */
export const KIND_NAMES: Record<ChartKind, string> = {
  line: 'Line', area: 'Area', stackedArea: 'Stacked area', bar: 'Bar', hbar: 'Horizontal bar',
  stacked: 'Stacked bar', grouped: 'Grouped bar', pie: 'Donut', treemap: 'Treemap', heatmap: 'Heatmap',
  scatter: 'Scatter', funnel: 'Funnel', radar: 'Radar', waterfall: 'Waterfall',
}
// the end of the note when the asked kind does not fit: "... - showing bars."
const SHOWING: Record<ChartKind, string> = {
  line: 'a line', area: 'an area chart', stackedArea: 'a stacked area', bar: 'bars', hbar: 'bars',
  stacked: 'stacked bars', grouped: 'grouped bars', pie: 'a donut', treemap: 'a treemap', heatmap: 'a heatmap',
  scatter: 'a scatter chart', funnel: 'a funnel', radar: 'a radar', waterfall: 'a waterfall',
}
// the order of the buttons / menu (the best kind for the rows always comes first)
const ORDER: ChartKind[] = ['line', 'area', 'stackedArea', 'bar', 'hbar', 'stacked', 'grouped', 'pie', 'treemap',
  'heatmap', 'scatter', 'funnel', 'radar', 'waterfall']

export interface ChartPoint {
  label: string
  values: (number | null)[] // one per series (null = no value, '-', or a pair the rows do not have)
  texts: string[] // the same values as the table shows them (for the tooltip)
}

/** A group that only holds what has no real name ("Not classified", "Unknown", "Others" ...). */
export interface CatchAll {
  label: string // as in the rows ('' for a blank)
  name: string // as the notes write it ('(blank)' for a blank)
  total: number // its amount: the first amount, or every series after a pivot (absolute values)
  share: number // its % of the total of all the groups (0-100)
  hidden: boolean // left out of the chart now (the table and the answer always keep it)
}

export interface ChartPick {
  kind: ChartKind
  x: string // the label column (the categories)
  ys: string[] // the series: the number columns drawn, or after a pivot the values of the second label
  amount: string // the amount drawn: ys joined, or after a pivot its one amount column
  group: string // after a pivot: the second label column (the series); '' otherwise
  data: ChartPoint[] // the categories drawn (scatter: values = [x amount, y amount])
  horizontal: boolean // bars run left to right (long labels, many bars, or a horizontal bar asked for)
  time: boolean // the label is a time (months, dates, years ...): kept in its order
  note: string // e.g. 'top 25 of 40' when only the first bars are drawn
  seriesNote: string // e.g. 'top 10 of 14 customer_name values' when a pivot has too many series
  fallback: string // why the asked kind is not drawn, e.g. 'A funnel needs ... - showing bars'
  options: ChartKind[] // every kind these rows can be drawn as (the chart-type buttons / menu)
  catchAll: CatchAll | null // a catch-all group of the label (the "Hide / Show" button), else null
}

// the chart a question asks for in words. "line" alone is not enough (invoice lines, order lines): it needs
// chart / graph / plot / trend; "area" alone is a place (sales by area); "grouped" alone is "grouped by".
// The more exact wishes come first ("stacked area" before "stacked", "horizontal bar" before "bar").
const WANTS: [ChartKind, RegExp][] = [
  ['waterfall', /\bwaterfall\b|\bbridge\s*(chart|graph)\b/i],
  ['funnel', /\bfunnel\b/i],
  ['radar', /\bradar\b|\b(spider|web|star)\s*(chart|graph|plot|diagram)s?\b/i],
  ['treemap', /\btree\s*-?\s*maps?\b/i],
  ['heatmap', /\bheat\s*-?\s*maps?\b|\bheat\s*(chart|grid|table)s?\b/i],
  ['scatter', /\bscatter(\s*(chart|graph|plot|diagram))?s?\b|\bx\s*-?\s*y\s*(chart|graph|plot)s?\b/i],
  ['stackedArea', /\bstacked\s*area\b/i],
  ['area', /\barea\s*(chart|graph|plot|diagram)s?\b/i],
  ['stacked', /\bstacked\b/i],
  ['grouped', /\b(grouped|clustered|side[\s-]*by[\s-]*side)\s*(bar|column)s?\b|\b(grouped|clustered)\s*(chart|graph)s?\b/i],
  ['hbar', /\bhorizontal\s*(bar|column)s?\b|\bhorizontal\s*(chart|graph)s?\b|\bsideways\s*bars?\b/i],
  ['pie', /\b(pie|donut|doughnut)s?\b/i],
  ['bar', /\b(bar|column)s?\s*(chart|graph|plot|diagram)s?\b|\bbars\b|\bbar\s+(view|form)\b/i],
  ['line', /\b(line|trend)\s*(chart|graph|plot|diagram)s?\b|\btrend\s*line\b|\bmulti[\s-]*lines?\b/i],
]

/** The chart kind the question asks for in words, or null when it names none (then pickChart chooses). */
export function chartKindFromText(text: string): ChartKind | null {
  return WANTS.find(([, words]) => words.test(text ?? ''))?.[0] ?? null
}

// any chart wish in words - a kind ("bar chart", "pie") or just "chart" / "graph" / "plot": when the rows fit
// no chart, the answer card says why there is none (05-Nov: a line chart of 1 row was silently not drawn)
const ANY_CHART = /\b(chart|graph|plot|diagram|visuali[sz]\w*)s?\b/i

/** True when the question asks for a chart in words (any kind, or just "chart" / "graph" / "plot"). */
export function chartAskedFromText(text: string): boolean {
  return ANY_CHART.test(text ?? '') || chartKindFromText(text) !== null
}

// charts the app does not draw itself: the "Make this chart with AI" button (layer 2, uses AI tokens)
const UNUSUAL: [string, RegExp][] = [
  ['sankey diagram', /\bsankey\b|\bflow\s*diagram\b/i],
  ['sunburst chart', /\bsun\s*-?\s*burst\b/i],
  ['box plot', /\bbox\s*-?\s*(plot|chart|and\s*whiskers?)\b|\bwhiskers?\b/i],
  // a gauge / bubble / rose alone may be a product or a verb (pressure gauges, sales rose): a chart word too
  ['gauge', /\bgauge\s*(chart|graph|meter|dial)s?\b|\b(as|in|on)\s+a\s+gauge\b|\bspeedometer\b|\bdial\s*(chart|graph)\b/i],
  ['bubble chart', /\bbubble\s*(chart|graph|plot|diagram)s?\b|\bbubbles?\s+(by|for|of|per)\b|\bas\s+bubbles?\b/i],
  ['candlestick chart', /\bcandle\s*-?\s*sticks?\b|\bohlc\b/i],
  ['chart with a target line', /\b(target|goal|budget|benchmark|reference)\s*lines?\b|\b(vs\.?|versus|against)\s+(the\s+)?(target|goal|budget)\b/i],
  ['bar and line combo chart', /\bcombo\s*(chart|graph)s?\b|\bcombination\s*(chart|graph)s?\b|\b(dual|two|secondary)\s*(y[\s-]*)?ax[ie]s\b|\bbars?\s*(and|with|\+)\s*(a\s+)?lines?\b|\blines?\s*(and|with|\+)\s*bars?\b|\bpareto\b/i],
  ['histogram', /\bhistograms?\b/i],
  ['rose (polar) chart', /\bnightingale\b|\b(rose|polar)\s*(chart|graph|diagram|plot)s?\b/i],
  ['100% stacked bar', /\b100\s*%\s*stacked\b|\b(percent|percentage)\s*stacked\b/i],
  ['pictorial bar chart', /\bpictorial\b/i],
  ['network graph', /\bnetwork\s*(graph|chart|diagram)\b/i],
  ['tree diagram', /\btree\s*(diagram|chart|graph)\b|\bhierarchy\s*(diagram|chart)\b/i],
]

/** The chart the question asks for that the app cannot draw itself (a sankey, a gauge, a bar with a
 *  target line ...) - its name for the AI, or null. A built-in kind may be named too ("bar with a target
 *  line" is drawn as bars, with the AI button for the target line). */
export function unusualChartFromText(text: string): string | null {
  return UNUSUAL.find(([, words]) => words.test(text ?? ''))?.[0] ?? null
}

export const MAX_LINE_POINTS = 60
export const MAX_BARS = 25 // also the most categories of a treemap, a heatmap or a waterfall
const MAX_SERIES = 3 // number columns drawn together
const MAX_PIVOT_SERIES = 10 // values of the second label (the series of a pivot)
const MAX_PARTS = 12 // a donut, a funnel, a radar
export const HIDE_SHARE = 70 // a catch-all group holding more than this % of the total is hidden at first
export const UNEVEN_SHARE = 80 // one group holding more than this %: bars (sorted) instead of a donut

// columns that only explain the dates of the answer: never drawn
const HELPER = /(^|_)(data_from|data_to|period_start|period_end|as_of_date|matches)$/i
// numbers that are names or places in a list, not amounts (like agent.py's _PLAIN_INT and _NOT_AN_AMOUNT)
const PLAIN_INT = /(^id$|_id$|_no$|number$|code$|year$|^year)/i
const NOT_AN_AMOUNT = /(quarter|period|month|day|week|rank)$/i
// the amounts people ask about: money first, then quantities, counts and percentages
const MONEY = /(_inr|_jpy|_usd|value|sales|amount|revenue|total)/i
const MEASURE = /(qty|quantity|count|pct|percent)/i
// a label that names a kind of thing, so its rows can be parts of a whole
const CATEGORY = /(^|_)(type|category|segment|group|class|status|kind|mode|channel|region|zone|division|market|country|source)s?$/i
// numbers that do not add up to a whole (an average of the parts is not a part)
const NOT_ADDITIVE = /(avg|average|mean|rate|price|growth|change|margin|pct|percent|share|ratio)/i
// a number label that is a time (year 2026, quarter 1, month 3, nop_sales_period_no 7)
const TIME_NAME = /(year|quarter|month|period|week|day|date|fy)(_no|_number)?$/i

const MONTH = '(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?)'
const FY = "(fy\\s*'?)?\\d{2,4}([-/]\\d{2,4})?"
const TIME_VALUE = [
  new RegExp(`^${MONTH}([\\s\\-'/]+\\d{2,4})?$`, 'i'), // Jan 2026, Sep-26, January
  new RegExp(`^\\d{1,2}[-/ ]${MONTH}[-/ ]\\d{2,4}( \\d{1,2}:\\d{2})?$`, 'i'), // 21-Dec-2025
  /^\d{4}-\d{2}(-\d{2})?([ T]\d{1,2}:\d{2}.*)?$/, // 2026-01-31, 2025-26
  /^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$/, // 31/01/2026
  /^fy\s*'?\d{2,4}([-/]\d{2,4})?$/i, // FY 2025-26, FY26
  new RegExp(`^(q[1-4]|h[12])([\\s\\-]+${FY})?$`, 'i'), // Q1, Q1 FY 2026-27
  new RegExp(`^${FY}[\\s\\-]+(q[1-4]|h[12])$`, 'i'), // FY 2026-27 Q1
  /^(p|period|week|wk|w)\s*-?\s*\d{1,2}(\b.*)?$/i, // P7, Week 12
]

// a group with no real name: "Not classified", "Not given", "Unknown", "Unassigned", "Others", "N/A", "-", a
// blank - the whole label only, so "Unknown Hydraulics Ltd" or "Other Machines Pvt Ltd" are real names
const CATCH_ALL = /^[([<]?\s*(not[\s_-]*(classified|given|specified|assigned|available)|un(known|assigned|classified|specified|categori[sz]ed)|others?|n\s*\/\s*a|none|null|blank|-+|–|—)?\s*[)\]>]?$/i

/** True for a label that only collects what has no real name ("Not classified", "Unknown", "Others", "-"). */
export function isCatchAll(label: string): boolean {
  return CATCH_ALL.test((label ?? '').trim())
}

/** '1,234.50' -> 1234.5, '-12.5%' -> -12.5, '(300)' -> -300; '-' or text -> null. */
export function parseNumber(text: string): number | null {
  const t = text.replace(/[,\s%₹$¥]/g, '')
  if (t === '' || t === '-' || t === '–' || t === '—') return null
  const negative = /^\(.+\)$/.test(t) // accounting style
  const core = negative ? t.slice(1, -1) : t
  if (!/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(core)) return null
  const n = Number(core)
  return Number.isFinite(n) ? (negative ? -n : n) : null
}

function isYear(n: number): boolean {
  return Number.isInteger(n) && n >= 1990 && n <= 2100
}

/** 2526 = FY 2025-26 (the last two digits follow the first two). */
function isFyCode(text: string): boolean {
  const m = /^(\d{2})(\d{2})$/.exec(text.trim())
  return !!m && (Number(m[1]) + 1) % 100 === Number(m[2])
}

function isTimeText(text: string): boolean {
  const t = text.trim()
  if (/^\d{4}$/.test(t)) return isYear(Number(t)) || isFyCode(t)
  return TIME_VALUE.some((pattern) => pattern.test(t))
}

/** The values that are there ('-' and blanks left out). */
const filled = (texts: string[]) => texts.filter((t) => t.trim() !== '' && t.trim() !== '-')

/** A number column of years (2025, 2026 ...): a label, never an amount. */
function isYearColumn(texts: string[]): boolean {
  const numbers = texts.map(parseNumber).filter((n): n is number => n !== null)
  return numbers.length > 0 && numbers.every(isYear) && texts.every((t) => !t.includes('.'))
}

function isTimeColumn(name: string, num: boolean, texts: string[]): boolean {
  const values = filled(texts)
  if (values.length === 0) return false
  if (num) return TIME_NAME.test(name) || isYearColumn(values)
  return values.every(isTimeText)
}

/** The kind of number, so only like with like shares one axis (rupees with rupees, counts with counts). */
function unit(name: string): string {
  const currency = /inr/i.test(name) ? 'inr' : /jpy/i.test(name) ? 'jpy' : /usd/i.test(name) ? 'usd' : ''
  if (/(pct|percent|share|margin|ratio|rate)/i.test(name)) return 'pct'
  if (/(qty|quantity)/i.test(name)) return 'qty' + currency
  if (/(count|^no_of|^num_)/i.test(name)) return 'count'
  return 'amount' + currency
}

function isSortedDown(values: (number | null)[]): boolean {
  const numbers = values.filter((v): v is number => v !== null)
  return numbers.every((v, i) => i === 0 || v <= numbers[i - 1])
}

/** The sum of a category's values (a pivot row's total, for "top 25" and the series order). */
const sum = (values: (number | null)[]) => values.reduce<number>((total, v) => total + (v ?? 0), 0)

type Col = { i: number; name: string; num: boolean; texts: string[] }

/** The rows as categories x series, before a kind is chosen. */
interface Table {
  x: string
  ys: string[]
  amount: string
  group: string
  points: ChartPoint[]
  pivot: boolean
  time: boolean
  additive: boolean // the amounts add up to a whole (not an average, a rate or a %)
  partsOfWhole: boolean // a few categories of one amount: the donut is the best chart
  seriesNote: string
  scatter: { ys: [string, string]; points: ChartPoint[]; best: boolean } | null // two amounts of each row
}

/** The rows read as a table of categories x series: one label with a different value on every row, else two
 *  labels whose pairs are all different (pivoted: rows = the first label, series = the second). null = no chart. */
function readTable(headers: Header[], rows: Cell[][]): Table | null {
  if (rows.length < 2 || headers.length < 2) return null
  const column = (i: number) => rows.map((row) => row[i]?.text ?? '')
  const cols: Col[] = headers
    .map((h, i) => ({ i, name: h.name, num: h.num, texts: column(i) }))
    .filter((c) => !HELPER.test(c.name) && filled(c.texts).length > 0)

  const idLike = (c: Col) => PLAIN_INT.test(c.name) || NOT_AN_AMOUNT.test(c.name) || isYearColumn(filled(c.texts))
  const amounts = cols.filter((c) => c.num && !idLike(c) && c.texts.some((t) => parseNumber(t) !== null))
  if (amounts.length === 0) return null
  const rank = (c: Col) => (MONEY.test(c.name) ? 2 : MEASURE.test(c.name) ? 1 : 0)
  const ranked = [...amounts].sort((a, b) => rank(b) - rank(a))
  const isTime = (c: Col) => isTimeColumn(c.name, c.num, c.texts)

  // the label: a text column with a different value on every row (names before codes), else a
  // number label such as the year
  const unique = (c: Col) => new Set(c.texts.map((t) => t.trim())).size === c.texts.length
  const texts = cols.filter((c) => !c.num)
  const label =
    texts.find((c) => !PLAIN_INT.test(c.name) && unique(c)) ??
    texts.find(unique) ??
    cols.find((c) => c.num && idLike(c) && unique(c))

  if (label) {
    // the y columns: amounts first, then only the ones of the same kind as the first (one axis), max 3
    const first = unit(ranked[0].name)
    const ys = ranked.filter((c) => unit(c.name) === first).slice(0, MAX_SERIES)
    const points: ChartPoint[] = rows.map((row, r) => ({
      label: label.texts[r].trim(),
      values: ys.map((c) => parseNumber(row[c.i]?.text ?? '')),
      texts: ys.map((c) => row[c.i]?.text ?? ''),
    }))
    const additive = ys.every((c) => !NOT_ADDITIVE.test(c.name))
    const time = isTime(label)
    const positive = points.every((p) => p.values[0] !== null && p.values[0] > 0)
    // two amounts of different kinds (value and quantity ...): one dot per row
    const other = ranked.find((c) => unit(c.name) !== first)
    const pair = other ? [ranked[0], other] : null
    const scatter = pair && {
      ys: [pair[0].name, pair[1].name] as [string, string],
      points: rows.map((row, r) => ({
        label: label.texts[r].trim(),
        values: pair.map((c) => parseNumber(row[c.i]?.text ?? '')),
        texts: pair.map((c) => row[c.i]?.text ?? ''),
      })),
      // the best chart only for exactly two amounts over 5+ rows that are not a ranking (a top-10 list reads
      // better as bars)
      best: amounts.length === 2 && rows.length >= 5 && !time &&
        pair.every((c) => !isSortedDown(c.texts.map(parseNumber))),
    }
    return {
      x: label.name, ys: ys.map((c) => c.name), amount: ys.map((c) => c.name).join(', '), group: '',
      points, pivot: false, time, additive, seriesNote: '', scatter,
      partsOfWhole: points.length <= 6 && amounts.length === 1 && CATEGORY.test(label.name) && additive && positive,
    }
  }

  // two labels + an amount (month x customer, product_category x sale_type): pivot them. The labels: text
  // columns and number labels (year, quarter), names before codes; every pair must be on one row only.
  const labels = cols.filter((c) => !c.num || idLike(c))
  const distinct = (c: Col) => new Set(c.texts.map((t) => t.trim())).size
  const pairs: [Col, Col][] = []
  for (const named of [true, false]) {
    for (let a = 0; a < labels.length; a++) {
      for (let b = a + 1; b < labels.length; b++) {
        const [one, two] = [labels[a], labels[b]]
        if (named && (PLAIN_INT.test(one.name) || PLAIN_INT.test(two.name))) continue
        if (distinct(one) < 2 || distinct(two) < 2) continue
        const keys = new Set(rows.map((_, r) => `${one.texts[r].trim()}\u0000${two.texts[r].trim()}`))
        if (keys.size === rows.length) pairs.push([one, two])
      }
    }
  }
  if (pairs.length === 0) return null
  let [rowsBy, seriesBy] = pairs[0]
  // a time runs along the axis; and the label with fewer values makes the series (when the other has too many)
  if (isTime(seriesBy) && !isTime(rowsBy)) [rowsBy, seriesBy] = [seriesBy, rowsBy]
  else if (!isTime(rowsBy) && distinct(seriesBy) > MAX_PIVOT_SERIES && distinct(rowsBy) <= MAX_PIVOT_SERIES) {
    [rowsBy, seriesBy] = [seriesBy, rowsBy]
  }
  const amount = ranked[0]
  const categories: string[] = []
  let names: string[] = []
  const cells = new Map<string, string>()
  rows.forEach((row, r) => {
    const [category, name] = [rowsBy.texts[r].trim(), seriesBy.texts[r].trim()]
    if (!categories.includes(category)) categories.push(category)
    if (!names.includes(name)) names.push(name)
    cells.set(`${category}\u0000${name}`, row[amount.i]?.text ?? '')
  })
  // too many series: the biggest ones (by their total) are drawn
  let seriesNote = ''
  if (names.length > MAX_PIVOT_SERIES) {
    const totals = new Map(names.map((name) => [name, sum(categories.map((c) => parseNumber(cells.get(`${c}\u0000${name}`) ?? '')))]))
    const kept = new Set([...names].sort((a, b) => Math.abs(totals.get(b) ?? 0) - Math.abs(totals.get(a) ?? 0)).slice(0, MAX_PIVOT_SERIES))
    seriesNote = `top ${MAX_PIVOT_SERIES} of ${names.length} ${seriesBy.name} values`
    names = names.filter((name) => kept.has(name))
  }
  const points: ChartPoint[] = categories.map((category) => {
    const texts = names.map((name) => cells.get(`${category}\u0000${name}`) ?? '-') // a missing pair stays empty
    return { label: category, values: texts.map(parseNumber), texts }
  })
  return {
    x: rowsBy.name, ys: names, amount: amount.name, group: seriesBy.name, points, pivot: true,
    time: isTime(rowsBy), additive: !NOT_ADDITIVE.test(amount.name), partsOfWhole: false, seriesNote, scatter: null,
  }
}

const BAR_LIKE: ChartKind[] = ['bar', 'hbar', 'stacked', 'grouped']

/** '' when the rows can be drawn as this kind, else the short reason (the start of the fallback note). */
function misfit(kind: ChartKind, t: Table): string {
  const n = t.points.length
  const s = t.ys.length
  const values = t.points.flatMap((p) => p.values).filter((v): v is number => v !== null)
  const positive = values.length > 0 && values.every((v) => v > 0)
  const firstPositive = t.points.every((p) => p.values[0] !== null && p.values[0] > 0)
  const noNegative = values.every((v) => v >= 0)
  switch (kind) {
    case 'line': case 'area':
      return n <= MAX_LINE_POINTS ? '' : `A ${kind} chart needs at most ${MAX_LINE_POINTS} points`
    case 'stackedArea':
      return s >= 2 && t.additive && noNegative && n <= MAX_LINE_POINTS ? ''
        : 'A stacked area needs two labels or several amounts that add up'
    case 'bar': case 'hbar':
      return ''
    case 'stacked':
      return s >= 2 && t.additive ? '' : 'Stacked bars need two labels or several amounts that add up'
    case 'grouped':
      return s >= 2 ? '' : 'Grouped bars need two labels or several amounts'
    case 'pie':
      return s === 1 && n <= MAX_PARTS && firstPositive && t.additive ? ''
        : `A donut needs up to ${MAX_PARTS} positive parts of one amount`
    case 'treemap':
      return t.additive && positive ? '' : 'A treemap needs positive amounts that add up'
    case 'heatmap':
      return s >= 2 ? '' : 'A heatmap needs two labels (or several amounts)'
    case 'scatter':
      return t.scatter ? '' : 'A scatter chart needs two amount columns of different kinds'
    case 'funnel':
      return s === 1 && n <= MAX_PARTS && firstPositive ? ''
        : `A funnel needs one positive amount per step (up to ${MAX_PARTS} steps)`
    case 'radar':
      return n >= 3 && n <= MAX_PARTS && noNegative ? '' : `A radar needs 3 to ${MAX_PARTS} labels and no negative values`
    case 'waterfall': {
      if (s !== 1 || !t.additive || n > MAX_BARS) return `A waterfall needs one amount per step (up to ${MAX_BARS} steps)`
      let running = 0
      for (const p of t.points) {
        running += p.values[0] ?? 0
        if (running < 0) return 'A waterfall needs a running total that stays above zero'
      }
      return ''
    }
  }
}

/** The best kind for the rows: a line for a time, a donut for a few parts of a whole, stacked bars for a pivot,
 *  a scatter for two kinds of amounts, else bars. */
function bestKind(t: Table): ChartKind {
  if (t.time && t.points.length <= MAX_LINE_POINTS) return 'line'
  if (t.pivot) return t.additive ? 'stacked' : 'grouped'
  if (t.partsOfWhole) return 'pie'
  if (t.scatter?.best) return 'scatter'
  return t.ys.length > 1 ? 'grouped' : 'bar'
}

/** Words that mean the same chart for these rows: "bar chart" of several series = their best bars. */
function alias(want: ChartKind, t: Table): ChartKind {
  if (t.ys.length > 1 && (want === 'bar' || want === 'hbar')) return t.pivot && t.additive ? 'stacked' : 'grouped'
  return want
}

/** The size of a group: its first amount, or every series after a pivot (absolute values). */
const size = (t: Table, p: ChartPoint) =>
  (t.pivot ? p.values : p.values.slice(0, 1)).reduce<number>((total, v) => total + Math.abs(v ?? 0), 0)

/** The biggest catch-all group of the label (3 groups or more, not a time), hidden when it holds more than
 *  HIDE_SHARE % of the total - or as the user's button says (hide = true / false). */
function findCatchAll(t: Table, hide: boolean | null): CatchAll | null {
  if (t.time || t.points.length < 3) return null
  const total = sum(t.points.map((p) => size(t, p)))
  const found = t.points.filter((p) => isCatchAll(p.label)).sort((a, b) => size(t, b) - size(t, a))[0]
  if (!found || !(total > 0)) return null
  const share = (size(t, found) / total) * 100
  return { label: found.label, name: found.label || '(blank)', total: size(t, found), share, hidden: hide ?? share > HIDE_SHARE }
}

/** The % of the total the biggest group holds (0 when nothing adds up). */
function topShare(t: Table): number {
  const sizes = t.points.map((p) => size(t, p))
  const total = sum(sizes)
  return total > 0 ? (Math.max(...sizes) / total) * 100 : 0
}

/** The chart for these rows, or null when a chart would not help (one row, no amounts, ids only ...).
 *  want = the kind the user asked for (words in the question, or a button): used when the rows can be drawn
 *  that way, else the best kind for the rows with a short note why. hide = the "Hide / Show" button for a
 *  catch-all group (null: hidden when it holds more than 70% of the total). Hiding changes only the chart. */
export function pickChart(headers: Header[], rows: Cell[][], want: ChartKind | null = null,
  hide: boolean | null = null): ChartPick | null {
  const all = readTable(headers, rows)
  if (!all) return null
  if (all.time && all.points.length > MAX_LINE_POINTS) return null // too many points for any chart

  // a waterfall keeps every step (its total would be wrong without one)
  const catchAll = want === 'waterfall' ? null : findCatchAll(all, hide)
  const gone = catchAll?.hidden ? catchAll.label : null
  const kept = all.points.filter((p) => p.label !== gone)
  // after a pivot, a series only the hidden group had (Service of "Not classified") goes too
  const series = all.ys.map((_, j) => j).filter((j) => !all.pivot || kept.some((p) => p.values[j] !== null))
  const t: Table = gone === null ? all : {
    ...all,
    ys: series.map((j) => all.ys[j]),
    points: kept.map((p) => ({ ...p, values: series.map((j) => p.values[j]), texts: series.map((j) => p.texts[j]) })),
    scatter: all.scatter && { ...all.scatter, points: all.scatter.points.filter((p) => p.label !== gone) },
  }

  // very uneven groups (one holds more than 80%): bars, biggest first, read better than a donut - unless asked
  const uneven = want === null && !t.time && topShare(t) > UNEVEN_SHARE
  const best = uneven && bestKind(t) === 'pie' ? 'bar' : bestKind(t)
  const longest = (points: ChartPoint[]) => Math.max(...points.map((p) => p.label.length))
  // bars run left to right for long names or many bars; months stay upright, in their order
  const autoHorizontal = !t.time && (longest(t.points.slice(0, MAX_BARS)) > 12 || Math.min(t.points.length, MAX_BARS) > 12)

  // every kind these rows fit, the best first; one "Bar" button only (a horizontal one when bars stand upright)
  const options = [best, ...ORDER.filter((k) => k !== best)].filter((k) => !misfit(k, t))
    .filter((k) => !(t.ys.length > 1 && (k === 'bar' || k === 'hbar')) && !(k === 'hbar' && autoHorizontal))

  const asked = want && alias(want, t)
  const reason = asked ? misfit(asked, t) : ''
  let kind = asked && !reason ? asked : best
  if (kind === 'hbar' && autoHorizontal) kind = 'bar' // the same bars
  const fallback = reason ? `${reason} - showing ${SHOWING[best]}.` : ''

  const total = (p: ChartPoint) => (t.pivot ? sum(p.values) : p.values[0])
  const sorted = uneven && BAR_LIKE.includes(kind)
    ? [...t.points].sort((a, b) => (total(b) ?? 0) - (total(a) ?? 0)) : t.points
  // categories drawn: the first 25 of bars, a treemap, a heatmap (lines, donuts, funnels and radars fit already)
  const cutKinds: ChartKind[] = [...BAR_LIKE, 'treemap', 'heatmap']
  const cut = cutKinds.includes(kind) && sorted.length > MAX_BARS
  const data = kind === 'scatter' && t.scatter ? t.scatter.points : cut ? sorted.slice(0, MAX_BARS) : sorted
  const note = cut ? `${isSortedDown(sorted.map(total)) ? 'top' : 'first'} ${MAX_BARS} of ${all.points.length}` : ''
  const single = kind === 'pie' || kind === 'funnel' || kind === 'waterfall'
  const ys = kind === 'scatter' && t.scatter ? [...t.scatter.ys] : single ? t.ys.slice(0, 1) : t.ys
  const points = single ? data.map((p) => ({ ...p, values: p.values.slice(0, 1), texts: p.texts.slice(0, 1) })) : data
  return {
    kind, x: t.x, ys, amount: kind === 'scatter' ? ys.join(' and ') : single ? ys[0] : t.amount, group: t.group,
    data: points, time: t.time, note, seriesNote: kind === 'scatter' ? '' : t.seriesNote, fallback, options, catchAll,
    horizontal: kind === 'hbar' || (BAR_LIKE.includes(kind) && autoHorizontal) || (want === 'hbar' && BAR_LIKE.includes(kind)),
  }
}

/** Indian short numbers for the axis: 1.2 Cr, 35 L, 12 K, 950. */
export function shortIndian(n: number): string {
  const abs = Math.abs(n)
  const [size, unitName] = abs >= 1e7 ? [1e7, ' Cr'] : abs >= 1e5 ? [1e5, ' L'] : abs >= 1e3 ? [1e3, ' K'] : [1, '']
  const scaled = n / size
  const places = Math.abs(scaled) >= 100 || Number.isInteger(scaled) ? 0 : Math.abs(scaled) >= 10 ? 1 : size === 1 ? 2 : 1
  const text = scaled.toLocaleString('en-IN', { maximumFractionDigits: places })
  return text + unitName
}
