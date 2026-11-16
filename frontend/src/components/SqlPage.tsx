// SQL (staff): a small MySQL Workbench inside the app. On the left the saved queries (mine, and the ones
// other admins shared; SqlSaved.tsx) above the tables of ai_gold with their row counts and, opened with the
// arrow, their columns and types (a search box filters them; a click puts the name into the editor at the
// cursor; the play icon runs "SELECT * ... LIMIT 100" of the table). On the right the editor tabs (SqlTabs.tsx,
// several queries open at once, each with its own text and its own last result), the SQL editor (CodeMirror,
// loaded only on this page) with Run (Ctrl+Enter; with text selected only the selection runs), Save (Ctrl+S),
// Save as, Open / Download a .sql file, Clear, Excel and the last 10 queries ("Recent"), and under it the
// result grid with "123 rows · 0.12 s", or the API's message in a red box. The server only runs read-only
// SELECTs (max 500 rows, 30 s) and writes every query to the Audit log. The open tabs (sqlTabs.ts), the
// Recent list and the panel sizes are kept in this browser (localStorage).
import { ChevronRight, Database, Download, Eraser, FileSpreadsheet, FileUp, History, Play, Save, SaveAll, Search, Table2 } from 'lucide-react'
import {
  type ChangeEvent, type KeyboardEvent, type PointerEvent, Suspense, lazy, memo, useEffect, useMemo, useRef, useState,
} from 'react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { ApiError, AuthError, api, problemText } from '../api'
import type { SqlCell, SqlResult, SqlSavedList, SqlSavedQuery, SqlSchema, SqlTable } from '../types'
import { Dots, NoAccess, plural } from './common'
import type { SqlEditorHandle } from './SqlEditor'
import { type SaveRequest, SqlSaveDialog } from './SqlSaveDialog'
import { type SavedActions, SqlSaved } from './SqlSaved'
import { SqlTabs } from './SqlTabs'
import { type SqlTab, type TabsState, isBlank, isDirty, keepTabs, newTab, readTabs, savedTab, sqlFileName } from './sqlTabModel'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover'
import { Spinner } from './ui/spinner'
import { Toaster } from './ui/sonner'
import './SqlPage.css'

const SqlEditor = lazy(() => import('./SqlEditor'))

const RECENT_KEY = 'mi.sqlRecent' // localStorage: the last queries run, newest first
const SIZES_KEY = 'mi.sqlSizes' // localStorage: the width of the left panel and the height of the editor
const RECENT_MAX = 10
const FILE_MAX = 200 * 1024 // the biggest .sql file "Open .sql file" takes (bytes)
const NO_TABLES: SqlTable[] = []
const MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
const RUN_KEYS = MAC ? '⌘+Enter' : 'Ctrl+Enter'
const SAVE_KEYS = MAC ? '⌘+S' : 'Ctrl+S'
const SAVE_AS_KEYS = MAC ? '⌘+Shift+S' : 'Ctrl+Shift+S'

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

function SchemaTreeView({ schema, error, onInsert, onPreview }:
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

// memo: typing in the editor does not draw the tree again
const SchemaTree = memo(SchemaTreeView)

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

function ResultGridView({ result }: { result: SqlResult }) {
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

// memo: typing in the editor does not draw the rows again
const ResultGrid = memo(ResultGridView)

/** The last result of one tab (not kept over a reload). */
interface TabOutput { result: SqlResult | null; error: string }
const NO_OUTPUT: TabOutput = { result: null, error: '' }

/** Why Save is off for someone else's shared query. */
const readOnlyNote = (tab: SqlTab) =>
  `Only ${tab.ownerName || 'its owner'} can change this query - use Save as to keep your own copy`

/** The list with this query in place of the old one (or added to its group when it is new). */
function withQuery(list: SqlSavedList, query: SqlSavedQuery): SqlSavedList {
  const drop = (group: SqlSavedQuery[]) => group.filter((q) => q.id !== query.id)
  return query.mine
    ? { mine: [...drop(list.mine), query], shared: drop(list.shared) }
    : { mine: drop(list.mine), shared: [...drop(list.shared), query] }
}

/** Saves a text as a file (the browser's own download). */
function saveFile(text: string, name: string) {
  const link = document.createElement('a')
  link.href = URL.createObjectURL(new Blob([text], { type: 'application/sql' }))
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(link.href), 1000)
}

export default function SqlPage() {
  const handles = useRef(new Map<string, SqlEditorHandle>()) // the editor of each tab
  const column = useRef<HTMLDivElement>(null)
  const fileBox = useRef<HTMLInputElement>(null)
  const [schema, setSchema] = useState<SqlSchema | null>(null)
  const [schemaError, setSchemaError] = useState('')
  const [forbidden, setForbidden] = useState(false)
  const [{ tabs, active }, setTabsState] = useState<TabsState>(readTabs)
  const [outputs, setOutputs] = useState<Record<string, TabOutput>>({})
  const [runningTab, setRunningTab] = useState<string | null>(null)
  const busy = useRef(false) // a second Ctrl+Enter before the first answer does nothing
  const [excelBusy, setExcelBusy] = useState(false)
  const [excelError, setExcelError] = useState('')
  const [recent, setRecent] = useState(readRecent)
  const [recentOpen, setRecentOpen] = useState(false)
  const [sizes, setSizes] = useState(readSizes)
  const sizesNow = useRef(sizes) // the sizes right now (a drag changes them before the page is drawn again)
  const [saved, setSaved] = useState<SqlSavedList | null>(null)
  const [savedError, setSavedError] = useState('')
  const [saveAsk, setSaveAsk] = useState<(SaveRequest & { tabId: string }) | null>(null)
  const [saveBusy, setSaveBusy] = useState(false)
  const [saveError, setSaveError] = useState('')
  const saving = useRef(false) // one Save at a time

  const tab = tabs.find((t) => t.id === active) ?? tabs[0]
  const output = outputs[tab.id] ?? NO_OUTPUT
  const readOnly = tab.savedId !== null && !tab.mine
  const activeNow = useRef(tab.id) // the shown tab right now (for the callbacks made once)
  activeNow.current = tab.id

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
    api.sqlSaved()
      .then((body) => {
        if (gone) return
        setSaved(body)
        // the open tabs of saved queries take the names (and owners) the server has now
        const byId = new Map([...body.mine, ...body.shared].map((q) => [q.id, q]))
        setTabsState((now) => ({
          ...now,
          tabs: now.tabs.map((t) => {
            const q = t.savedId === null ? undefined : byId.get(t.savedId)
            return q ? { ...t, title: q.name, mine: q.mine, ownerName: q.owner_name } : t
          }),
        }))
      })
      .catch((err) => {
        if (!gone && !(err instanceof AuthError)) setSavedError(problemText(err, 'The saved queries could not be loaded.'))
      })
    return () => { gone = true }
  }, [])

  // the open tabs are kept in this browser (a reload brings them back)
  useEffect(() => keepTabs({ tabs, active }), [tabs, active])

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

  // ---- the tabs
  const changeTab = (id: string, part: Partial<SqlTab>) =>
    setTabsState((now) => ({ ...now, tabs: now.tabs.map((t) => (t.id === id ? { ...t, ...part } : t)) }))

  /** Opens a new tab (made from the open tabs); with reuseBlank it takes the place of an empty, unchanged active tab. */
  function openTab(make: (open: SqlTab[]) => SqlTab, reuseBlank = false) {
    setTabsState((now) => {
      const at = now.tabs.findIndex((t) => t.id === now.active)
      const reuse = reuseBlank && at >= 0 && isBlank(now.tabs[at])
      const made = make(reuse ? now.tabs.filter((_, i) => i !== at) : now.tabs)
      return { tabs: reuse ? now.tabs.map((t, i) => (i === at ? made : t)) : [...now.tabs, made], active: made.id }
    })
    setExcelError('')
  }

  function selectTab(id: string) {
    setTabsState((now) => ({ ...now, active: id }))
    setExcelError('')
  }

  function closeTab(id: string) {
    setTabsState((now) => {
      const at = now.tabs.findIndex((t) => t.id === id)
      const rest = now.tabs.filter((t) => t.id !== id)
      if (rest.length === 0) {
        const fresh = newTab([])
        return { tabs: [fresh], active: fresh.id }
      }
      const next = now.active === id ? (rest[at] ?? rest[at - 1]).id : now.active
      return { tabs: rest, active: next }
    })
    setOutputs((now) => {
      const rest = { ...now }
      delete rest[id]
      return rest
    })
  }

  function openSaved(query: SqlSavedQuery) {
    const shown = tabs.find((t) => t.savedId === query.id)
    if (shown) selectTab(shown.id)
    else openTab(() => savedTab(query), true)
  }

  // ---- running
  const setOutput = (id: string, next: (old: TabOutput) => TabOutput) =>
    setOutputs((now) => ({ ...now, [id]: next(now[id] ?? NO_OUTPUT) }))

  async function run() {
    if (busy.current) return
    const id = activeNow.current
    const sql = (handles.current.get(id)?.runText() ?? '').trim()
    if (!sql) {
      setOutput(id, () => ({ result: null, error: 'Type a SELECT query first.' }))
      return
    }
    busy.current = true
    setRunningTab(id)
    setOutput(id, (old) => ({ ...old, error: '' }))
    setExcelError('')
    const list = withRecent(recent, sql)
    setRecent(list)
    try {
      window.localStorage.setItem(RECENT_KEY, JSON.stringify(list))
    } catch {
      // storage blocked: the list lasts until the page is loaded again
    }
    try {
      const result = await api.sql(sql)
      setOutput(id, () => ({ result, error: '' }))
    } catch (err) {
      if (err instanceof AuthError) return // the app shows the sign-in page
      setOutput(id, () => ({ result: null, error: problemText(err, 'The query could not be run.') }))
    } finally {
      busy.current = false
      setRunningTab(null)
    }
  }

  async function excel() {
    if (!output.result || excelBusy) return
    setExcelBusy(true)
    setExcelError('')
    try {
      await api.sqlExcel(output.result.sql)
    } catch (err) {
      if (!(err instanceof AuthError)) setExcelError(problemText(err, 'The Excel file could not be made.'))
    } finally {
      setExcelBusy(false)
    }
  }

  function preview(table: string) {
    handles.current.get(activeNow.current)?.setText(`SELECT * FROM ${table} LIMIT 100;`)
    void run()
  }

  // ---- saving
  /** A saved query came back from the API: the list and the tabs that show it take its new state. */
  function applyQuery(query: SqlSavedQuery) {
    setSaved((now) => (now ? withQuery(now, query) : now))
    setTabsState((now) => ({
      ...now,
      tabs: now.tabs.map((t) => (t.savedId === query.id ? { ...t, title: query.name, mine: query.mine, ownerName: query.owner_name } : t)),
    }))
  }

  /** The saved query is gone: out of the list, and the tabs that showed it become unsaved tabs. */
  function forgetQuery(id: number) {
    setSaved((now) => (now ? { mine: now.mine.filter((q) => q.id !== id), shared: now.shared.filter((q) => q.id !== id) } : now))
    setTabsState((now) => ({
      ...now,
      tabs: now.tabs.map((t) => (t.savedId === id ? { ...t, savedId: null, base: '', mine: true, ownerName: '' } : t)),
    }))
  }

  function askName(asNew: boolean) {
    setSaveError('')
    setSaveAsk({
      tabId: tab.id,
      heading: asNew ? 'Save as' : 'Save query',
      name: asNew && tab.savedId !== null ? `${tab.title} (copy)` : tab.title,
      shared: false,
    })
  }

  async function save() {
    if (readOnly) {
      toast.error(readOnlyNote(tab))
      return
    }
    if (tab.savedId === null) {
      askName(false)
      return
    }
    if (!isDirty(tab) || saving.current) return
    saving.current = true
    const { id, savedId, text } = tab
    try {
      const { query } = await api.sqlChangeSaved(savedId, { sql: text })
      applyQuery(query)
      changeTab(id, { base: text }) // what was typed meanwhile stays unsaved
    } catch (err) {
      if (err instanceof AuthError) return
      if (err instanceof ApiError && err.status === 404) forgetQuery(savedId) // deleted meanwhile: the next Save asks a name
      toast.error(problemText(err, 'The query could not be saved.'))
    } finally {
      saving.current = false
    }
  }

  async function saveNamed(name: string, shared: boolean) {
    const target = tabs.find((t) => t.id === saveAsk?.tabId)
    if (!target) {
      setSaveAsk(null)
      return
    }
    setSaveBusy(true)
    setSaveError('')
    const text = target.text
    try {
      const { query } = await api.sqlSave({ name, sql: text, shared })
      setSaved((now) => (now ? withQuery(now, query) : now))
      changeTab(target.id, { savedId: query.id, title: query.name, base: text, mine: true, ownerName: query.owner_name })
      setSaveAsk(null)
    } catch (err) {
      if (!(err instanceof AuthError)) setSaveError(problemText(err, 'The query could not be saved.'))
    } finally {
      setSaveBusy(false)
    }
  }

  // ---- the "..." of a saved query (calls the API, the list follows)
  async function renameSaved(query: SqlSavedQuery, name: string): Promise<string> {
    try {
      applyQuery((await api.sqlChangeSaved(query.id, { name })).query)
      return ''
    } catch (err) {
      if (err instanceof AuthError) return ''
      if (err instanceof ApiError && err.status === 404) forgetQuery(query.id)
      return problemText(err, 'The query could not be renamed.')
    }
  }

  async function duplicateSaved(query: SqlSavedQuery) {
    try {
      const copy = (await api.sqlSave({ name: `${query.name} (copy)`, sql: query.sql, shared: false })).query
      setSaved((now) => (now ? withQuery(now, copy) : now))
      toast.success(`Saved a copy: "${copy.name}".`)
    } catch (err) {
      if (!(err instanceof AuthError)) toast.error(problemText(err, 'The copy could not be saved.'))
    }
  }

  async function shareSaved(query: SqlSavedQuery, shared: boolean) {
    try {
      applyQuery((await api.sqlChangeSaved(query.id, { shared })).query)
    } catch (err) {
      if (err instanceof AuthError) return
      if (err instanceof ApiError && err.status === 404) forgetQuery(query.id)
      toast.error(problemText(err, 'The query could not be changed.'))
    }
  }

  async function deleteSaved(query: SqlSavedQuery) {
    try {
      await api.sqlDeleteSaved(query.id)
      forgetQuery(query.id)
      toast.success(`"${query.name}" was deleted.`)
    } catch (err) {
      if (err instanceof AuthError) return
      if (err instanceof ApiError && err.status === 404) forgetQuery(query.id)
      toast.error(problemText(err, 'The query could not be deleted.'))
    }
  }

  // ---- .sql files
  async function openFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = '' // the same file can be opened again
    if (!file) return
    if (file.size > FILE_MAX) {
      toast.error(`${file.name} is too big - a .sql file can be at most 200 KB.`)
      return
    }
    let text: string
    try {
      text = await file.text()
    } catch {
      toast.error(`${file.name} could not be read.`)
      return
    }
    const title = file.name.replace(/\.(sql|txt)$/i, '') || file.name
    openTab((open) => ({ ...newTab(open, text), title }), true)
  }

  // the latest functions, for the parts made once (the window's Ctrl+S, the memo'd panels)
  const latest = useRef({ save, askName, openSaved, renameSaved, duplicateSaved, shareSaved, deleteSaved, preview })
  latest.current = { save, askName, openSaved, renameSaved, duplicateSaved, shareSaved, deleteSaved, preview }

  // Ctrl+S saves (Ctrl+Shift+S: Save as), never the browser's own "save the page"
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== 's') return
      event.preventDefault()
      if (document.querySelector('[role="alertdialog"]')) return // a dialog is open: it has its own buttons
      if (event.shiftKey) latest.current.askName(true)
      else void latest.current.save()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const savedActions = useMemo<SavedActions>(() => ({
    open: (query) => latest.current.openSaved(query),
    rename: (query, name) => latest.current.renameSaved(query, name),
    duplicate: (query) => void latest.current.duplicateSaved(query),
    share: (query, shared) => void latest.current.shareSaved(query, shared),
    remove: (query) => void latest.current.deleteSaved(query),
  }), [])
  const tree = useMemo(() => ({
    insert: (name: string) => handles.current.get(activeNow.current)?.insert(name),
    preview: (table: string) => latest.current.preview(table),
  }), [])

  const editorMax = () => Math.max(140, (column.current?.clientHeight || 1000) - 200)
  const running = runningTab === tab.id
  const result = output.result
  const status = result && `${result.truncated ? `first ${result.row_count} rows` : plural(result.row_count, 'row')} · ${result.secs.toFixed(2)} s`

  if (forbidden) return <NoAccess />

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <p className="m-0 flex-none text-[12px] text-muted-foreground">
        Read-only: SELECT queries on ai_gold, max 500 rows, 30 s limit. Every query is in the Audit log.
      </p>
      <div className="flex min-h-0 flex-1 max-[900px]:flex-col max-[900px]:gap-3">
        <aside aria-label="Saved queries and tables" style={{ width: sizes.tree }}
          className="flex flex-none flex-col gap-2 rounded-xl border border-border bg-card p-2 max-[900px]:w-full!">
          <SqlSaved list={saved} error={savedError} activeId={tab.savedId} actions={savedActions} />
          <div aria-hidden="true" className="flex-none border-t border-border" />
          <section aria-label="Tables" className="min-h-0 flex-1 max-[900px]:h-[300px] max-[900px]:flex-none">
            <SchemaTree schema={schema} error={schemaError} onInsert={tree.insert} onPreview={tree.preview} />
          </section>
        </aside>
        <Splitter vertical label="Width of the left panel" value={sizes.tree} min={200} max={() => 520}
          onChange={(width) => resize({ tree: width })} onDone={keepSizes} />

        <div ref={column} className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="mb-2 flex flex-none flex-wrap items-center gap-2">
            <Button size="sm" onClick={() => void run()} disabled={runningTab !== null} title={`Run (${RUN_KEYS}). With text selected, only the selection runs.`}>
              {runningTab !== null ? <Spinner /> : <Play />} Run
            </Button>
            {/* a disabled button shows no tooltip in every browser: the note sits on the box around it too */}
            <span title={readOnly ? readOnlyNote(tab) : undefined} className="inline-flex">
              <Button size="sm" variant="outline" onClick={() => void save()} disabled={readOnly}
                title={readOnly ? readOnlyNote(tab) : tab.savedId === null ? `Save (${SAVE_KEYS}) - asks for a name` : `Save (${SAVE_KEYS})`}>
                <Save /> Save
              </Button>
            </span>
            <Button size="sm" variant="outline" onClick={() => askName(true)} title={`Save as a new saved query (${SAVE_AS_KEYS})`}>
              <SaveAll /> Save as…
            </Button>
            <Button size="icon-sm" variant="ghost" onClick={() => fileBox.current?.click()} aria-label="Open .sql file" title="Open a .sql file in a new tab">
              <FileUp />
            </Button>
            <input ref={fileBox} type="file" accept=".sql,.txt,text/plain" hidden data-testid="sql-file"
              onChange={(event) => void openFile(event)} />
            <Button size="icon-sm" variant="ghost" onClick={() => saveFile(tab.text, sqlFileName(tab.title))} disabled={!tab.text}
              aria-label="Download .sql" title={tab.text ? `Download this tab as ${sqlFileName(tab.title)}` : 'The tab is empty'}>
              <Download />
            </Button>
            <Button size="sm" variant="outline" onClick={() => handles.current.get(tab.id)?.setText('')} title="Clear the editor (Ctrl+Z brings the text back)">
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
              <PopoverContent align="start" className="ui-scope w-[min(520px,90vw)] p-1.5">
                <ul aria-label="Recent queries">
                  {recent.map((sql) => (
                    <li key={sql}>
                      <button type="button" title={sql}
                        onClick={() => { handles.current.get(tab.id)?.setText(sql); setRecentOpen(false) }}
                        className="block w-full truncate rounded-md px-2.5 py-1.5 text-left font-mono text-[12px] hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring">
                        {sql.replace(/\s+/g, ' ')}
                      </button>
                    </li>
                  ))}
                </ul>
              </PopoverContent>
            </Popover>
            <span className="ml-auto text-[11.5px] text-muted-foreground max-[640px]:hidden">{RUN_KEYS} runs · {SAVE_KEYS} saves</span>
          </div>
          {excelError && (
            <div role="alert" className="mb-2 flex-none rounded-lg border border-destructive/40 bg-danger-soft px-3 py-1.5 text-[12.5px] text-destructive">
              {excelError}
            </div>
          )}

          <SqlTabs tabs={tabs} active={tab.id} onSelect={selectTab} onClose={closeTab}
            onNew={() => openTab((open) => newTab(open))} />
          <div style={{ height: sizes.editor }} className="flex-none overflow-hidden rounded-b-xl border border-t-0 border-input bg-card">
            <Suspense fallback={<div role="status" className="p-3 text-[12.5px] text-muted-foreground"><Dots /> Loading the editor…</div>}>
              {tabs.map((t) => (
                <div key={t.id} role="tabpanel" aria-labelledby={`sql-tab-${t.id}`} hidden={t.id !== tab.id} className="h-full">
                  <SqlEditor initialText={t.text} tables={schema?.tables ?? NO_TABLES} active={t.id === tab.id}
                    ref={(handle) => {
                      if (handle) handles.current.set(t.id, handle)
                      else handles.current.delete(t.id)
                    }}
                    onChange={(text) => changeTab(t.id, { text })} onRun={() => void run()} />
                </div>
              ))}
            </Suspense>
          </div>
          <Splitter vertical={false} label="Height of the editor" value={sizes.editor} min={100} max={editorMax}
            onChange={(height) => resize({ editor: height })} onDone={keepSizes} />

          <div className="flex min-h-0 flex-1 flex-col gap-1.5 max-[900px]:min-h-[340px]">
            <div role="status" className="flex-none text-[12px] text-muted-foreground tabular-nums">
              {running ? <><Spinner className="mr-1 inline" /> Running…</> : status || ''}
            </div>
            {output.error ? (
              <div role="alert" className="flex-none rounded-lg border border-destructive/40 bg-danger-soft px-3 py-2 text-[13px] whitespace-pre-wrap text-destructive">
                {output.error}
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

      <SqlSaveDialog request={saveAsk} busy={saveBusy} error={saveError}
        onSave={(name, shared) => void saveNamed(name, shared)} onCancel={() => setSaveAsk(null)} />
      <Toaster position="top-center" duration={6000} />
    </div>
  )
}
