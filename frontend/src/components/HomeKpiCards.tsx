// The KPI cards of the Home page (HomePage.tsx puts them in its grid of 4 a row). Every card keeps: the label,
// the big number counting up the first time it shows (screen readers get the final number only), the change
// badge, the note at the bottom, and a click opens the Ask page with its question filled in (nothing is asked
// until Ask is pressed). Every card fills its row's height, so the notes and the links of a row line up.
// Every card has the same light look: the white card, a thin light border, a soft shadow, the same light blue
// icon circle and label; only the small picture under the number differs (by kpi.key), always in the blue family:
// - month_sales: a small line of the last sales months (the brand blue);
// - fy_sales: a small filled area of the FY's running total (the darker brand blue);
// - customers: a ring of the active customers out of all customers ("total");
// - products: small bars, one per sales month, the newest one strong;
// - open_orders / stock: the facts as light blue chips, a big faint blue icon in the corner;
// - top_customer / top_product: a round light blue avatar (the customer's initials, the product's award),
//   a small "No. 1" / "Top product" tag, the name, the amount and its share as a chip.
// The change badge stays small: green for up, red for down (the success / danger colours).
// A card from an older server (no trend, facts, total or name) or one this page does not know falls back to
// the plain look: an icon, the number, a small line or chips where there are any.
// No chart library: small inline SVGs, hidden from screen readers (a sentence says the same). app.css colours
// every <a> outside a cascade layer: the card links' own colours are marked (!).
// Light and dark: every colour is a token (bg-card, text-heading ...) or a light / dark pair - a soft tint in
// light, a see-through tint in dark. The small pictures are drawn in currentColor, so they follow the text colour.
import {
  ArrowRight, Award, CalendarRange, ClipboardList, Crown, IndianRupee, type LucideIcon, Package, Users, Warehouse,
} from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { wantsMotion } from '../charts/chartOption'
import { shortIndian } from '../charts/pickChart'
import { Link } from '../router'
import type { HomeChange, HomeKpi, HomeTrendPoint } from '../types'

/** A KPI card as the server sends it. Active customers also has "total": all customers (an older server: none). */
export type KpiData = HomeKpi & { total?: number | null }

/** How long the KPI numbers count up the first time they show. */
const COUNT_MS = 700

const CAPTION = 'text-[11px] font-semibold tracking-[.06em] uppercase'

// the soft shadow of every card: a hairline and a faint blue glow under it (theme colours, light and dark)
const SHADOW = 'shadow-[0_1px_2px_color-mix(in_srgb,var(--shadow-c)_5%,transparent),0_12px_28px_-24px_color-mix(in_srgb,var(--brand)_40%,transparent)]'

// ------------------------------------------------------------------------------------------------ the looks

type Chart = 'line' | 'area' | 'ring' | 'bars' | 'none'

interface Look {
  icon: LucideIcon
  chart: Chart            // the small picture under the number ('none': the facts as chips instead)
  card: string            // the background and the border
  hover: string           // the border (and shadow, focus ring) on hover and focus, when the card is a link
  text: string            // the card's own text colour (!: app.css colours every <a>)
  circle: string          // the icon's circle
  caption: string         // the label
  value: string           // the big number
  sub: string             // the full amount under it
  note: string            // the note and the "Ask the Assistant about this" line
  link: string            // the "Ask the Assistant about this" line when the card is pointed at
  ink: string             // the colour of the small picture
  chip: string            // the facts chips
  watermark?: LucideIcon  // a big faint icon in the bottom corner
  mark?: string           // its colour
  avatar?: string         // the top cards: the round avatar
  tag?: [string, string, string] // the top cards: [emoji, words, colours]
}

// the one light look of every card (a card this page does not know gets it too); the cards below only pick their
// icon, their small picture and the blue shade of it
const CHIP = 'border border-primary/15 bg-primary-soft text-primary'
const PLAIN: Look = {
  icon: IndianRupee, chart: 'line',
  card: 'border-border bg-card', hover: 'hover:border-primary/30 focus-visible:border-primary/40',
  text: 'text-card-foreground! hover:text-card-foreground!',
  circle: 'bg-primary-soft text-primary', caption: 'text-muted-foreground', value: 'text-heading', sub: 'text-heading/80',
  note: 'text-muted-foreground', link: 'group-hover:text-primary', ink: 'text-primary', chip: CHIP,
}

const LOOKS: Record<string, Partial<Look>> = {
  month_sales: {},
  fy_sales: { icon: CalendarRange, chart: 'area', ink: 'text-primary-hover' },
  customers: { icon: Users, chart: 'ring' },
  products: { icon: Package, chart: 'bars' },
  open_orders: { icon: ClipboardList, chart: 'none', watermark: ClipboardList, mark: 'text-primary' },
  stock: { icon: Warehouse, chart: 'none', watermark: Warehouse, mark: 'text-primary' },
  top_customer: {
    icon: Crown, chart: 'none', avatar: 'bg-primary-soft text-primary ring-primary/20', tag: ['🏆', 'No. 1', CHIP],
  },
  top_product: {
    icon: Award, chart: 'none', avatar: 'bg-primary-soft text-primary ring-primary/20', tag: ['⭐', 'Top product', CHIP],
  },
}

// ------------------------------------------------------------------------------------------------ small helpers

/** The big number of a KPI card: money short in Indian units ('INR 12 L'), a count as the API wrote it. */
function bigText(kpi: HomeKpi): string {
  return kpi.money && kpi.text !== '-' ? `INR ${shortIndian(kpi.value)}` : kpi.text
}

/** A number on its way up to a KPI's value, written like the final one (money in the final's unit: Cr, L, K). */
function countingText(kpi: HomeKpi, n: number): string {
  if (!kpi.money) return Math.round(n).toLocaleString('en-US')
  const abs = Math.abs(kpi.value)
  const [size, unit] = abs >= 1e7 ? [1e7, ' Cr'] : abs >= 1e5 ? [1e5, ' L'] : abs >= 1e3 ? [1e3, ' K'] : [1, '']
  return `INR ${(n / size).toLocaleString('en-IN', { maximumFractionDigits: size === 1 ? 0 : 1 })}${unit}`
}

/** Counts from 0 up to the target in COUNT_MS, once (from the first show); null when not counting (done, less
 *  motion asked for, nothing to count) - the caller then shows the exact text. */
function useCountUp(target: number, can: boolean): number | null {
  const [run] = useState(() => can && Number.isFinite(target) && target !== 0 && wantsMotion()
    && typeof window.requestAnimationFrame === 'function')
  const [value, setValue] = useState<number | null>(run ? 0 : null)
  useEffect(() => {
    if (!run) return
    let frame = 0
    let start = -1
    const step = (now: number) => {
      if (start < 0) start = now
      const t = Math.min(1, (now - start) / COUNT_MS)
      if (t >= 1) { setValue(null); return }
      setValue(target * (1 - (1 - t) ** 3)) // fast first, slow at the end
      frame = window.requestAnimationFrame(step)
    }
    frame = window.requestAnimationFrame(step)
    return () => { window.cancelAnimationFrame(frame); setValue(null) }
  }, [run, target])
  return value
}

/** The months of a trend that can be drawn (a number each). */
function drawable(points: HomeTrendPoint[] | null | undefined): HomeTrendPoint[] {
  return (points ?? []).filter((p) => p && Number.isFinite(p.value))
}

/** The amount of one month in a sentence for screen readers. */
function pointText(point: HomeTrendPoint, money: boolean): string {
  return `${point.label}: ${money ? `INR ${shortIndian(point.value)}` : Math.round(point.value).toLocaleString('en-US')}`
}

// words a company name often has that say nothing about who it is
const NOT_A_NAME = new Set(['limited', 'ltd', 'pvt', 'private', 'inc', 'llp', 'llc', 'co', 'company', 'corp',
  'corporation', 'the', 'and', 'of'])

/** The 1-2 letters of a name for a round avatar: 'Allied Castings Limited' -> 'AC', 'M/s. Sharma Traders' -> 'ST'. */
export function initials(name: string): string {
  const words = name.replace(/^m\/s\.?\s*/i, '').split(/[\s.,&()/_-]+/).filter((w) => /^[\p{L}\p{N}]/u.test(w))
  const kept = words.filter((w) => !NOT_A_NAME.has(w.toLowerCase()))
  return (kept.length ? kept : words).slice(0, 2).map((w) => [...w][0]).join('').toUpperCase()
}

/** The share of value in total for a ring, 0 to 1 (0 when there is no total). */
export function share(value: number, total: number): number {
  if (!(Number.isFinite(value) && Number.isFinite(total) && total > 0)) return 0
  return Math.min(1, Math.max(0, value / total))
}

/** A share written for the middle of a ring: '42%', '<1%' (more than none but under half a percent). */
export function shareText(part: number): string {
  const pct = Math.round(part * 100)
  return part > 0 && pct === 0 ? '<1%' : `${pct}%`
}

// ------------------------------------------------------------------------------------------------ the small pictures

/** The newest month as a dot (an HTML dot: the stretched SVG would draw an oval). */
function LastDot({ x, y, ring }: { x: number; y: number; ring?: string }) {
  return (
    <span aria-hidden="true" className={cn('absolute size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-current ring-2 ring-card', ring)}
      style={{ left: `${x}%`, top: `${y}%` }} />
  )
}

/** A small line of the last sales months over a soft area. Nothing for fewer than 2 months. The picture is hidden
 *  from screen readers; a sentence says the same. */
export function Sparkline({ points, money, className, dot, area = 0.1 }:
  { points: HomeTrendPoint[] | null | undefined; money: boolean; className?: string; dot?: string; area?: number }) {
  const good = drawable(points)
  if (good.length < 2) return null
  const W = 120
  const H = 36
  const PAD = 4
  const values = good.map((p) => p.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const xy = good.map((p, i): [number, number] => [
    (i / (good.length - 1)) * W,
    max === min ? H / 2 : PAD + (H - 2 * PAD) * (1 - (p.value - min) / (max - min)),
  ])
  const line = xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const [lastX, lastY] = xy[xy.length - 1]
  return (
    <div data-slot="sparkline" className={cn('relative h-9 w-full', className)}>
      <svg aria-hidden="true" focusable="false" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="block h-full w-full overflow-visible">
        <polygon points={`0,${H} ${line} ${W},${H}`} fill="currentColor" opacity={area} />
        <polyline points={line} fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round"
          vectorEffect="non-scaling-stroke" />
      </svg>
      <LastDot x={(lastX / W) * 100} y={(lastY / H) * 100} ring={dot} />
      <span className="sr-only">
        The last {good.length} sales months: {good.map((p) => pointText(p, money)).join(', ')}.
      </span>
    </div>
  )
}

/** A small filled area (from 0 up, so a running total reads as it grows), fading down to the card. */
function AreaChart({ points, money, className }: { points: HomeTrendPoint[]; money: boolean; className?: string }) {
  const gradient = `kpi-area-${useId().replace(/[^\w-]/g, '')}`
  const W = 120
  const H = 44
  const PAD = 4
  const values = points.map((p) => p.value)
  const low = Math.min(0, ...values)
  const high = Math.max(...values)
  const xy = points.map((p, i): [number, number] => [
    (i / (points.length - 1)) * W,
    high === low ? H / 2 : PAD + (H - PAD) * (1 - (p.value - low) / (high - low)),
  ])
  const line = xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' L')
  const [lastX, lastY] = xy[xy.length - 1]
  return (
    <div data-slot="kpi-area" className={cn('relative mt-1 h-12 w-full', className)}>
      <svg aria-hidden="true" focusable="false" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="block h-full w-full overflow-visible">
        <defs>
          <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity={0.32} />
            <stop offset="100%" stopColor="currentColor" stopOpacity={0.03} />
          </linearGradient>
        </defs>
        <path data-slot="area" d={`M0,${H} L${line} L${W},${H} Z`} fill={`url(#${gradient})`} />
        <path d={`M${line}`} fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round"
          vectorEffect="non-scaling-stroke" />
      </svg>
      <LastDot x={(lastX / W) * 100} y={(lastY / H) * 100} />
      <span className="sr-only">
        The FY running total at the end of the last {points.length} sales months: {points.map((p) => pointText(p, money)).join(', ')}.
      </span>
    </div>
  )
}

/** Small bars, one per sales month (from 0 up), the newest one strong; the first and last month written under them. */
function Bars({ points, money, className }: { points: HomeTrendPoint[]; money: boolean; className?: string }) {
  const W = 120
  const H = 40
  const slot = W / points.length
  const gap = Math.min(6, slot * 0.3)
  const high = Math.max(0, ...points.map((p) => p.value))
  return (
    <div data-slot="kpi-bars" className={cn('mt-1 flex flex-col gap-1', className)}>
      <svg aria-hidden="true" focusable="false" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="block h-10 w-full">
        {points.map((p, i) => {
          const last = i === points.length - 1
          // a month with nothing sold still shows a thin stub, so every month has its place
          const h = high > 0 && p.value > 0 ? Math.max(1.5, (p.value / high) * H) : 1.5
          return (
            <rect key={`${p.label}-${i}`} data-last={last || undefined} x={i * slot + gap / 2} y={H - h} width={slot - gap} height={h}
              rx={1.5} fill="currentColor" opacity={last ? 1 : 0.3} />
          )
        })}
      </svg>
      <div aria-hidden="true" className="flex justify-between text-[10px] leading-none text-muted-foreground">
        <span>{points[0].label}</span><span>{points[points.length - 1].label}</span>
      </div>
      <span className="sr-only">
        The last {points.length} sales months: {points.map((p) => pointText(p, money)).join(', ')}.
      </span>
    </div>
  )
}

/** A ring of a part of a whole (active customers of all customers), the share written in the middle. */
function Ring({ kpi, total, className }: { kpi: HomeKpi; total: number; className?: string }) {
  const part = share(kpi.value, total)
  const text = shareText(part)
  const R = 26
  const C = 2 * Math.PI * R
  return (
    <div data-slot="kpi-ring" className={cn('relative size-16 flex-none', className)}>
      <svg aria-hidden="true" focusable="false" viewBox="0 0 64 64" className="block size-full -rotate-90">
        <circle cx={32} cy={32} r={R} fill="none" stroke="currentColor" strokeOpacity={0.15} strokeWidth={7} />
        {part > 0 && (
          <circle data-slot="ring-fill" cx={32} cy={32} r={R} fill="none" stroke="currentColor" strokeWidth={7} strokeLinecap="round"
            strokeDasharray={`${(part * C).toFixed(2)} ${C.toFixed(2)}`} />
        )}
      </svg>
      <span aria-hidden="true" className="absolute inset-0 flex items-center justify-center text-[13px] font-semibold text-heading tabular-nums">
        {text}
      </span>
      <span className="sr-only">{kpi.text} of {total.toLocaleString('en-US')} customers ({text})</span>
    </div>
  )
}

// ------------------------------------------------------------------------------------------------ the parts of a card

function Change({ change, className }: { change: HomeChange; className?: string }) {
  const up = change.direction === 'up'
  const down = change.direction === 'down'
  return (
    <Badge variant={up ? 'success' : down ? 'destructive' : 'secondary'} data-change={change.direction}
      className={cn('h-auto rounded-md px-1.5 text-left text-[11.5px] font-semibold whitespace-normal', className)}>
      <span aria-hidden="true" className="text-[9px]">{up ? '▲' : down ? '▼' : '●'}</span>
      <span><span className="sr-only">{down ? 'Down' : up ? 'Up' : 'Same'} </span>{change.text}</span>
    </Badge>
  )
}

/** The big number: it counts up the first time it shows; while it counts, screen readers get the final one only. */
function BigNumber({ kpi, className }: { kpi: HomeKpi; className?: string }) {
  const final = bigText(kpi)
  const counting = useCountUp(kpi.value, kpi.text !== '-')
  const shown = counting === null ? final : countingText(kpi, counting)
  return (
    <div className={cn('leading-tight font-semibold tabular-nums [overflow-wrap:anywhere]', className)} title={kpi.text}>
      <span data-slot="kpi-value" aria-hidden={counting !== null || undefined}>{shown}</span>
      {counting !== null && <span className="sr-only">{final}</span>}
    </div>
  )
}

/** The round avatar of a top card: the customer's initials (a small crown on it), or the card's icon. */
function Avatar({ kpi, look }: { kpi: HomeKpi; look: Look }) {
  const Icon = look.icon
  const name = kpi.name?.trim() ?? ''
  const letters = kpi.key === 'top_customer' && name ? initials(name) : ''
  return (
    <span aria-hidden="true" data-slot="kpi-avatar"
      className={cn('relative flex size-11 flex-none items-center justify-center rounded-full text-[15px] font-semibold tracking-wide ring-2', look.avatar)}>
      {letters || <Icon className="size-5" />}
      {letters && (
        <span className="absolute -top-1 -right-1 flex size-[18px] items-center justify-center rounded-full bg-card text-primary shadow-[0_1px_3px_color-mix(in_srgb,var(--shadow-c)_20%,transparent)]">
          <Crown className="size-3" />
        </span>
      )}
    </span>
  )
}

// ------------------------------------------------------------------------------------------------ the card

export function KpiCard({ kpi }: { kpi: KpiData }) {
  const known = kpi.key in LOOKS
  const look: Look = { ...PLAIN, ...LOOKS[kpi.key] }
  const ask = kpi.ask?.trim()
  const name = kpi.name?.trim()
  const points = drawable(kpi.trend)
  const total = Number(kpi.total ?? 0)
  // the picture this card can draw: the ring needs the total (an older server: the plain small line), the
  // others at least 2 months
  let chart = look.chart
  if (chart === 'ring' && !(Number.isFinite(total) && total > 0)) chart = 'line'
  if (chart !== 'ring' && points.length < 2) chart = 'none'
  // the short facts, where there is no picture (an older server sends none)
  const facts = chart === 'none'
    ? (kpi.facts ?? []).map((fact) => String(fact ?? '').trim()).filter(Boolean).slice(0, 3) : []
  const top = Boolean(look.avatar)
  const hero = kpi.key === 'month_sales'
  const Icon = look.icon
  const Mark = look.watermark

  const number = <BigNumber kpi={kpi} className={cn(top ? 'text-[21px]' : hero ? 'text-[28px]' : 'text-[25px]', look.value)} />
  const full = kpi.money && kpi.text !== '-'
    ? <div className={cn('text-xs font-medium [overflow-wrap:anywhere]', !top && '-mt-1', look.sub)}>{kpi.text}</div> : null
  const change = kpi.change ? <div><Change change={kpi.change} /></div> : null

  const body = (
    <>
      {/* the big faint icon sits behind everything (-z-10 inside the card's own layer: "isolate") */}
      {Mark && (
        <Mark aria-hidden="true" strokeWidth={1.5}
          className={cn('pointer-events-none absolute -right-5 -bottom-6 -z-10 size-32 -rotate-12 opacity-[.07]', look.mark)} />
      )}
      {/* the label is never cut: it may take 2 lines (as tall as the icon, so the numbers of a row line up)
          or more, and then starts level with the top of the icon */}
      <div className="flex items-start gap-2.5">
        {!top && (
          <span aria-hidden="true" className={cn('flex size-9 flex-none items-center justify-center rounded-full', look.circle)}>
            <Icon className="size-[18px]" />
          </span>
        )}
        <span data-slot="kpi-label" className={cn(CAPTION, look.caption, 'flex min-h-9 min-w-0 flex-1 items-center leading-snug [overflow-wrap:anywhere]')}>
          {kpi.label}
        </span>
        {top && name && look.tag && (
          <span data-slot="kpi-tag" className={cn('inline-flex flex-none items-center gap-1 self-center rounded-full px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap', look.tag[2])}>
            <span aria-hidden="true">{look.tag[0]}</span>{look.tag[1]}
          </span>
        )}
      </div>

      {top ? (
        <div className="flex items-center gap-3">
          <Avatar kpi={kpi} look={look} />
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            {name && <div data-slot="kpi-name" title={name} className="truncate text-[14px] leading-snug font-semibold text-heading">{name}</div>}
            {number}
            {full}
          </div>
        </div>
      ) : chart === 'ring' ? (
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-2">{number}{change}</div>
          <Ring kpi={kpi} total={total} className={look.ink} />
        </div>
      ) : (
        <>{number}{full}</>
      )}
      {chart !== 'ring' && change}

      {chart === 'line' && (
        <Sparkline points={points} money={kpi.money} className={cn('mt-1', look.ink)} area={hero ? 0.14 : 0.1} />
      )}
      {chart === 'area' && <AreaChart points={points} money={kpi.money} className={look.ink} />}
      {chart === 'bars' && <Bars points={points} money={kpi.money} className={look.ink} />}
      {facts.length > 0 && (
        <ul data-slot="kpi-facts" className="mt-1 flex flex-wrap gap-1.5">
          {facts.map((fact, i) => (
            <li key={i} className="min-w-0 max-w-full">
              <Badge variant="secondary"
                className={cn('h-auto max-w-full rounded-md px-2 py-0.5 text-left text-[11.5px] whitespace-normal [overflow-wrap:anywhere]', look.chip)}>
                {fact}
              </Badge>
            </li>
          ))}
        </ul>
      )}

      {/* the note and the link sit at the bottom, so the bottoms of a row line up */}
      <div className={cn('mt-auto text-xs leading-relaxed', look.note)}>{kpi.note}</div>
      {ask && (
        <div className={cn('flex items-center gap-1 pt-0.5 text-[12px] font-medium transition-colors', look.note, look.link)}>
          Ask the Assistant about this<ArrowRight aria-hidden="true" className="size-3.5 transition-transform group-hover:translate-x-0.5" />
          <span className="sr-only">: {ask}</span>
        </div>
      )}
    </>
  )

  const shape = cn('relative isolate flex h-full min-w-0 flex-col gap-2 overflow-hidden rounded-xl border px-4.5 pt-4.5 pb-4',
    SHADOW, 'text-card-foreground', look.card)
  const lookName = known ? kpi.key : 'plain'
  if (!ask) return <div className={shape} data-kpi={kpi.key} data-look={lookName}>{body}</div>
  // the whole card opens the Ask page with its question in the box
  return (
    <Link to={`/new?q=${encodeURIComponent(ask)}`} data-kpi={kpi.key} data-look={lookName} title={`Ask the Assistant: ${ask}`}
      className={cn(shape, 'group outline-none transition-[transform,box-shadow,border-color] duration-200',
        'hover:-translate-y-0.5 hover:shadow-[0_1px_2px_color-mix(in_srgb,var(--shadow-c)_6%,transparent),0_18px_34px_-22px_color-mix(in_srgb,var(--brand)_45%,transparent)] focus-visible:ring-3 focus-visible:ring-ring/40',
        look.text, look.hover)}>
      {body}
    </Link>
  )
}

export function KpiSkeleton() {
  return (
    <Card className="flex h-full flex-col gap-2.5 px-4.5 pt-4.5 pb-4" aria-hidden="true">
      <div className="flex items-center gap-2.5"><Skeleton className="size-9 rounded-full" /><Skeleton className="h-3.5 w-1/2" /></div>
      <Skeleton className="h-7 w-1/2" />
      <Skeleton className="h-9 w-full" />
      <Skeleton className="h-3 w-5/6" />
    </Card>
  )
}
