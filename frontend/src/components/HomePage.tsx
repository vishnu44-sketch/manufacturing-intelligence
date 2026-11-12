// Home (/, every user): the first page after signing in. From the top:
// - the welcome banner (HomeHero.tsx): the greeting, the India-time clock, the NOP sales month we are in and the
//   FY, and a quick start with example questions;
// - the KPI cards (HomeKpiCards.tsx, each with its own look: net sales, customers, products, open orders,
//   stock, the top customer and product - never after today): the number counting up the first time it
//   shows, a small picture of the last NOP months (or a few short facts as chips), the change; a click opens
//   the Ask page with a question about that number filled in (nothing is asked until Ask is pressed);
// - the user's last questions (a click opens the saved answer - no AI call) and the user's usage today;
// - what the app is connected to (names and a green / red dot), the main tables with their records and
//   dates, and how a question is answered step by step.
// Everything comes from one read-only call (/api/home, no AI call). A part that cannot be read shows its own small
// message and the rest of the page still works (e.g. MySQL down: the KPI cards say so, the rest stays). An older
// server without "trend", "ask", "facts", "name" or "recent" still works: those parts just do not show.
// The card grids choose their columns from how many cards there are (8 KPI cards: 4 a row, 6: 3 a row), so the
// last row is never left half empty, and every card in a row is as tall as the tallest.
// Drawn with Tailwind + shadcn/ui (Card, Button, Badge, Progress, Separator, Skeleton); the page's root has the
// class "ui-scope" (see src/tailwind.css). app.css colours every <a> outside a cascade layer: the links' own
// colours are marked (!). app.css also stops every animation when the person asked for less motion.
import {
  ArrowRight, BookOpenText, Bot, CalendarRange, ChartColumn, ChevronRight, CircleAlert, ClipboardList, CodeXml,
  Database, FileText, History, type LucideIcon, MessageSquareText, Package, Plug, ReceiptText, ShieldCheck, Sparkles,
  Users, Warehouse,
} from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { AuthError, api, problemText } from '../api'
import { Link, questionPath } from '../router'
import HomeFeatures from './HomeFeatures'
import HomeHero from './HomeHero'
import { KpiCard, KpiSkeleton } from './HomeKpiCards'
import type { HomeConnection, HomeData, HomeRecent, HomeTable, HomeUsage, Me } from '../types'

// the small type styles the page repeats
const CAPTION = 'text-[11px] font-semibold tracking-[.06em] uppercase text-muted-foreground'
const TITLE = 'm-0 text-[15px] font-semibold text-heading'
const NOTE = 'text-xs leading-relaxed text-muted-foreground'
const ERROR_BOX = 'flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/10 px-3.5 py-2.5 text-[13px] leading-snug text-destructive'

// The card grids. A grid measures the room it has (a container query: its wrapper has the class "@container"),
// not the window: the left menu (236 px, 72 px when slim) and the page's padding leave the content much
// narrower than the window. 1 column on a phone, 2 from 440 px, and the wide count of columns from where
// its cards are still wide enough. The class names are written out in full so Tailwind finds them.
const STEPS: Record<number, string> = {
  1: '',
  2: '@min-[440px]:grid-cols-2',
  3: '@min-[440px]:grid-cols-2 @min-[720px]:grid-cols-3',
  4: '@min-[440px]:grid-cols-2 @min-[900px]:grid-cols-4',
  5: '@min-[440px]:grid-cols-2 @min-[1100px]:grid-cols-5',
}
// an odd number of cards at 2 columns: the last one would stand alone, so it takes the whole row (until the
// wide step)
const ODD_LAST: Record<number, string> = {
  3: '@min-[440px]:[&>*:last-child]:col-span-2 @min-[720px]:[&>*:last-child]:col-span-1',
  4: '@min-[440px]:[&>*:last-child]:col-span-2 @min-[900px]:[&>*:last-child]:col-span-1',
  5: '@min-[440px]:[&>*:last-child]:col-span-2 @min-[1100px]:[&>*:last-child]:col-span-1',
}
// exactly 5 cards (the connections), between 2 columns and 5 in a row: 3 on the first row and 2 wider ones
// below it (a grid of 6 narrow columns: the first 3 cards take 2 each, the last 2 take 3 each)
const FIVE_MIDDLE = '@min-[720px]:grid-cols-6 @min-[720px]:[&>*]:col-span-2 @min-[720px]:[&>*:nth-child(n+4)]:col-span-3 '
  + '@min-[1100px]:[&>*]:col-span-1 @min-[1100px]:[&>*:nth-child(n+4)]:col-span-1'

/** How many columns a grid of `count` cards gets on a wide screen: of 2 to `most` columns, the one that leaves
 *  the fewest empty places in the last row (the most columns when two leave as few). 8 cards, up to 4: 4 a
 *  row; 6 cards: 3 a row; 5 cards, up to 5: all 5 in a row. */
export function wideColumns(count: number, most: number): number {
  if (count <= 1) return 1
  let best = 1
  let fewest = Infinity
  for (let cols = Math.min(most, count, 5); cols >= 2; cols--) {
    const empty = (cols - (count % cols)) % cols
    if (empty < fewest) { best = cols; fewest = empty }
  }
  return best
}

/** The classes of a grid of `count` cards with up to `most` columns on a wide screen. */
export function gridClass(count: number, most: number): string {
  const cols = wideColumns(count, most)
  return ['grid', STEPS[cols],
    count % 2 === 1 && cols > 2 ? ODD_LAST[cols] : '',
    count === 5 && cols === 5 ? FIVE_MIDDLE : '',
  ].filter(Boolean).join(' ')
}

/** A grid of cards in its own measuring box (see STEPS). The cards in a row stretch to the same height. */
function CardGrid({ count, most, className, label, list, grid, children }:
  { count: number; most: number; className?: string; label?: string; list?: boolean; grid?: string; children: ReactNode }) {
  const Tag = list ? 'ul' : 'div'
  return (
    <div className="@container min-w-0">
      <Tag className={`${gridClass(count, most)} ${className ?? ''}`.trim()} data-columns={wideColumns(count, most)}
        data-grid={grid} aria-label={list ? label : undefined}>
        {children}
      </Tag>
    </div>
  )
}

// the soft colour circles of the icons (text colour = the icon). "brand" is the blue brand tint; "danger" is
// real red, only for something that is down. Every tone is a token or a light / dark pair.
const TONES = {
  brand: 'bg-primary-soft text-primary',
  danger: 'bg-destructive/10 text-destructive',
  blue: 'bg-info-soft text-info',
  green: 'bg-success-soft text-success',
  amber: 'bg-warning-soft text-warning',
  purple: 'bg-violet-500/12 text-violet-700 dark:bg-violet-400/15 dark:text-violet-300',
  grey: 'bg-secondary text-heading',
}
type Tone = keyof typeof TONES

// how a question is answered, step by step (what the Ask page shows while it works): the title, a short line
// shown under it, and the longer explanation (on hover, and read out by screen readers)
const FLOW: [LucideIcon, string, string, string][] = [
  [MessageSquareText, 'Your question', 'in plain English',
    'You type a question in plain English. A follow-up ("and last month?") is first written out in full, so it can be answered on its own.'],
  [BookOpenText, 'Find the notes', 'RAG in Qdrant',
    'RAG: the notes closest to the question (our tables, columns and rules) are found in Qdrant and given to the AI.'],
  [CodeXml, 'AI writes the SQL', 'one read-only SELECT',
    'The AI model (Groq) writes one read-only SELECT from the question and the notes.'],
  [ShieldCheck, 'SQL guard', 'our own check',
    'Our own check reads the SQL before it runs: one SELECT only, only the allowed tables, nothing that changes data.'],
  [Database, 'Read-only MySQL', 'ai_gold, 30 s limit',
    'The SQL runs on MySQL ai_gold with a read-only user and a 30 second limit.'],
  [ChartColumn, 'Answer, chart, Excel', 'ready to use',
    'The AI writes a short answer from the rows; you also get the table, a chart and an Excel download.'],
]

// the label and look of a recent question's status
const STATUS: Record<string, [string, 'success' | 'info' | 'secondary' | 'warning' | 'destructive']> = {
  ok: ['Answered', 'success'],
  docs: ['From documents', 'info'],
  memory: ['From memory', 'info'],
  nodata: ['No data', 'secondary'],
  refused: ['Refused', 'warning'],
  error: ['Failed', 'destructive'],
}

export { greeting } from './HomeHero'

/** A token count written short: '143,064' -> '143k', '1,250,000' -> '1.3M', '950' -> '950'. Text that is not a
 *  number comes back as it is. */
export function shortTokens(text: string): string {
  const n = Number(String(text).replace(/,/g, '').trim())
  if (!String(text).trim() || !Number.isFinite(n)) return text
  const one = (x: number) => x.toLocaleString('en-US', { maximumFractionDigits: 1 })
  if (Math.abs(n) >= 1e6) return `${one(n / 1e6)}M`
  if (Math.abs(n) >= 1e4) return `${Math.round(n / 1e3)}k`
  if (Math.abs(n) >= 1e3) return `${one(n / 1e3)}k`
  return String(n)
}

/** The colour of the usage bar: green, amber above 70%, real red (not the brand) above 90%. */
export function usageColour(pct: number): string {
  return pct > 90 ? 'bg-destructive' : pct > 70 ? 'bg-warning' : 'bg-success'
}

/** A section of the page: a title (and an optional line or link beside it) above its content. */
function Section({ title, aside, children, label, className }:
  { title: string; aside?: ReactNode; children: ReactNode; label?: string; className?: string }) {
  return (
    <section aria-label={label ?? title} className={cn('flex min-w-0 flex-col gap-2.5', className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <h2 className={TITLE}>{title}</h2>
        {aside && <span className={NOTE}>{aside}</span>}
      </div>
      {children}
    </section>
  )
}

function PartError({ children }: { children: ReactNode }) {
  return (
    <div className={ERROR_BOX} role="alert">
      <CircleAlert aria-hidden="true" className="mt-px size-4 flex-none" />
      <span>{children}</span>
    </div>
  )
}

/** An icon in a soft coloured circle. */
function IconCircle({ icon: Icon, tone, className }: { icon: LucideIcon; tone: Tone; className?: string }) {
  return (
    <span aria-hidden="true" className={cn('flex size-9 flex-none items-center justify-center rounded-full', TONES[tone], className)}>
      <Icon className="size-[18px]" />
    </span>
  )
}

// ------------------------------------------------------------------------------------------------ recent questions

function RecentRow({ item }: { item: HomeRecent }) {
  const [label, variant] = STATUS[item.status] ?? [item.status || 'Asked', 'secondary']
  return (
    <li data-recent={item.id}>
      <Link to={item.url || questionPath(item.id)} title={item.text}
        className="group flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-heading! outline-none transition-colors hover:bg-muted hover:text-heading! focus-visible:bg-muted focus-visible:ring-3 focus-visible:ring-ring/40 focus-visible:ring-inset max-[760px]:px-3.5">
        <span className="min-w-0 basis-full truncate text-[13.5px] font-medium group-hover:text-primary min-[560px]:basis-0 min-[560px]:flex-1">{item.text}</span>
        <Badge variant={variant} data-status={item.status}>
          <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />{label}
        </Badge>
        <span className="text-xs whitespace-nowrap text-muted-foreground">{item.when}</span>
        <ChevronRight aria-hidden="true" className="size-4 flex-none text-faint group-hover:text-primary max-[559px]:ml-auto" />
      </Link>
    </li>
  )
}

function Recent({ data, examples }: { data: HomeData; examples: string[] }) {
  if (data.recent_error) return <PartError>Your recent questions can't be read right now. {data.recent_error}</PartError>
  // an older server sends no "recent": point to History instead
  if (!data.recent) {
    return (
      <Card className="flex items-center gap-3 px-5 py-4 max-[760px]:px-3.5">
        <IconCircle icon={History} tone="grey" />
        <span className="text-[13px] text-muted-foreground">Your earlier questions and their answers are in <Link to="/history" className="font-medium text-primary! hover:underline">History</Link>.</span>
      </Card>
    )
  }
  if (!data.recent.length) {
    return (
      <Card className="flex flex-col gap-3 px-5 py-4.5 max-[760px]:px-3.5" data-recent-empty="">
        <div className="flex items-center gap-3">
          <IconCircle icon={Sparkles} tone="brand" />
          <div>
            <div className="text-[14px] font-semibold text-heading">No questions yet - try one of these</div>
            <div className={NOTE}>The Ask page opens with the question filled in; nothing is asked until you press Ask.</div>
          </div>
        </div>
        {examples.length > 0 && (
          <ul className="flex flex-col gap-1.5" aria-label="Example questions">
            {examples.map((example) => (
              <li key={example}>
                <Link to={`/new?q=${encodeURIComponent(example)}`}
                  className="flex items-center gap-2 rounded-lg border border-border bg-muted px-3 py-2 text-[13px] text-heading! outline-none transition-colors hover:border-primary/40 hover:text-primary! focus-visible:ring-3 focus-visible:ring-ring/40">
                  <ArrowRight aria-hidden="true" className="size-3.5 flex-none text-primary" />
                  <span className="min-w-0 [overflow-wrap:anywhere]">{example}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    )
  }
  return (
    <Card className="overflow-hidden">
      <ul className="divide-y divide-border" aria-label="Your recent questions">
        {data.recent.slice(0, 5).map((item) => <RecentRow key={item.id} item={item} />)}
      </ul>
    </Card>
  )
}

// ------------------------------------------------------------------------------------------------ usage

function Stat({ icon, label, value }: { icon: LucideIcon; label: string; value: ReactNode }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <IconCircle icon={icon} tone="grey" />
      <div className="min-w-0">
        <div className={CAPTION}>{label}</div>
        <div className="text-[21px] leading-tight font-semibold text-heading tabular-nums">{value}</div>
      </div>
    </div>
  )
}

function Usage({ usage }: { usage: HomeUsage }) {
  const pct = Number.isFinite(usage.pct) ? usage.pct : 0
  const colour = usageColour(pct)
  const tone = pct > 90 ? 'destructive' : pct > 70 ? 'warning' : 'success'
  return (
    <Card className="flex flex-col gap-4 px-5 py-4.5 max-[760px]:px-3.5">
      <div className="grid grid-cols-2 gap-3 max-[400px]:grid-cols-1">
        <Stat icon={MessageSquareText} label="Questions today" value={usage.questions_today} />
        <Stat icon={Sparkles} label="Your AI tokens today" value={usage.my_tokens_text} />
      </div>
      <Separator />
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <span className="text-[13px] font-medium text-heading">AI tokens, last 24 hours (whole app)</span>
          <Badge variant={tone} data-pct="">{pct}%</Badge>
        </div>
        <div className="text-[15px] font-semibold text-heading">
          {shortTokens(usage.tokens_24h)} <span className="font-normal text-muted-foreground">of</span> {shortTokens(usage.limit)} <span className="font-normal text-muted-foreground">tokens</span>
        </div>
        <Progress value={pct} aria-label="AI tokens of the daily limit" className="h-2.5" indicatorClassName={colour} />
        <div className={NOTE}>
          {usage.tokens_24h} of {usage.limit} tokens · {usage.model} · the daily limit Groq counts over the last 24 hours
          {usage.period_end ? ` · today's period: ${usage.period_tokens} tokens, resets ${usage.period_end}` : ''}
        </div>
      </div>
    </Card>
  )
}

// ------------------------------------------------------------------------------------------------ connections

function connectionIcon(key: string): LucideIcon {
  if (key === 'groq') return Bot
  if (key === 'docs') return BookOpenText
  if (key === 'pdfs') return FileText
  if (key === 'ai_gold' || key === 'app_db') return Database
  return Plug
}

/** A green dot that pulses gently (connected), or a red one. */
function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span aria-hidden="true" data-dot={ok ? 'ok' : 'down'} className="relative flex size-2.5 flex-none">
      {ok && <span className="absolute inset-0 animate-ping rounded-full bg-success opacity-50 [animation-duration:2.4s] motion-reduce:animate-none" />}
      <span className={cn('relative size-2.5 rounded-full', ok ? 'bg-success' : 'bg-destructive')} />
    </span>
  )
}

function Connections({ lines }: { lines: HomeConnection[] }) {
  return (
    <CardGrid list count={lines.length} most={5} className="gap-3" label="Connections" grid="connections">
      {lines.map((line) => (
        <li key={line.key} className="min-w-0">
          <Card className="flex h-full items-start gap-3 px-4 py-3.5" data-connection={line.key}>
            <IconCircle icon={connectionIcon(line.key)} tone={line.ok ? 'grey' : 'danger'} className="rounded-lg" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 text-[13px] font-semibold text-heading [overflow-wrap:anywhere]">{line.name}</span>
                <StatusDot ok={line.ok} />
              </div>
              <div className="text-[11.5px] leading-snug text-muted-foreground [overflow-wrap:anywhere]">{line.what}</div>
              <div className={cn('mt-1 text-xs font-medium', line.ok ? 'text-success' : 'text-destructive')}>
                <span className="sr-only">{line.ok ? 'Connected: ' : 'Not connected: '}</span>{line.note}
              </div>
            </div>
          </Card>
        </li>
      ))}
    </CardGrid>
  )
}

// ------------------------------------------------------------------------------------------------ our data

function tableIcon(table: string): LucideIcon {
  const t = table.toLowerCase()
  if (t.includes('invoice')) return ReceiptText
  if (t.includes('customer')) return Users
  if (t.includes('order')) return ClipboardList
  if (t.includes('stock') || t.includes('inventory')) return Warehouse
  if (t.includes('product') || t.includes('item')) return Package
  return Database
}

function TableCard({ table, biggest }: { table: HomeTable; biggest: number }) {
  // the thin bar: this table's records against the biggest table's (only for the eye; the number says it)
  const share = biggest > 0 && table.rows > 0 ? Math.max(3, (table.rows / biggest) * 100) : 0
  return (
    <Card className="flex flex-col gap-2 px-4 py-3.5" data-table={table.table}>
      <div className="flex items-center gap-2.5">
        <IconCircle icon={tableIcon(table.table)} tone="blue" className="size-8 rounded-lg" />
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold text-heading">{table.name}</div>
          <code className="block truncate bg-transparent! p-0! text-[10.5px]! text-muted-foreground">{table.table}</code>
        </div>
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-[19px] font-semibold text-heading tabular-nums">{table.rows_text}</span>
        <span className="text-xs text-muted-foreground">records</span>
      </div>
      <Progress value={share} aria-hidden="true" className="h-1.5" indicatorClassName="bg-info/70" />
      {table.from && (
        <div className="flex items-center gap-1.5 text-xs text-heading/80">
          <CalendarRange aria-hidden="true" className="size-3.5 flex-none text-muted-foreground" />
          <span>{table.from} to {table.to}</span>
        </div>
      )}
      <div className={NOTE}>{table.note}</div>
      {table.after_today && (
        <div className="rounded-md bg-warning-soft px-2 py-1 text-[11.5px] leading-snug text-warning">
          Has test rows dated after today - the numbers above stop at today.
        </div>
      )}
    </Card>
  )
}

// ------------------------------------------------------------------------------------------------ how it works

function HowItWorks({ model }: { model: string }) {
  const stack = ['Django', 'React', 'LangChain', 'LangGraph', 'Qdrant', 'FastEmbed', `Groq (${model || 'AI model'})`,
    'MCP server', 'ECharts', 'Tailwind + shadcn']
  // a phone / narrow screen: the steps go down, joined by a line on the left; a wide screen: across, joined by arrows
  return (
    <Card className="flex flex-col gap-5 px-5 py-5 max-[760px]:px-3.5">
      <ol className="flex flex-col min-[1100px]:flex-row" aria-label="How a question is answered">
        {FLOW.map(([Icon, step, detail, explain], i) => {
          const ends = i === 0 || i === FLOW.length - 1
          return (
            <li key={step} title={explain}
              className={cn('relative flex gap-3 pb-5 last:pb-0',
                'min-[1100px]:flex-1 min-[1100px]:flex-col min-[1100px]:items-center min-[1100px]:px-1.5 min-[1100px]:pb-0 min-[1100px]:text-center')}>
              {i < FLOW.length - 1 && (
                <span aria-hidden="true"
                  className={cn('absolute top-11 bottom-1 left-5 w-px bg-border',
                    'min-[1100px]:top-5 min-[1100px]:bottom-auto min-[1100px]:left-[calc(50%+28px)] min-[1100px]:right-[calc(-50%+28px)] min-[1100px]:h-px min-[1100px]:w-auto')}>
                  <ChevronRight className={cn('absolute -bottom-2 left-1/2 size-3.5 -translate-x-1/2 rotate-90 text-faint',
                    'min-[1100px]:-right-2 min-[1100px]:bottom-auto min-[1100px]:left-auto min-[1100px]:top-1/2 min-[1100px]:translate-x-0 min-[1100px]:-translate-y-1/2 min-[1100px]:rotate-0')} />
                </span>
              )}
              <span aria-hidden="true"
                className={cn('relative flex size-10 flex-none items-center justify-center rounded-full border',
                  ends ? 'border-primary/20 bg-primary-soft text-primary' : 'border-border bg-muted text-heading')}>
                <Icon className="size-[18px]" />
              </span>
              <div className="flex min-w-0 flex-col gap-0.5 pt-0.5 min-[1100px]:pt-2">
                <span className="text-[10.5px] font-semibold tracking-[.06em] text-faint uppercase">Step {i + 1}</span>
                <span className="text-[13px] leading-snug font-semibold text-heading">{step}</span>
                <span className="text-[11.5px] leading-snug text-muted-foreground">{detail}</span>
                <span className="sr-only">{explain}</span>
              </div>
            </li>
          )
        })}
      </ol>
      <Separator />
      <div>
        <div className={cn(CAPTION, 'mb-2')}>What we use</div>
        <ul className="flex flex-wrap gap-1.5" aria-label="What we use">
          {stack.map((name) => <li key={name}><Badge variant="outline" className="bg-muted px-2.5 py-1">{name}</Badge></li>)}
        </ul>
      </div>
    </Card>
  )
}

// ------------------------------------------------------------------------------------------------ the page

export default function HomePage({ me }: { me: Me }) {
  const [data, setData] = useState<HomeData | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let gone = false
    api.home()
      .then((reply) => { if (!gone) setData(reply) })
      .catch((err) => { if (!gone && !(err instanceof AuthError)) setError(problemText(err, "The Home page can't be read right now.")) })
    return () => { gone = true }
  }, [])

  const loading = !data && !error
  const name = data?.first_name || me.name.split(' ')[0] || me.username
  const examples = me.examples.slice(0, 3)
  const biggest = Math.max(0, ...(data?.tables ?? []).map((t) => t.rows || 0))

  return (
    <div className="ui-scope flex min-w-0 flex-col gap-7">
      {/* 1. welcome, with the quick start */}
      <HomeHero name={name} calendar={data?.calendar} loading={loading} examples={examples} />

      {/* the two big feature cards: Ask AI and the Knowledge graph (no data needed, so always shown) */}
      <HomeFeatures />

      {error && <PartError>{error}</PartError>}

      {/* 2. the KPI cards */}
      {!error && (
        <Section title="Key numbers" aside="Up to today · net sales = invoices minus credit notes, before GST">
          {loading ? (
            <CardGrid count={8} most={4} className="gap-3.5">{Array.from({ length: 8 }, (_, i) => <KpiSkeleton key={i} />)}</CardGrid>
          ) : data?.kpi_error ? (
            <PartError>The key numbers can't be read right now. {data.kpi_error}</PartError>
          ) : (
            <CardGrid count={data?.kpis.length ?? 0} most={4} className="gap-3.5" grid="kpis">
              {data?.kpis.map((kpi) => <KpiCard key={kpi.key} kpi={kpi} />)}
            </CardGrid>
          )}
        </Section>
      )}

      {/* 3. recent questions and 4. usage, side by side on a wide screen */}
      {!error && (
        <div className="grid items-start gap-7 min-[1100px]:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
          <Section title="Your recent questions"
            aside={<Link to="/history" className="inline-flex items-center gap-1 font-medium text-primary! hover:text-primary! hover:underline">See all in History<ArrowRight aria-hidden="true" className="size-3.5" /></Link>}>
            {loading ? (
              <Card className="flex flex-col gap-3 px-4 py-4">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-5 w-full" />)}</Card>
            ) : data ? <Recent data={data} examples={examples} /> : null}
          </Section>
          <Section title="Your usage">
            {loading ? <Skeleton className="h-52 w-full rounded-xl" />
              : data?.usage ? <Usage usage={data.usage} />
                : <PartError>Your usage can't be read right now.{data?.usage_error ? ` ${data.usage_error}` : ''}</PartError>}
          </Section>
        </div>
      )}

      {/* 5. connections */}
      {!error && (
        <Section title="Connected" aside="Checked every minute">
          {loading ? (
            <CardGrid count={5} most={5} className="gap-3">
              {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-[76px] w-full rounded-xl" />)}
            </CardGrid>
          ) : data?.connections.length ? <Connections lines={data.connections} />
            : <PartError>The connections can't be checked right now.{data?.connections_error ? ` ${data.connections_error}` : ''}</PartError>}
        </Section>
      )}

      {/* 6. our data */}
      {!error && (
        <Section title="Our data" aside="MySQL ai_gold, read-only">
          {loading ? (
            <CardGrid count={6} most={3} className="gap-3.5">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-32 w-full rounded-xl" />)}</CardGrid>
          ) : data?.tables_error ? (
            <PartError>The tables can't be read right now. {data.tables_error}</PartError>
          ) : (
            <CardGrid count={data?.tables.length ?? 0} most={3} className="gap-3.5" grid="tables">
              {data?.tables.map((table) => <TableCard key={table.table} table={table} biggest={biggest} />)}
            </CardGrid>
          )}
        </Section>
      )}

      {/* 7. how it works (no data needed) */}
      <Section title="How it works" aside="Every answer, step by step - point at a step for more">
        <HowItWorks model={data?.model ?? ''} />
      </Section>
    </div>
  )
}
