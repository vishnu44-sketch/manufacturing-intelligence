// ML Dashboard (/ml-dashboard, every user): what the 6 machine-learning models found in the sales data. The models
// run on the server (run_ml, after each data load) and save their results; the cards only read them (one read-only
// call, /api/insights, no AI call). 18-Nov: the cards moved here from ML Insights, which keeps only the ML chat.
// At the top: which data the estimates are made from and when they ran; then the cards, each with a small
// "Ask about this" button - it opens ML Insights and asks the card's question there as a new ML chat
// (/insights?new=1&ask=<question>):
// 1. Sales forecast - the last 12 sales months and the next 3 (a dashed line over a soft low-high band), the 3
//    forecast numbers in INR Cr with their range, the model's error on the last 6 months, and the top-10 product
//    forecasts (a table that opens on a click);
// 2. Customers at risk - how many High / Medium / Low, and the customers most likely to stop buying;
// 3. Customer groups - a donut of the customers in each group, and a short line per group;
// 4. Unusual invoices - how many of each kind, and the invoices with a price, quantity or credit note far from usual;
// 5. Bought together - product pairs that are often on the same order;
// 6. Stock running out - how many items in each state, and the items that run out first.
// Before the models have run (ready: false) a calm note says so; a failed call shows the usual red box.
// Drawn with Tailwind + shadcn/ui in the theme's colour names only (bg-card, text-heading, success / warning /
// destructive ...), so the page follows the light and the dark theme. The charts (ECharts) load lazily.
import {
  ArrowRight, Boxes, ChevronDown, CircleAlert, Combine, Info, type LucideIcon, ShieldAlert, Sparkles,
  TrendingDown, TrendingUp, UserRoundX, UsersRound,
} from 'lucide-react'
import { type ReactNode, Suspense, lazy, useEffect, useMemo, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'
import { AuthError, api, problemText } from '../api'
import { readColours, shortValue } from '../charts/chartOption'
import useThemeName from '../charts/useThemeName'
import { askInMlPath, useRouter } from '../router'
import type {
  InsightsAlert, InsightsData, InsightsForecast, InsightsPair, InsightsRiskCustomer, InsightsSegment, InsightsStockItem,
} from '../types'

const InsightsChart = lazy(() => import('../charts/InsightsChart'))

// the questions of the cards' "Ask about this" buttons - also the ready questions under the ML Insights box
export const ASK = {
  forecast: 'What will our sales be in the next 3 months?',
  risk: 'Which customers might stop buying?',
  segments: 'What customer groups do we have?',
  alerts: 'Show the unusual invoices',
  pairs: 'Which products are bought together?',
  stock: 'Which items will run out of stock soon?',
}

// the small type styles the page repeats
const CAPTION = 'text-[11px] font-semibold tracking-[.06em] uppercase text-muted-foreground'
const NOTE = 'text-xs leading-relaxed text-muted-foreground'
const ERROR_BOX = 'flex items-start gap-2 rounded-lg border border-destructive/20 bg-danger-soft px-3.5 py-2.5 text-[13px] leading-snug text-destructive'
const NUM = 'text-right tabular-nums whitespace-nowrap'
const ROWS_FIRST = 8 // rows a table shows before "Show all"

type Variant = 'success' | 'warning' | 'info' | 'destructive' | 'secondary'

// the soft colour circles of the card icons (text colour = the icon); tokens only
const TONES = {
  brand: 'bg-primary-soft text-primary',
  red: 'bg-danger-soft text-destructive',
  blue: 'bg-info-soft text-info',
  green: 'bg-success-soft text-success',
  amber: 'bg-warning-soft text-warning',
  grey: 'bg-secondary text-heading',
}

// ------------------------------------------------------------------------------------------------ formats

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** A date as the app writes it: '2026-10-31' -> '31-Oct-2026' (read as written, no time zone); '-' when none. */
export function dayText(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  if (!m) return iso || '-'
  return `${m[3]}-${MONTHS[Number(m[2]) - 1] ?? m[2]}-${m[1]}`
}

/** When the models ran: '2026-11-17T16:00:00' -> '17-Nov-2026, 4:00 PM' (the server's own clock, India time). */
export function runText(iso: string | null | undefined): string {
  const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})/.exec(iso ?? '')
  if (!m) return dayText(iso)
  const hour = Number(m[2])
  return `${dayText(m[1])}, ${hour % 12 || 12}:${m[3]} ${hour < 12 ? 'AM' : 'PM'}`
}

/** Money short in Indian units: 63648019 -> 'INR 6.36 Cr', 2462000 -> 'INR 24.6 L'. */
export const inr = (n: number | null | undefined) => (Number.isFinite(n) ? `INR ${shortValue(n as number)}` : '-')

/** Money in full, Indian grouping (for a hover title): 'INR 6,36,48,019'. */
const inrFull = (n: number) => `INR ${Math.round(n).toLocaleString('en-IN')}`

/** Money in crore, 2 places: 63648019 -> '6.36' (the forecast tiles write 'INR 6.36 Cr'). */
export const crore = (n: number) => (n / 1e7).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** A quantity: whole numbers with Indian grouping, small ones with 1 decimal. */
const qty = (n: number | null | undefined, places = 0) =>
  (Number.isFinite(n) ? (n as number).toLocaleString('en-IN', { maximumFractionDigits: places }) : '-')

const RISK_VARIANT: Record<string, Variant> = { High: 'destructive', Medium: 'warning', Low: 'success' }
const ALERT_VARIANT: Record<string, Variant> = { 'Unusual price': 'info', 'Unusual quantity': 'warning', 'Large credit note': 'destructive' }
const STOCK_VARIANT: Record<string, Variant> = {
  'Out of stock': 'destructive', 'Under 30 days': 'warning', 'Under 90 days': 'info', OK: 'success', 'No recent sales': 'secondary',
}
const STOCK_ORDER = ['Out of stock', 'Under 30 days', 'Under 90 days', 'OK', 'No recent sales']

// ------------------------------------------------------------------------------------------------ small parts

/** The small button of a card: opens ML Insights and asks its question there, as a new ML chat. */
function AskLink({ question }: { question: string }) {
  const { navigate } = useRouter()
  return (
    <button type="button" onClick={() => navigate(askInMlPath(question))} title={`Ask: ${question}`} data-ask=""
      className="group inline-flex flex-none cursor-pointer items-center gap-1 rounded-md text-[12px] font-medium text-primary outline-none hover:text-primary-hover hover:underline focus-visible:ring-3 focus-visible:ring-ring/40">
      Ask about this<span className="sr-only">: {question}</span>
      <ArrowRight aria-hidden="true" className="size-3.5 transition-transform group-hover:translate-x-0.5" />
    </button>
  )
}

/** A card of the page: an icon in a soft circle, the title and a short line under it, the Ask link at the right. */
function InsightCard({ id, icon: Icon, tone, title, note, ask, wide, children }:
  { id: string; icon: LucideIcon; tone: keyof typeof TONES; title: string; note: string; ask: string; wide?: boolean; children: ReactNode }) {
  return (
    <Card className={cn('flex min-w-0 flex-col gap-4 px-5 py-4.5 max-[760px]:px-3.5', wide && '@min-[980px]:col-span-2')}>
      <section aria-label={title} data-insight={id} className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
          <span aria-hidden="true" className={cn('flex size-9 flex-none items-center justify-center rounded-full', TONES[tone])}>
            <Icon className="size-[18px]" />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="m-0 text-[15px] leading-snug font-semibold text-heading">{title}</h3>
            <div className={NOTE}>{note}</div>
          </div>
          <AskLink question={ask} />
        </div>
        {children}
      </section>
    </Card>
  )
}

/** The counts of a card as small pills: 'High 12', 'Medium 30' ... in the given order (others after them). */
function CountPills({ counts, order, variants, label }:
  { counts: Record<string, number> | undefined; order: string[]; variants: Record<string, Variant>; label: string }) {
  const names = [...order.filter((name) => counts && name in counts), ...Object.keys(counts ?? {}).filter((name) => !order.includes(name))]
  if (!names.length) return null
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label={label}>
      {names.map((name) => (
        <li key={name}>
          <Badge variant={variants[name] ?? 'secondary'} data-count={name} className="h-7 gap-1.5 px-2.5 text-[12px]">
            <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
            {name}<span className="font-semibold tabular-nums">{qty(counts?.[name])}</span>
          </Badge>
        </li>
      ))}
    </ul>
  )
}

function Chip({ text, variants }: { text: string; variants: Record<string, Variant> }) {
  return <Badge variant={variants[text] ?? 'secondary'} className="text-[11.5px]">{text || '-'}</Badge>
}

/** Nothing from this model (it did not run, or found nothing). */
function NoResults({ children = 'No results from this model yet.' }: { children?: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-border px-3.5 py-3 text-[13px] text-muted-foreground">{children}</div>
}

/** The first rows of a list, and a button that shows all of them (and fewer again). */
function useFirstRows<T>(items: T[], first = ROWS_FIRST): [T[], ReactNode] {
  const [all, setAll] = useState(false)
  const shown = all ? items : items.slice(0, first)
  const button = items.length > first ? (
    <Button type="button" variant="ghost" size="sm" className="self-start" onClick={() => setAll(!all)} aria-expanded={all}>
      <ChevronDown aria-hidden="true" className={cn('size-4 transition-transform', all && 'rotate-180')} />
      {all ? 'Show fewer' : `Show all ${items.length}`}
    </Button>
  ) : null
  return [shown, button]
}

/** A table in a soft rounded frame (scrolls sideways on a phone). */
function Frame({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <Table aria-label={label} className="text-[12.5px]">{children}</Table>
    </div>
  )
}

const ChartWait = ({ height }: { height: number }) => <Skeleton className="w-full rounded-lg" style={{ height }} />

// ------------------------------------------------------------------------------------------------ 1. sales forecast

/** The product forecasts as one row per product: a column per forecast month, sorted by their total. */
function productRows(forecast: InsightsForecast) {
  const months = (forecast.months ?? []).map((m) => m.month)
  const byCode = new Map<string, { code: string; name: string; values: Map<string, [number, number, number]>; total: number }>()
  for (const p of forecast.products ?? []) {
    const row = byCode.get(p.product_code) ?? { code: p.product_code, name: p.product_description, values: new Map(), total: 0 }
    row.values.set(p.month, [p.forecast, p.low, p.high])
    row.total += p.forecast || 0
    byCode.set(p.product_code, row)
    if (!months.includes(p.month)) months.push(p.month)
  }
  return { months, rows: [...byCode.values()].sort((a, b) => b.total - a.total).slice(0, 10) }
}

/** Every forecast month (12 since 18-Nov) in a small table behind a button: month, its dates, the forecast and
 *  the likely range (it widens further ahead). */
function AllMonths({ months }: { months: InsightsForecast['months'] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="flex flex-col gap-2.5">
      <Button type="button" variant="outline" size="sm" className="self-start" aria-expanded={open}
        aria-controls="insights-all-months" onClick={() => setOpen(!open)}>
        <ChevronDown aria-hidden="true" className={cn('size-4 transition-transform', open && 'rotate-180')} />
        {open ? 'Hide' : 'Show'} all {months.length} forecast months
      </Button>
      {open && (
        <div id="insights-all-months">
          <Frame label="All forecast months">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Sales month</TableHead>
                  <TableHead>Dates</TableHead>
                  <TableHead className="text-right">Forecast</TableHead>
                  <TableHead className="text-right">Likely range</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {months.map((m) => (
                  <TableRow key={m.month} data-all-month={m.month}>
                    <TableCell className="font-medium text-heading">{m.month}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{dayText(m.period_start)} to {dayText(m.period_end)}</TableCell>
                    <TableCell className="text-right tabular-nums" title={inrFull(m.forecast)}>INR {crore(m.forecast)} Cr</TableCell>
                    <TableCell className="text-right whitespace-nowrap tabular-nums">{crore(m.low)} – {crore(m.high)} Cr</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Frame>
        </div>
      )}
    </div>
  )
}

function ForecastCard({ forecast }: { forecast: InsightsForecast | null | undefined }) {
  const [open, setOpen] = useState(false)
  const products = useMemo(() => (forecast ? productRows(forecast) : { months: [], rows: [] }), [forecast])
  const months = forecast?.months ?? []
  const history = forecast?.history ?? []
  const label = forecast
    ? `Net sales of the last ${history.length} sales months and the forecast for the next ${months.length}: `
      + months.map((m) => `${m.month} INR ${crore(m.forecast)} Cr (between ${crore(m.low)} and ${crore(m.high)} Cr)`).join(', ')
    : ''
  return (
    <InsightCard id="forecast" icon={TrendingUp} tone="brand" title="Sales forecast" wide ask={ASK.forecast}
      note={`Net sales of the last 12 sales months (21st to 20th) and the expected next ${months.length || 3}, with a likely range`}>
      {!forecast || !months.length ? <NoResults /> : (
        <>
          <Suspense fallback={<ChartWait height={280} />}>
            <InsightsChart kind="forecast" forecast={forecast} label={label} />
          </Suspense>
          {/* the next 3 months as tiles; all the forecast months (12 since 18-Nov) in the table below */}
          <ul className="grid grid-cols-1 gap-3 @min-[520px]:grid-cols-3" aria-label="The next 3 sales months">
            {months.slice(0, 3).map((m) => (
              <li key={m.month} data-forecast-month={m.month}
                className="flex min-w-0 flex-col gap-0.5 rounded-lg border border-border bg-muted px-3.5 py-3">
                <span className={CAPTION}>{m.month}</span>
                <span className="text-[11.5px] text-muted-foreground">{dayText(m.period_start)} to {dayText(m.period_end)}</span>
                <span className="mt-1 text-[22px] leading-tight font-semibold text-heading tabular-nums" title={inrFull(m.forecast)}>
                  INR {crore(m.forecast)} Cr
                </span>
                <span className="text-xs text-muted-foreground tabular-nums">Likely {crore(m.low)} – {crore(m.high)} Cr</span>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
            {Number.isFinite(forecast.mape_pct) && (
              <span className="inline-flex items-center gap-1.5 text-[13px] text-heading" data-mape="">
                <Info aria-hidden="true" className="size-4 flex-none text-muted-foreground" />
                Model accuracy: about {Math.round(forecast.mape_pct * 10) / 10}% error (MAPE) on the last 6 months
              </span>
            )}
            {forecast.model && <span className={NOTE}>Model: {forecast.model}</span>}
          </div>
          {months.length > 3 && <AllMonths months={months} />}
          {products.rows.length > 0 && (
            <div className="flex flex-col gap-2.5">
              <Button type="button" variant="outline" size="sm" className="self-start" aria-expanded={open}
                aria-controls="insights-products" onClick={() => setOpen(!open)}>
                <ChevronDown aria-hidden="true" className={cn('size-4 transition-transform', open && 'rotate-180')} />
                {open ? 'Hide' : 'Show'} the top {products.rows.length} product forecasts
              </Button>
              {open && (
                <div id="insights-products">
                  <Frame label="Top product forecasts">
                    <TableHeader>
                      <TableRow>
                        <TableHead>Product</TableHead>
                        {products.months.map((month) => <TableHead key={month} className="text-right">{month}</TableHead>)}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {products.rows.map((row) => (
                        <TableRow key={row.code}>
                          <TableCell className="min-w-[180px]">
                            <div className="font-medium text-heading">{row.name || row.code}</div>
                            <div className="text-[11px] text-muted-foreground">{row.code}</div>
                          </TableCell>
                          {products.months.map((month) => {
                            const v = row.values.get(month)
                            return (
                              <TableCell key={month} className={NUM}>
                                {v ? (
                                  <>
                                    <div className="font-medium text-heading">{inr(v[0])}</div>
                                    <div className="text-[11px] text-muted-foreground">{shortValue(v[1])} – {shortValue(v[2])}</div>
                                  </>
                                ) : '-'}
                              </TableCell>
                            )
                          })}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Frame>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </InsightCard>
  )
}

// ------------------------------------------------------------------------------------------------ 2. customers at risk

function ScoreBar({ score, level }: { score: number; level: string }) {
  const value = Math.max(0, Math.min(100, Math.round(score || 0)))
  const fill = level === 'High' ? 'bg-destructive' : level === 'Medium' ? 'bg-warning' : 'bg-success'
  return (
    <div className="flex items-center gap-2" title={`Risk score ${value} of 100 (${level})`}>
      <div className="h-1.5 w-16 flex-none overflow-hidden rounded-full bg-secondary" aria-hidden="true">
        <div className={cn('h-full rounded-full', fill)} style={{ width: `${value}%` }} />
      </div>
      <span className="text-[12px] font-semibold text-heading tabular-nums">{value}</span>
      <span className="sr-only">of 100, {level}</span>
    </div>
  )
}

function Change({ pct }: { pct: number | null }) {
  if (pct === null || !Number.isFinite(pct)) return <span className="text-muted-foreground">-</span>
  const rounded = Math.round(pct)
  const down = rounded < 0
  const Icon = down ? TrendingDown : TrendingUp
  return (
    <span className={cn('inline-flex items-center gap-1 font-semibold tabular-nums', down ? 'text-destructive' : rounded > 0 ? 'text-success' : 'text-muted-foreground')}>
      {rounded !== 0 && <Icon aria-hidden="true" className="size-3.5" />}
      {rounded > 0 ? '+' : ''}{rounded}%
    </span>
  )
}

function RiskCard({ risk }: { risk: InsightsData['risk'] }) {
  const customers: InsightsRiskCustomer[] = risk?.customers ?? []
  const [shown, more] = useFirstRows(customers)
  return (
    <InsightCard id="risk" icon={UserRoundX} tone="red" title="Customers at risk" wide ask={ASK.risk}
      note="Customers who buy less or less often than before, and might stop buying">
      <CountPills counts={risk?.counts} order={['High', 'Medium', 'Low']} variants={RISK_VARIANT} label="Customers by risk" />
      {!customers.length ? <NoResults /> : (
        <>
          <Frame label="Customers at risk">
            <TableHeader>
              <TableRow>
                <TableHead>Customer</TableHead>
                <TableHead>Risk score</TableHead>
                <TableHead>Why</TableHead>
                <TableHead>Last invoice</TableHead>
                <TableHead className="text-right">Last 3 months</TableHead>
                <TableHead className="text-right">3 months before</TableHead>
                <TableHead className="text-right">Change</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((c) => (
                <TableRow key={c.customer_name} data-risk={c.risk_level}>
                  <TableCell className="min-w-[170px] font-medium text-heading">{c.customer_name}</TableCell>
                  <TableCell><ScoreBar score={c.risk_score} level={c.risk_level} /></TableCell>
                  <TableCell className="min-w-[200px] text-[12px]">{c.reason}</TableCell>
                  <TableCell className="whitespace-nowrap">{dayText(c.last_invoice_date)}</TableCell>
                  <TableCell className={NUM} title={inrFull(c.sales_last_3m)}>{inr(c.sales_last_3m)}</TableCell>
                  <TableCell className={NUM} title={inrFull(c.sales_prev_3m)}>{inr(c.sales_prev_3m)}</TableCell>
                  <TableCell className={NUM}><Change pct={c.change_pct} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Frame>
          {more}
        </>
      )}
    </InsightCard>
  )
}

// ------------------------------------------------------------------------------------------------ 3. customer groups

function SegmentsCard({ segments }: { segments: InsightsSegment[] }) {
  // the dots of the list take the donut's colours (the theme's chart palette, in the same order)
  const palette = readColours(useThemeName()).series
  const total = segments.reduce((sum, s) => sum + (s.customers || 0), 0)
  const label = `Customers in each group: ${segments.map((s) => `${s.segment_name} ${s.customers}`).join(', ')}`
  return (
    <InsightCard id="segments" icon={UsersRound} tone="blue" title="Customer groups" ask={ASK.segments}
      note="Customers grouped by how recently, how often and how much they buy">
      {!segments.length ? <NoResults /> : (
        <div className="flex flex-col gap-4">
          <Suspense fallback={<ChartWait height={210} />}>
            <InsightsChart kind="segments" segments={segments} label={label} centre={total.toLocaleString('en-IN')} />
          </Suspense>
          <ul className="flex flex-col divide-y divide-border" aria-label="Customer groups">
            {segments.map((s, i) => (
              <li key={s.segment_name} data-segment={s.segment_name} className="flex flex-col gap-0.5 py-2.5 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="inline-flex items-center gap-2 text-[13.5px] font-semibold text-heading">
                    <span aria-hidden="true" className="size-2.5 flex-none rounded-full" style={{ background: palette[i % palette.length] }} />
                    {s.segment_name}
                  </span>
                  <span className="text-[13px] font-semibold text-heading tabular-nums" title={inrFull(s.sales_inr)}>{inr(s.sales_inr)}</span>
                </div>
                <div className={NOTE}>
                  {qty(s.customers)} customers{total > 0 ? ` (${Math.round((s.customers / total) * 100)}%)` : ''} · last bought about{' '}
                  {qty(s.avg_recency_days)} days ago · {qty(s.avg_invoices, 1)} invoices each on average
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </InsightCard>
  )
}

// ------------------------------------------------------------------------------------------------ 4. unusual invoices

function AlertsCard({ alerts }: { alerts: InsightsData['alerts'] }) {
  const items: InsightsAlert[] = alerts?.items ?? []
  const [shown, more] = useFirstRows(items)
  return (
    <InsightCard id="alerts" icon={ShieldAlert} tone="amber" title="Unusual invoices" wide ask={ASK.alerts}
      note="Invoice lines whose price, quantity or credit note is far from what is usual for that product or customer">
      <CountPills counts={alerts?.counts} order={['Unusual price', 'Unusual quantity', 'Large credit note']} variants={ALERT_VARIANT}
        label="Unusual invoices by type" />
      {!items.length ? <NoResults>Nothing unusual found.</NoResults> : (
        <>
          <Frame label="Unusual invoices">
            <TableHeader>
              <TableRow>
                <TableHead>Type</TableHead>
                <TableHead>Invoice</TableHead>
                <TableHead>Date</TableHead>
                <TableHead>Customer</TableHead>
                <TableHead>Product</TableHead>
                <TableHead className="text-right">Value vs typical</TableHead>
                <TableHead>Why</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((a, i) => (
                <TableRow key={`${a.invoice_number}-${a.product_code}-${i}`} data-alert={a.alert_type}>
                  <TableCell><Chip text={a.alert_type} variants={ALERT_VARIANT} /></TableCell>
                  <TableCell className="font-medium whitespace-nowrap text-heading">{a.invoice_number}</TableCell>
                  <TableCell className="whitespace-nowrap">{dayText(a.invoice_date)}</TableCell>
                  <TableCell className="min-w-[150px]">{a.customer_name}</TableCell>
                  <TableCell className="whitespace-nowrap">{a.product_code || '-'}</TableCell>
                  <TableCell className={NUM}>
                    <div className="font-semibold text-heading" title={inrFull(a.value_inr)}>{inr(a.value_inr)}</div>
                    {a.typical_inr !== null && Number.isFinite(a.typical_inr) && (
                      <div className="text-[11px] text-muted-foreground">typical {inr(a.typical_inr)}</div>
                    )}
                  </TableCell>
                  <TableCell className="min-w-[200px] text-[12px]">{a.reason}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Frame>
          {more}
        </>
      )}
    </InsightCard>
  )
}

// ------------------------------------------------------------------------------------------------ 5. bought together

function PairsCard({ pairs }: { pairs: InsightsPair[] }) {
  const [shown, more] = useFirstRows(pairs)
  return (
    <InsightCard id="pairs" icon={Combine} tone="green" title="Bought together" ask={ASK.pairs}
      note="Products that are often on the same order - ideas for bundles and cross-selling">
      {!pairs.length ? <NoResults /> : (
        <>
          <Frame label="Products bought together">
            <TableHeader>
              <TableRow>
                <TableHead>Products</TableHead>
                <TableHead className="text-right">Orders</TableHead>
                <TableHead className="text-right" title="Of the orders with the first product, how many also had the second">Confidence</TableHead>
                <TableHead className="text-right" title="How many times more often than by chance">Lift</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((p) => (
                <TableRow key={`${p.product_a_code}+${p.product_b_code}`} data-pair="">
                  <TableCell className="min-w-[190px]">
                    <div className="font-medium text-heading" title={p.product_a_code}>{p.product_a_description || p.product_a_code}</div>
                    <div className="text-[12px] text-muted-foreground">
                      <span aria-hidden="true" className="font-semibold text-primary">+ </span>
                      <span className="sr-only">with </span>
                      <span title={p.product_b_code}>{p.product_b_description || p.product_b_code}</span>
                    </div>
                  </TableCell>
                  <TableCell className={NUM}>{qty(p.orders_together)}</TableCell>
                  <TableCell className={NUM}>{qty(p.confidence_pct)}%</TableCell>
                  <TableCell className={NUM}>{qty(p.lift, 1)}×</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Frame>
          {more}
        </>
      )}
    </InsightCard>
  )
}

// ------------------------------------------------------------------------------------------------ 6. stock running out

/** The items that run out first: out of stock, then the fewest days left; no recent sales last. */
export function soonest(items: InsightsStockItem[]): InsightsStockItem[] {
  const rank = (s: string) => { const i = STOCK_ORDER.indexOf(s); return i < 0 ? STOCK_ORDER.length : i }
  return [...items].sort((a, b) => rank(a.status) - rank(b.status)
    || (a.days_left ?? Infinity) - (b.days_left ?? Infinity))
}

function StockCard({ stockout }: { stockout: InsightsData['stockout'] }) {
  const items = useMemo(() => soonest(stockout?.items ?? []), [stockout])
  const [shown, more] = useFirstRows(items)
  return (
    <InsightCard id="stock" icon={Boxes} tone="grey" title="Stock running out" wide ask={ASK.stock}
      note="Days of stock left at the recent rate of sales, and the date it would run out">
      <CountPills counts={stockout?.counts} order={STOCK_ORDER} variants={STOCK_VARIANT} label="Items by stock status" />
      {!items.length ? <NoResults /> : (
        <>
          <Frame label="Stock running out">
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead className="text-right">In stock</TableHead>
                <TableHead className="text-right">Sold per day</TableHead>
                <TableHead className="text-right">Days left</TableHead>
                <TableHead>Runs out</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((s) => (
                <TableRow key={s.product_code} data-stock={s.status}>
                  <TableCell className="min-w-[190px]">
                    <div className="font-medium text-heading">{s.product_description || s.product_code}</div>
                    <div className="text-[11px] text-muted-foreground">{s.product_code}</div>
                  </TableCell>
                  <TableCell className={NUM}>{qty(s.stock_qty)}</TableCell>
                  <TableCell className={NUM}>{qty(s.avg_daily_sales_qty, 1)}</TableCell>
                  <TableCell className={cn(NUM, 'font-semibold text-heading')}>{s.days_left === null ? '-' : qty(s.days_left)}</TableCell>
                  <TableCell className="whitespace-nowrap">{dayText(s.runout_date)}</TableCell>
                  <TableCell><Chip text={s.status} variants={STOCK_VARIANT} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Frame>
          {more}
        </>
      )}
    </InsightCard>
  )
}

// ------------------------------------------------------------------------------------------------ before the results

function NotReady() {
  return (
    <Card className="flex items-start gap-3 px-5 py-5 max-[760px]:px-3.5" data-insights-empty="">
      <span aria-hidden="true" className={cn('flex size-10 flex-none items-center justify-center rounded-full', TONES.brand)}>
        <Sparkles className="size-5" />
      </span>
      <div className="flex min-w-0 flex-col gap-1">
        <h3 className="m-0 text-[15px] font-semibold text-heading">No insights yet</h3>
        <p className="m-0 text-[13px] leading-relaxed text-muted-foreground">
          The ML results are not ready yet - an admin runs run_ml after each data load.
        </p>
      </div>
    </Card>
  )
}

function PageSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 @min-[980px]:grid-cols-2" aria-hidden="true">
      <Skeleton className="h-80 w-full rounded-xl @min-[980px]:col-span-2" />
      <Skeleton className="h-64 w-full rounded-xl" />
      <Skeleton className="h-64 w-full rounded-xl" />
    </div>
  )
}

// ------------------------------------------------------------------------------------------------ the page

export default function MlDashboard() {
  const [data, setData] = useState<InsightsData | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let gone = false
    api.insights()
      .then((reply) => { if (!gone) setData(reply) })
      .catch((err) => { if (!gone && !(err instanceof AuthError)) setError(problemText(err, "The insights can't be read right now.")) })
    return () => { gone = true }
  }, [])

  return (
    <section aria-label="ML results" className="ui-scope @container flex min-w-0 flex-col gap-4" data-ml-dashboard="">
      {data?.ready && (
        <p className="m-0 flex items-start gap-2 text-[13px] leading-relaxed text-muted-foreground" data-insights-about="">
          <Sparkles aria-hidden="true" className="mt-0.5 size-4 flex-none text-primary" />
          <span>
            Estimates by machine-learning models on the data up to {dayText(data.data_to)} · last run {runText(data.run_at)}
          </span>
        </p>
      )}
      {error ? (
        <div className={ERROR_BOX} role="alert">
          <CircleAlert aria-hidden="true" className="mt-px size-4 flex-none" />
          <span>{error}</span>
        </div>
      ) : !data ? (
        <><span className="sr-only" role="status">Loading…</span><PageSkeleton /></>
      ) : !data.ready ? <NotReady /> : (
        <div className="grid grid-cols-1 gap-4 @min-[980px]:grid-cols-2">
          <ForecastCard forecast={data.forecast} />
          <RiskCard risk={data.risk} />
          <SegmentsCard segments={data.segments ?? []} />
          <PairsCard pairs={data.pairs ?? []} />
          <AlertsCard alerts={data.alerts} />
          <StockCard stockout={data.stockout} />
        </div>
      )}
    </section>
  )
}
