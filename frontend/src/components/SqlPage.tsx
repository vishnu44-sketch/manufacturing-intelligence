// SQL (staff): a small MySQL Workbench inside the app. On the left the tables of ai_gold with their row
// counts and, opened with the arrow, their columns and types (a search box filters them; a click puts the
// name into the editor at the cursor; the play icon runs "SELECT * ... LIMIT 100" of the table). On the right
// the SQL editor (CodeMirror, loaded only on this page) with Run (Ctrl+Enter; with text selected only the
// selection runs), Clear, Excel and the last 10 queries ("Recent"), and under it the result grid with
// "123 rows · 0.12 s", or the API's message in a red box. The server only runs read-only SELECTs (max 500
// rows, 30 s) and writes every query to the Audit log. The editor text is kept for this browser tab
// (sessionStorage), the Recent list and the panel sizes in this browser (localStorage).
import { ChevronRight, Database, Eraser, FileSpreadsheet, History, Play, Search, Table2 } from 'lucide-react'
import {
  type KeyboardEvent, type PointerEvent, Suspense, lazy, useEffect, useMemo, useRef, useState,
} from 'react'
import { cn } from '@/lib/utils'
import { ApiError, AuthError, api, problemText } from '../api'
import type { SqlCell, SqlResult, SqlSchema, SqlTable } from '../types'
import { Dots, NoAccess, plural } from './common'
import type { SqlEditorHandle } from './SqlEditor'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover'
import { Spinner } from './ui/spinner'
import './SqlPage.css'

const SqlEditor = lazy(() => import('./SqlEditor'))

const TEXT_KEY = 'mi.sqlText' // sessionStorage: the editor text (a reload keeps it)
const RECENT_KEY = 'mi.sqlRecent' // localStorage: the last queries run, newest first
const SIZES_KEY = 'mi.sqlSizes' // localStorage: the width of the table list and the height of the editor
const RECENT_MAX = 10
const NO_TABLES: SqlTable[] = []
const MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
const RUN_KEYS = MAC ? '⌘+Enter' : 'Ctrl+Enter'

function readText(): string {
  try {
    return window.sessionStorage.getItem(TEXT_KEY) ?? ''
  } catch {
    return ''
  }
}

function keepText(text: string) {
  try {
    if (text) window.sessionStorage.setItem(TEXT_KEY, text)
    else window.sessionStorage.removeItem(TEXT_KEY)
  } catch {
    // storage blocked: the text is lost on a reload, nothing else changes
  }
}

function readRecent(): string[] {
  try {
    const list: unknown = JSON.parse(window.localStorage.getItem(RECENT_KEY) ?? '[]')
    return Array.isArray(list) ? list.filter((q): q is string => typeof q === 'string').slice(0, RECENT_MAX) : []
  } catch {
    return []
  }
}

/** The Recent list with this query on top (once, at most 10). */
export function withRecent(list: string[], sql: string): string[] {
  return [sql, ...list.filter((q) => q !== sql)].slice(0, RECENT_MAX)
}

interface Sizes { tree: number; editor: number }
const SIZES: Sizes = { tree: 280, editor: 240 }
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

function readSizes(): Sizes {
  try {
    const saved = JSON.parse(window.localStorage.getItem(SIZES_KEY) ?? '{}') as Partial<Sizes>
    return {
      tree: typeof saved.tree === 'number' ? clamp(saved.tree, 200, 520) : SIZES.tree,
      editor: typeof saved.editor === 'number' ? clamp(saved.editor, 100, 1200) : SIZES.editor,
    }
  } catch {
    return SIZES
  }
}

/** A bar to drag (or move with the arrow keys) between two panels. */
function Splitter({ vertical, label, value, min, max, onChange, onDone }:
  { vertical: boolean; label: string; value: number; min: number; max: () => number;
    onChange: (value: number) => void; onDone: () => void }) {
  const start = useRef<{ at: number; value: number } | null>(null)
  const down = (event: PointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.currentTarget.setPointerCapture?.(event.pointerId)
    start.current = { at: vertical ? event.clientX : event.clientY, value }
  }
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (!start.current) return
    const delta = (vertical ? event.clientX : event.clientY) - start.current.at
    onChange(clamp(start.current.value + delta, min, max()))
  }
  const up = (event: PointerEvent<HTMLDivElement>) => {
    if (!start.current) return
    start.current = null
    event.currentTarget.releasePointerCapture?.(event.pointerId)
    onDone()
  }
  const key = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = { ArrowLeft: -16, ArrowUp: -16, ArrowRight: 16, ArrowDown: 16 }[event.key]
    if (step === undefined) return
    event.preventDefault()
    onChange(clamp(value + step, min, max()))
    onDone()
  }
  return (
    <div role="separator" aria-orientation={vertical ? 'vertical' : 'horizontal'} aria-label={label} tabIndex={0}
      aria-valuenow={Math.round(value)} aria-valuemin={min}
      onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onKeyDown={key}
      className={cn(
        'group flex flex-none touch-none items-center justify-center outline-none',
        vertical ? 'w-2 cursor-col-resize max-[900px]:hidden' : 'h-2 cursor-row-resize')}>
      <span className={cn('rounded-full bg-border transition-colors group-hover:bg-primary/60 group-focus-visible:bg-primary',
        vertical ? 'h-10 w-[3px]' : 'h-[3px] w-10')} />
    </div>
  )
}

/** The tables (and their columns) that match the search: a table whose name matches keeps all its
 *  columns; any other table stays when one of its columns matches, with only those columns. */
export function filterTables(tables: SqlTable[], find: string): { table: SqlTable; columns: SqlTable['columns']; byColumn: boolean }[] {
  const needle = find.trim().toLowerCase()
  const shown = []
  for (const table of tables) {
    if (!needle || table.name.toLowerCase().includes(needle)) {
      shown.push({ table, columns: table.columns, byColumn: false })
      continue
    }
    const columns = table.columns.filter((column) => column.name.toLowerCase().includes(needle))
    if (columns.length) shown.push({ table, columns, byColumn: true })
  }
  return shown
}

const TREE_BUTTON = 'rounded-md focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-ring'

function SchemaTree({ schema, error, onInsert, onPreview }:
  { schema: SqlSchema | null; error: string; onInsert: (name: string) => void; onPreview: (table: string) => void }) {
  const [find, setFind] = useState('')
  const [dbOpen, setDbOpen] = useState(true)
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  const shown = useMemo(() => filterTables(schema?.tables ?? NO_TABLES, find), [schema, find])
  const toggle = (name: string) => setOpen((now) => {
    const next = new Set(now)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    return next
  })
  const database = schema?.database || 'ai_gold'

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="relative flex-none">
        <Search aria-hidden="true" size={14} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground" />
        <Input type="text" value={find} onChange={(event) => setFind(event.target.value)} aria-label="Find a table or column"
          placeholder="Find a table or column" className="pl-8!" />
      </div>
      <div className="min-h-0 flex-1 overflow-auto text-[12.5px] [scrollbar-width:thin]">
        {error ? (
          <div role="alert" className="rounded-lg border border-destructive/40 bg-danger-soft px-3 py-2 text-destructive">{error}</div>
        ) : !schema ? (
          <div role="status" className="px-2 py-1 text-muted-foreground"><Dots /> Loading the tables…</div>
        ) : (
          <ul aria-label={`Tables of ${database}`}>
            <li>
              <button type="button" onClick={() => setDbOpen(!dbOpen)} aria-expanded={dbOpen}
                className={cn(TREE_BUTTON, 'flex h-7 w-full items-center gap-1.5 px-1 text-left font-semibold hover:bg-accent')}>
                <ChevronRight aria-hidden="true" size={14} className={cn('flex-none text-muted-foreground transition-transform', dbOpen && 'rotate-90')} />
                <Database aria-hidden="true" size={14} className="flex-none text-primary" />
                <span className="truncate">{database}</span>
                <span className="ml-auto text-[11px] font-normal text-muted-foreground">{plural(schema.tables.length, 'table')}</span>
              </button>
              {dbOpen && (
                <ul className="pl-3">
                  {shown.length === 0 && <li className="px-2 py-1 text-muted-foreground">{find.trim() ? 'Nothing matches.' : 'No tables found.'}</li>}
                  {shown.map(({ table, columns, byColumn }) => {
                    const isOpen = byColumn || open.has(table.name)
                    return (
                      <li key={table.name}>
                        <div className="flex h-7 items-center gap-0.5 rounded-md hover:bg-accent">
                          <button type="button" onClick={() => toggle(table.name)} aria-expanded={isOpen}
                            aria-label={`${isOpen ? 'Hide' : 'Show'} the columns of ${table.name}`}
                            className={cn(TREE_BUTTON, 'grid size-6 flex-none place-items-center text-muted-foreground hover:text-foreground')}>
                            <ChevronRight aria-hidden="true" size={14} className={cn('transition-transform', isOpen && 'rotate-90')} />
                          </button>
                          <button type="button" onClick={() => onInsert(table.name)} title={`Put ${table.name} into the editor`}
                            className={cn(TREE_BUTTON, 'flex h-full min-w-0 flex-1 items-center gap-1.5 text-left')}>
                            <Table2 aria-hidden="true" size={14} className="flex-none text-muted-foreground" />
                            <span className="truncate font-medium">{table.name}</span>
                          </button>
                          {table.rows != null && (
                            <span className="flex-none text-[11px] text-muted-foreground tabular-nums" title={`${table.rows.toLocaleString('en-US')} rows`}>
                              {table.rows.toLocaleString('en-US')}
                            </span>
                          )}
                          <button type="button" onClick={() => onPreview(table.name)}
                            aria-label={`Run SELECT * FROM ${table.name} LIMIT 100`} title={`Run SELECT * FROM ${table.name} LIMIT 100`}
                            className={cn(TREE_BUTTON, 'grid size-6 flex-none place-items-center text-muted-foreground hover:text-primary')}>
                            <Play aria-hidden="true" size={12} />
                          </button>
                        </div>
                        {isOpen && (
                          <ul className="pb-1 pl-7">
                            {columns.map((column) => (
                              <li key={column.name}>
                                <button type="button" onClick={() => onInsert(column.name)} title={`Put ${column.name} into the editor`}
                                  className={cn(TREE_BUTTON, 'flex h-6 w-full min-w-0 items-center gap-2 px-1.5 text-left hover:bg-accent')}>
                                  <span className="truncate">{column.name}</span>
                                  <span className="ml-auto flex-none text-[11px] text-muted-foreground">{column.type}</span>
                                </button>
                              </li>
                            ))}
                            {columns.length === 0 && <li className="px-1.5 text-muted-foreground">No columns.</li>}
                          </ul>
                        )}
                      </li>
                    )
                  })}
                </ul>
              )}
            </li>
          </ul>
        )}
      </div>
    </div>
  )
}

const NUMBER = /^-?\d+(\.\d+)?(e[+-]?\d+)?$/i

/** Which columns hold only numbers (right-aligned): every value that is not NULL is a number. */
export function numericColumns(result: SqlResult): boolean[] {
  return result.columns.map((_, index) => {
    let any = false
    for (const row of result.rows) {
      const cell = row[index]
      if (cell === null || cell === undefined) continue
      if (typeof cell === 'number' || (typeof cell === 'string' && NUMBER.test(cell))) any = true
      else return false
    }
    return any
  })
}

function cellText(cell: SqlCell): string {
  if (typeof cell === 'string') return cell
  if (typeof cell === 'number' || typeof cell === 'boolean') return String(cell)
  return JSON.stringify(cell)
}

function ResultGrid({ result }: { result: SqlResult }) {
  const numeric = useMemo(() => numericColumns(result), [result])
  const head = 'sticky top-0 z-10 border-b border-border bg-muted px-3 py-1.5 font-semibold whitespace-nowrap text-heading'
  return (
    <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border bg-card [scrollbar-width:thin]">
      <table aria-label="Query result" className="w-max min-w-full border-separate border-spacing-0 text-[12.5px]">
        <thead>
          <tr>
            <th scope="col" className={cn(head, 'w-px text-right text-faint')}>#</th>
            {result.columns.map((column, index) => (
              <th key={index} scope="col" className={cn(head, numeric[index] ? 'text-right' : 'text-left')}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, r) => (
            <tr key={r} className="hover:bg-accent/60">
              <td className="border-b border-border px-3 py-1 text-right text-faint tabular-nums">{r + 1}</td>
              {result.columns.map((_, index) => {
                const cell = row[index] ?? null
                const text = cell === null ? '' : cellText(cell)
                return (
                  <td key={index} title={text.length > 60 ? text : undefined}
                    className={cn('max-w-[28rem] truncate border-b border-border px-3 py-1 whitespace-nowrap',
                      numeric[index] && 'text-right tabular-nums')}>
                    {cell === null ? <span className="text-muted-foreground italic">NULL</span> : text}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {result.rows.length === 0 && <div className="px-3 py-2 text-[12.5px] text-muted-foreground">No rows.</div>}
    </div>
  )
}

export default function SqlPage() {
  const editor = useRef<SqlEditorHandle>(null)
  const column = useRef<HTMLDivElement>(null)
  const [schema, setSchema] = useState<SqlSchema | null>(null)
  const [schemaError, setSchemaError] = useState('')
  const [forbidden, setForbidden] = useState(false)
  const [initialText] = useState(readText)
  const [result, setResult] = useState<SqlResult | null>(null)
  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  const busy = useRef(false) // a second Ctrl+Enter before the first answer does nothing
  const [excelBusy, setExcelBusy] = useState(false)
  const [excelError, setExcelError] = useState('')
  const [recent, setRecent] = useState(readRecent)
  const [recentOpen, setRecentOpen] = useState(false)
  const [sizes, setSizes] = useState(readSizes)
  const sizesNow = useRef(sizes) // the sizes right now (a drag changes them before the page is drawn again)

  // on a desktop the page fills the window and does not scroll itself (SqlPage.css)
  useEffect(() => {
    document.body.classList.add('page-sql')
    return () => document.body.classList.remove('page-sql')
  }, [])

  useEffect(() => {
    let gone = false
    api.sqlSchema()
      .then((body) => { if (!gone) setSchema(body) })
      .catch((err) => {
        if (gone || err instanceof AuthError) return
        if (err instanceof ApiError && err.status === 403) setForbidden(true)
        else setSchemaError(problemText(err, 'The tables could not be loaded.'))
      })
    return () => { gone = true }
  }, [])

  const resize = (part: Partial<Sizes>) => {
    sizesNow.current = { ...sizesNow.current, ...part }
    setSizes(sizesNow.current)
  }
  // kept when a drag ends (not on every move)
  const keepSizes = () => {
    try {
      window.localStorage.setItem(SIZES_KEY, JSON.stringify(sizesNow.current))
    } catch {
      // storage blocked: the sizes last until the page is loaded again
    }
  }

  async function run() {
    if (busy.current) return
    const sql = (editor.current?.runText() ?? '').trim()
    if (!sql) {
      setResult(null)
      setError('Type a SELECT query first.')
      return
    }
    busy.current = true
    setRunning(true)
    setError('')
    setExcelError('')
    const list = withRecent(recent, sql)
    setRecent(list)
    try {
      window.localStorage.setItem(RECENT_KEY, JSON.stringify(list))
    } catch {
      // storage blocked: the list lasts until the page is loaded again
    }
    try {
      setResult(await api.sql(sql))
    } catch (err) {
      if (err instanceof AuthError) return // the app shows the sign-in page
      setResult(null)
      setError(problemText(err, 'The query could not be run.'))
    } finally {
      busy.current = false
      setRunning(false)
    }
  }

  async function excel() {
    if (!result || excelBusy) return
    setExcelBusy(true)
    setExcelError('')
    try {
      await api.sqlExcel(result.sql)
    } catch (err) {
      if (!(err instanceof AuthError)) setExcelError(problemText(err, 'The Excel file could not be made.'))
    } finally {
      setExcelBusy(false)
    }
  }

  function preview(table: string) {
    editor.current?.setText(`SELECT * FROM ${table} LIMIT 100;`)
    void run()
  }

  const editorMax = () => Math.max(140, (column.current?.clientHeight || 1000) - 160)
  const status = result && `${result.truncated ? `first ${result.row_count} rows` : plural(result.row_count, 'row')} · ${result.secs.toFixed(2)} s`

  if (forbidden) return <NoAccess />

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <p className="m-0 flex-none text-[12px] text-muted-foreground">
        Read-only: SELECT queries on ai_gold, max 500 rows, 30 s limit. Every query is in the Audit log.
      </p>
      <div className="flex min-h-0 flex-1 max-[900px]:flex-col max-[900px]:gap-3">
        <aside aria-label="Tables" style={{ width: sizes.tree }}
          className="flex-none rounded-xl border border-border bg-card p-2 max-[900px]:h-[300px] max-[900px]:w-full!">
          <SchemaTree schema={schema} error={schemaError} onInsert={(name) => editor.current?.insert(name)} onPreview={preview} />
        </aside>
        <Splitter vertical label="Width of the table list" value={sizes.tree} min={200} max={() => 520}
          onChange={(tree) => resize({ tree })} onDone={keepSizes} />

        <div ref={column} className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="mb-2 flex flex-none flex-wrap items-center gap-2">
            <Button size="sm" onClick={() => void run()} disabled={running} title={`Run (${RUN_KEYS}). With text selected, only the selection runs.`}>
              {running ? <Spinner /> : <Play />} Run
            </Button>
            <Button size="sm" variant="outline" onClick={() => editor.current?.setText('')} title="Clear the editor (Ctrl+Z brings the text back)">
              <Eraser /> Clear
            </Button>
            <Button size="sm" variant="outline" onClick={() => void excel()} disabled={!result || excelBusy}
              title={result ? 'Download these rows as an Excel file' : 'Run a query first'}>
              {excelBusy ? <Spinner /> : <FileSpreadsheet />} Excel
            </Button>
            <Popover open={recentOpen} onOpenChange={setRecentOpen}>
              <PopoverTrigger asChild>
                <Button size="sm" variant="ghost" disabled={recent.length === 0} title="The last queries run in this browser">
                  <History /> Recent
                </Button>
              </PopoverTrigger>
              <PopoverContent align="start" className="w-[min(520px,90vw)] p-1.5">
                <ul aria-label="Recent queries">
                  {recent.map((sql) => (
                    <li key={sql}>
                      <button type="button" title={sql}
                        onClick={() => { editor.current?.setText(sql); setRecentOpen(false) }}
                        className="block w-full truncate rounded-md px-2.5 py-1.5 text-left font-mono text-[12px] hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring">
                        {sql.replace(/\s+/g, ' ')}
                      </button>
                    </li>
                  ))}
                </ul>
              </PopoverContent>
            </Popover>
            <span className="ml-auto text-[11.5px] text-muted-foreground max-[640px]:hidden">{RUN_KEYS} runs · a selection runs alone</span>
          </div>
          {excelError && (
            <div role="alert" className="mb-2 flex-none rounded-lg border border-destructive/40 bg-danger-soft px-3 py-1.5 text-[12.5px] text-destructive">
              {excelError}
            </div>
          )}

          <div style={{ height: sizes.editor }} className="flex-none overflow-hidden rounded-xl border border-input bg-card">
            <Suspense fallback={<div role="status" className="p-3 text-[12.5px] text-muted-foreground"><Dots /> Loading the editor…</div>}>
              <SqlEditor ref={editor} initialText={initialText} tables={schema?.tables ?? NO_TABLES} onChange={keepText} onRun={() => void run()} />
            </Suspense>
          </div>
          <Splitter vertical={false} label="Height of the editor" value={sizes.editor} min={100} max={editorMax}
            onChange={(editor) => resize({ editor })} onDone={keepSizes} />

          <div className="flex min-h-0 flex-1 flex-col gap-1.5 max-[900px]:min-h-[340px]">
            <div role="status" className="flex-none text-[12px] text-muted-foreground tabular-nums">
              {running ? <><Spinner className="mr-1 inline" /> Running…</> : status || ''}
            </div>
            {error ? (
              <div role="alert" className="flex-none rounded-lg border border-destructive/40 bg-danger-soft px-3 py-2 text-[13px] whitespace-pre-wrap text-destructive">
                {error}
              </div>
            ) : result ? (
              <ResultGrid result={result} />
            ) : (
              <div className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-[12.5px] text-muted-foreground">
                Run a query to see its rows here. A click on a table or column puts its name into the editor.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
