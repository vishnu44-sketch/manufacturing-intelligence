// One saved answer, as it shows in a chat or on its own (/q/<id>): the status chip, the
// answer, "Understood as", the backup-model note, the one-time token notice, "Time taken" (folded),
// the SQL (folded), the sources (folded, 📄 for a PDF page), and under the card the rows from
// /api/questions/<id>/rows: a chart when they fit one, else (or on "Table") the rows table.
// Only an answered data question has SQL, rows and the Excel download. A general answer (a question not about
// the company, e.g. "what is GST?", answered by the AI itself) has a label that it is not from company data, and
// its paragraphs and simple "- " / "1. " lists are drawn as paragraphs and lists.
// Drawn with Tailwind + shadcn/ui (src/components/ui); the status chips, error boxes and the token
// notice keep their app.css look (as on History). Colours are token classes only (light and dark theme).
import { Suspense, lazy, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChartColumnBig, Check, ChevronRight, Copy, ExternalLink, Info, Table2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ApiError, AuthError, api, problemText } from '../api'
import { chartAskedFromText, chartWish, namesChartKind, pickChart, splitSeries, unusualChartFromText, uprightWish } from '../charts/pickChart'
import type { AiChartReply, Card, Rows, Status } from '../types'
import { copyText } from '../lib/clipboard'
import { ExcelLink } from './common'
import { handOffSql } from './sqlTabModel'
import { Button, buttonVariants } from './ui/button'
import { Card as Box, CardContent } from './ui/card'
import { Dots } from './ui/dots'
import { Segmented, SegmentedItem } from './ui/segmented'
import { Skeleton } from './ui/skeleton'
import { Spinner } from './ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table'

const CHIPS: Record<Status, [string, string]> = {
  ok: ['ok', 'ANSWERED'],
  docs: ['doc', 'FROM DOCUMENTS'],
  nodata: ['info', 'DATA NOT AVAILABLE'],
  refused: ['skip', 'NOT A COMPANY DATA QUESTION'],
  error: ['fail', 'NOT ANSWERED'],
  memory: ['ok', 'MEMORY UPDATED'], // old "Remember that ..." answers (the user memory was removed 19-Nov)
  general: ['info', 'GENERAL ANSWER'], // not about the company: the AI's own answer - no SQL, rows or Excel
}

/** A part of a general answer: a paragraph (its lines), a "- " list or a "1. " list (with its first number). */
type TextBlock =
  | { kind: 'p'; lines: string[] }
  | { kind: 'ul'; items: string[] }
  | { kind: 'ol'; items: string[]; start: number }

const BULLET = /^\s*[-*•]\s+(.*)$/
const NUMBERED = /^\s*(\d{1,3})[.)]\s+(.*)$/

/** Splits an answer into paragraphs (an empty line ends one) and simple lists: lines that start with "- " (or
 *  "* ", "• ") make a bulleted list, lines that start with "1. " (or "1) ") a numbered list. Only text comes
 *  out - React writes it as text, so nothing in the answer can become HTML. */
function textBlocks(text: string): TextBlock[] {
  const blocks: TextBlock[] = []
  for (const raw of text.replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.trim()
    const last = blocks[blocks.length - 1]
    if (!line) {
      if (last && last.kind === 'p' && last.lines.length > 0) blocks.push({ kind: 'p', lines: [] }) // ends the paragraph
      continue
    }
    const bullet = BULLET.exec(line)
    const numbered = bullet ? null : NUMBERED.exec(line)
    if (bullet) {
      if (last && last.kind === 'ul') last.items.push(bullet[1])
      else blocks.push({ kind: 'ul', items: [bullet[1]] })
    } else if (numbered) {
      if (last && last.kind === 'ol') last.items.push(numbered[2])
      else blocks.push({ kind: 'ol', items: [numbered[2]], start: Number(numbered[1]) })
    } else if (last && last.kind === 'p') {
      last.lines.push(line)
    } else {
      blocks.push({ kind: 'p', lines: [line] })
    }
  }
  return blocks.filter((block) => block.kind !== 'p' || block.lines.length > 0)
}

/** A general answer: its paragraphs and lists, with a little space between them. */
function GeneralText({ text }: { text: string }) {
  return (
    <div className="flex flex-col gap-2">
      {textBlocks(text).map((block, i) => block.kind === 'p' ? (
        <p key={i}>{block.lines.map((line, j) => <span key={j}>{j > 0 && <br />}{line}</span>)}</p>
      ) : block.kind === 'ul' ? (
        <ul key={i} className="list-disc space-y-0.5 pl-5 marker:text-muted-foreground">
          {block.items.map((item, j) => <li key={j}>{item}</li>)}
        </ul>
      ) : (
        <ol key={i} start={block.start} className="list-decimal space-y-0.5 pl-6 marker:text-muted-foreground">
          {block.items.map((item, j) => <li key={j}>{item}</li>)}
        </ol>
      ))}
    </div>
  )
}

function sourceChip(kind: string): string {
  return kind === 'example' ? 'ok' : kind === 'rule' ? 'skip' : kind === 'pdf' ? 'doc' : 'info'
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`
}

function stepSecs(secs: number): string {
  return secs < 0.1 ? secs.toFixed(2) : secs.toFixed(1)
}

/** The one-time token notice: fades away after 20 seconds, as on the page. */
function TokenNotice({ text }: { text: string }) {
  const [phase, setPhase] = useState<'shown' | 'fading' | 'gone'>('shown')
  useEffect(() => {
    const fade = window.setTimeout(() => setPhase('fading'), 20000)
    const gone = window.setTimeout(() => setPhase('gone'), 20900)
    return () => { window.clearTimeout(fade); window.clearTimeout(gone) }
  }, [])
  if (phase === 'gone') return null
  return <div className={`token-notice${phase === 'fading' ? ' fading' : ''}`} role="status">{text}</div>
}

/** A folded part of the card (Time taken / Show SQL / Sources used): the summary with a turning arrow. */
function Fold({ summary, children }: { summary: ReactNode; children: ReactNode }) {
  return (
    <details className="group/fold">
      <summary className={cn('inline-flex cursor-pointer list-none items-center gap-1 rounded-md py-0.5 pr-1.5 text-[12.5px] font-semibold text-heading',
        'transition-colors select-none hover:text-primary [&::-webkit-details-marker]:hidden')}>
        <ChevronRight aria-hidden="true" className="size-3.5 text-muted-foreground transition-transform group-open/fold:rotate-90" />
        {summary}
      </summary>
      <div className="pt-1.5 pl-[18px]">{children}</div>
    </details>
  )
}

/** "Loading…" (rows, chart) with the pulsing dots. */
function Wait({ children }: { children: ReactNode }) {
  return <div className="flex items-center gap-2 px-0.5 py-1 text-[12.5px] text-muted-foreground" role="status"><Dots />{children}</div>
}

type RowsState = { state: 'idle' } | { state: 'loading' } | { state: 'done'; rows: Rows } | { state: 'failed'; message: string }
type AiState = { state: 'idle' } | { state: 'loading' } | { state: 'done'; reply: AiChartReply } | { state: 'failed'; message: string }

// the chart is drawn in the browser from the rows (0 AI tokens); ECharts loads only when a chart is shown
const AnswerChart = lazy(() => import('../charts/AnswerChart'))
// a chart the app cannot draw itself (a sankey, a gauge ...): made by the AI on a click (uses AI tokens)
const AiChart = lazy(() => import('../charts/AiChart'))

/** "Make this chart with AI": the button, the wait, the friendly error, or the AI's chart. */
function AiChartAsk({ card, kind }: { card: Card; kind: string }) {
  const [ai, setAi] = useState<AiState>({ state: 'idle' })
  const make = () => {
    setAi({ state: 'loading' })
    api.aiChart(card.id, kind)
      .then((reply) => setAi({ state: 'done', reply }))
      .catch((error) => {
        if (error instanceof AuthError) return // the app shows the Login page
        setAi({ state: 'failed', message: problemText(error, 'The AI chart could not be made - the table below has the rows.') })
      })
  }
  if (ai.state === 'done') {
    return (
      <Suspense fallback={<Wait>Drawing the chart…</Wait>}>
        <AiChart option={ai.reply.option} kind={kind} title={card.understood_as || card.text}
          tokens={ai.reply.tokens} recorded={ai.reply.recorded} />
      </Suspense>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
      {ai.state === 'loading' ? (
        <Wait>Making the {kind} with AI…</Wait>
      ) : (
        <>
          <Button type="button" variant="outline" size="sm" onClick={make}>Make this chart with AI</Button>
          <span className="text-[12.5px] text-muted-foreground">A {kind} is not one of the built-in charts - the AI can draw it from the rows (uses AI tokens).</span>
        </>
      )}
      {ai.state === 'failed' && <div className="errbox basis-full" role="alert">{ai.message}</div>}
    </div>
  )
}

/** The SQL of an answer with its buttons: "Copy SQL" (everyone; a tick and "Copied" for 2 seconds) and, for
 *  admins, "Open in SQL page" (a new browser tab with this SQL in a new editor tab, to change and run it). */
function SqlBox({ sql, staff }: { sql: string; staff: boolean }) {
  const [copied, setCopied] = useState<'' | 'yes' | 'no'>('')
  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(''), copied === 'yes' ? 2000 : 4000)
    return () => window.clearTimeout(timer)
  }, [copied])
  const copy = async () => setCopied((await copyText(sql)) ? 'yes' : 'no')
  const open = () => {
    if (handOffSql(sql)) window.open('/sql', '_blank', 'noopener')
  }
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center justify-end gap-1.5">
        {copied === 'no' && (
          <span role="alert" className="mr-auto text-[12px] text-destructive">The SQL could not be copied in this browser.</span>
        )}
        <Button type="button" variant="outline" size="xs" onClick={copy} aria-label={copied === 'yes' ? 'Copied' : 'Copy SQL'}
                className={cn('gap-1', copied === 'yes' && 'text-success hover:text-success')}>
          {copied === 'yes'
            ? <><Check aria-hidden="true" className="size-3.5" />Copied</>
            : <><Copy aria-hidden="true" className="size-3.5" />Copy SQL</>}
        </Button>
        {staff && (
          <Button type="button" variant="outline" size="xs" onClick={open} className="gap-1"
                  title="Open this SQL in a new tab of the SQL page, to change and run it">
            <ExternalLink aria-hidden="true" className="size-3.5" />Open in SQL page
          </Button>
        )}
      </div>
      <pre className="sql">{sql}</pre>
    </div>
  )
}

export default function AnswerCard({ card, autoRows = false, staff = false }:
  { card: Card; autoRows?: boolean; staff?: boolean }) {
  const [rows, setRows] = useState<RowsState>({ state: 'idle' })
  const autoLoaded = useRef(false) // once only (React's dev mode runs every effect twice)
  // a general answer never has rows, SQL or Excel (even if a card said it had)
  const general = card.status === 'general'
  const hasRows = card.has_rows && !general

  const loadRows = useCallback(() => {
    setRows({ state: 'loading' })
    api.rows(card.rows_url)
      .then((data) => setRows({ state: 'done', rows: data }))
      .catch((error) => {
        if (error instanceof AuthError) return // the app shows the Login page
        setRows({ state: 'failed', message: error instanceof ApiError ? error.message : 'The rows could not be loaded.' })
      })
  }, [card.rows_url])

  // the newest answer (and the one just asked) loads its rows at once; older ones on "Show rows"
  useEffect(() => {
    if (autoRows && hasRows && !autoLoaded.current) {
      autoLoaded.current = true
      loadRows()
    }
  }, [autoRows, hasRows, loadRows])

  const [chipClass, chipText] = CHIPS[card.status] ?? CHIPS.error
  const loaded = rows.state === 'done' ? rows.rows : null
  const rowCount = loaded && !loaded.rows_error ? loaded.row_count : rows.state === 'idle' ? card.row_count : null
  // a chart when the rows fit one (months -> line, names -> bar, parts of a whole -> donut); the table is one click away.
  // 19-Nov: the AI decides - chart_kind 'none' (no chart makes this answer clearer) shows the TABLE first, the Chart
  // switch stays when the rows fit one; a kind -> that chart first; '' (older answers) -> a chart when the rows fit
  const [picked, setView] = useState<'chart' | 'table' | null>(null) // null = not switched by the user yet
  const view = picked ?? (card.chart_kind === 'none' ? 'table' : 'chart')
  // 19-Nov: the columns the AI named to draw (card.chart_columns) - pickChart uses them when the rows have them
  const chartColumns = card.chart_columns ?? null
  // 23-Nov: or one chart per series (splitSeries), e.g. each series with its own value column
  const hasChart = useMemo(
    () => !!loaded && !loaded.rows_error && (pickChart(loaded.headers, loaded.rows, null, null, false, chartColumns) !== null
      || splitSeries(loaded.headers, loaded.rows, null, false, chartColumns) !== null),
    [loaded, chartColumns])
  const wish = `${card.text} ${card.understood_as}`
  // the kind to draw: the one the AI named (card.chart_kind), else the one the words ask for, else pickChart's best
  const wishedKind = chartWish(card.chart_kind, wish)
  const upright = uprightWish(card.chart_kind, wish) // a column chart: bars stand upright even with long names
  const unusual = unusualChartFromText(wish) // e.g. a sankey: the "Make this chart with AI" button
  // a chart was asked for (in words, or the AI named a kind) but the rows fit none (e.g. 1 row): a short note says
  // why, instead of no chart at all (a chart only the AI can draw has its own button and text)
  const noChartNote = loaded && !loaded.rows_error && loaded.rows.length > 0 && !hasChart && !unusual
    && (chartAskedFromText(wish) || namesChartKind(card.chart_kind))
    ? (loaded.rows.length === 1 ? 'Only 1 row, so no chart can be drawn.' : "This answer can't be drawn as a chart.")
    : ''
  const folds = card.time_steps.length > 0 || (hasRows && card.sql) || card.sources.length > 0

  return (
    <>
      <Box>
        <CardContent className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className={`chip ${chipClass}`}>{chipText}</span>
            <span className="text-[12.5px] text-muted-foreground tabular-nums">
              {hasRows && rowCount != null && `${plural(rowCount, 'row')} · `}
              {card.secs.toFixed(1)} s{card.tries > 1 && ` · ${card.tries} tries`}
            </span>
            {hasRows && (
              <span className="ml-auto flex flex-wrap items-center gap-1.5 max-[700px]:ml-0">
                {rows.state === 'idle' && (
                  <Button type="button" variant="outline" size="sm" onClick={loadRows}>Show rows</Button>
                )}
                <ExcelLink url={card.excel_url} busyIcon={<Spinner />}
                           className={cn(buttonVariants({ variant: 'outline', size: 'sm' }),
                             'text-foreground! hover:text-primary! aria-busy:pointer-events-none aria-busy:opacity-80')}>
                  Download Excel
                </ExcelLink>
              </span>
            )}
          </div>
          {card.understood_as && <div className="text-xs text-muted-foreground italic">Understood as: {card.understood_as}</div>}
          {general && (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Info aria-hidden="true" className="size-3.5 flex-none text-info" />General answer – not from company data
            </div>
          )}
          <div className="text-[15px] leading-[1.65] text-foreground [overflow-wrap:anywhere]">
            {general ? <GeneralText text={card.answer} /> : card.answer.split('\n').map((line, i) => (
              <span key={i}>{i > 0 && <br />}{line}</span>
            ))}
          </div>
          {/* 18-Nov: which model answered and why, when it was not the first model of the chain (a limit, a busy
              model, an administrator's choice); older answers only know the backup model's name */}
          {card.model_note ? (
            <div className="flex items-start gap-1.5 text-[12.5px] text-muted-foreground" data-model-line="">
              <Info aria-hidden="true" className="mt-[3px] size-3.5 flex-none" />
              <span>Answered by {card.model_label || 'another model'} - {card.model_note.replace(/[.\s]+$/, '')}.</span>
            </div>
          ) : card.backup_model && (
            <div className="text-[12.5px] text-muted-foreground italic">
              Answered by the backup model ({card.backup_model}) - the main model's daily limit was reached.
            </div>
          )}
          {card.token_notice && <div><TokenNotice text={card.token_notice} /></div>}
          {folds && (
            <div className="mt-1 flex flex-col gap-1.5 border-t border-border pt-2.5">
              {card.time_steps.length > 0 && (
                <Fold summary={<>Time taken: {card.secs.toFixed(1)} s</>}>
                  <table className="w-[min(360px,100%)] text-[12.5px]">
                    <tbody>
                      {card.time_steps.map((step) => (
                        <tr key={step.label} className="border-b border-border last:border-b-0">
                          <td className="py-1 pr-6">{step.label}{step.note && <> <span className="text-muted-foreground">({step.note})</span></>}</td>
                          <td className="num py-1 text-right whitespace-nowrap tabular-nums">{stepSecs(step.secs)} s</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Fold>
              )}
              {hasRows && card.sql && (
                <Fold summary="Show SQL">
                  <SqlBox sql={card.sql} staff={staff} />
                </Fold>
              )}
              {card.sources.length > 0 && (
                <Fold summary={<>Sources used ({card.sources.length})</>}>
                  <div className="sources">
                    {card.sources.map((source, i) => (
                      <div className="src" key={i}>
                        <span className={`chip ${sourceChip(source.kind)}`}>{source.kind.toUpperCase()}</span>{' '}
                        {source.kind === 'pdf' && '📄 '}{source.heading}
                      </div>
                    ))}
                  </div>
                </Fold>
              )}
            </div>
          )}
        </CardContent>
      </Box>

      {hasRows && rows.state === 'loading' && (
        <div className="flex flex-col gap-2">
          <Wait>Loading the rows…</Wait>
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full opacity-70" />
          <Skeleton className="h-9 w-4/5 opacity-50" />
        </div>
      )}
      {hasRows && rows.state === 'failed' && <div className="errbox">{rows.message}</div>}
      {loaded && !loaded.rows_error && loaded.rows.length > 0 && unusual && <AiChartAsk card={card} kind={unusual} />}
      {loaded && (loaded.rows_error ? (
        <div className="errbox">{loaded.rows_error}</div>
      ) : loaded.rows.length > 0 && hasChart && view === 'chart' ? (
        <Suspense fallback={<Wait>Drawing the chart…</Wait>}>
          <AnswerChart headers={loaded.headers} rows={loaded.rows} title={card.understood_as || card.text}
            kind={wishedKind} upright={upright} columns={chartColumns}
            onShowTable={() => setView('table')} />
        </Suspense>
      ) : loaded.rows.length > 0 ? (
        <>
          {noChartNote && <div className="text-[12.5px] text-muted-foreground" role="status">{noChartNote}</div>}
          <Box className="overflow-hidden">
            {hasChart && (
              // the same Chart | Table switch as on the chart (here "Table" is on)
              <div className="flex justify-end border-b border-border px-3 py-2">
                <Segmented aria-label="Show the answer as">
                  <SegmentedItem pressed={false} aria-label="Show chart" onClick={() => setView('chart')}>
                    <ChartColumnBig aria-hidden="true" />Chart
                  </SegmentedItem>
                  <SegmentedItem pressed><Table2 aria-hidden="true" />Table</SegmentedItem>
                </Segmented>
              </div>
            )}
            <Table containerClassName="max-h-[min(460px,70vh)]">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  {loaded.headers.map((h, i) => <TableHead key={i} className={h.num ? 'num text-right' : undefined}>{h.name}</TableHead>)}
                </TableRow>
              </TableHeader>
              <TableBody>
                {loaded.rows.map((row, r) => (
                  <TableRow key={r}>
                    {row.map((cell, c) => (
                      <TableCell key={c} className={cell.num ? 'num text-right whitespace-nowrap tabular-nums' : undefined}>{cell.text}</TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
          {loaded.truncated && <div className="text-[12.5px] text-muted-foreground">Only the first 500 rows are shown (and in the Excel file).</div>}
        </>
      ) : (
        <Box><CardContent className="text-[12.5px] text-muted-foreground">The query ran but returned no rows.</CardContent></Box>
      ))}
    </>
  )
}
