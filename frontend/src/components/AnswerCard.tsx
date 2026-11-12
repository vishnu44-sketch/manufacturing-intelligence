// One saved answer, as it shows in a chat or on its own (/q/<id>): the status chip, the
// answer, "Understood as", the backup-model note, the one-time token notice, "Time taken" (folded),
// the SQL (folded), the sources (folded, 📄 for a PDF page), and under the card the rows from
// /api/questions/<id>/rows: a chart when they fit one, else (or on "Table") the rows table.
// Only an answered data question has SQL, rows and the Excel download.
// Drawn with Tailwind + shadcn/ui (src/components/ui); the status chips, error boxes and the token
// notice keep their app.css look (as on History). Colours are token classes only (light and dark theme).
import { Suspense, lazy, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChartColumnBig, ChevronRight, Table2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ApiError, AuthError, api, problemText } from '../api'
import { chartAskedFromText, chartKindFromText, pickChart, unusualChartFromText } from '../charts/pickChart'
import { Link } from '../router'
import type { AiChartReply, Card, Rows, Status } from '../types'
import { ExcelLink } from './common'
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
  memory: ['ok', 'SAVED TO MEMORY'], // "Remember that ..." - no SQL, rows or Excel
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

export default function AnswerCard({ card, autoRows = false }: { card: Card; autoRows?: boolean }) {
  const [rows, setRows] = useState<RowsState>({ state: 'idle' })
  const autoLoaded = useRef(false) // once only (React's dev mode runs every effect twice)

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
    if (autoRows && card.has_rows && !autoLoaded.current) {
      autoLoaded.current = true
      loadRows()
    }
  }, [autoRows, card.has_rows, loadRows])

  const [chipClass, chipText] = CHIPS[card.status] ?? CHIPS.error
  const loaded = rows.state === 'done' ? rows.rows : null
  const rowCount = loaded && !loaded.rows_error ? loaded.row_count : rows.state === 'idle' ? card.row_count : null
  // a chart when the rows fit one (months -> line, names -> bar, parts of a whole -> donut); the table is one click away
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const hasChart = useMemo(
    () => !!loaded && !loaded.rows_error && pickChart(loaded.headers, loaded.rows) !== null, [loaded])
  const wish = `${card.text} ${card.understood_as}`
  const unusual = unusualChartFromText(wish) // e.g. a sankey: the "Make this chart with AI" button
  // a chart was asked for but the rows fit none (e.g. 1 row): a short note says why, instead of no chart at all
  // (a chart only the AI can draw has its own button and text)
  const noChartNote = loaded && !loaded.rows_error && loaded.rows.length > 0 && !hasChart && !unusual
    && chartAskedFromText(wish)
    ? (loaded.rows.length === 1 ? 'Only 1 row, so no chart can be drawn.' : "This answer can't be drawn as a chart.")
    : ''
  const folds = card.time_steps.length > 0 || (card.has_rows && card.sql) || card.sources.length > 0

  return (
    <>
      <Box>
        <CardContent className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className={`chip ${chipClass}`}>{chipText}</span>
            <span className="text-[12.5px] text-muted-foreground tabular-nums">
              {card.has_rows && rowCount != null && `${plural(rowCount, 'row')} · `}
              {card.secs.toFixed(1)} s{card.tries > 1 && ` · ${card.tries} tries`}
            </span>
            {card.has_rows && (
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
          <div className="text-[15px] leading-[1.65] text-foreground [overflow-wrap:anywhere]">
            {card.answer.split('\n').map((line, i) => (
              <span key={i}>{i > 0 && <br />}{line}</span>
            ))}
          </div>
          {card.status === 'memory' && (
            <div className="text-[12.5px]"><Link to="/memory">Open the Memory page</Link></div>
          )}
          {card.backup_model && (
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
              {card.has_rows && card.sql && (
                <Fold summary="Show SQL">
                  <pre className="sql">{card.sql}</pre>
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

      {card.has_rows && rows.state === 'loading' && (
        <div className="flex flex-col gap-2">
          <Wait>Loading the rows…</Wait>
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full opacity-70" />
          <Skeleton className="h-9 w-4/5 opacity-50" />
        </div>
      )}
      {card.has_rows && rows.state === 'failed' && <div className="errbox">{rows.message}</div>}
      {loaded && !loaded.rows_error && loaded.rows.length > 0 && unusual && <AiChartAsk card={card} kind={unusual} />}
      {loaded && (loaded.rows_error ? (
        <div className="errbox">{loaded.rows_error}</div>
      ) : loaded.rows.length > 0 && hasChart && view === 'chart' ? (
        <Suspense fallback={<Wait>Drawing the chart…</Wait>}>
          <AnswerChart headers={loaded.headers} rows={loaded.rows} title={card.understood_as || card.text}
            kind={chartKindFromText(wish)}
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
