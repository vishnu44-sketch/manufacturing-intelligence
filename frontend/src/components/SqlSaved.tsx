// The "Saved queries" part of the SQL page's left panel (above the table tree), like MySQL Workbench's saved
// scripts: a search box and two groups, "My queries" (a globe when shared with all admins, a lock when
// private) and "Shared by others" (with the owner's name). One click opens a query in a tab. The "..." of a
// query: on my own Rename, Duplicate, the "Share with all admins" switch and Delete (asks first); on
// someone else's Open and Duplicate only.
import { ChevronRight, Copy, FolderOpen, Globe, Lock, MoreHorizontal, Pencil, Search, Trash2 } from 'lucide-react'
import { type FormEvent, memo, useMemo, useState } from 'react'
import { cn } from '@/lib/utils'
import type { SqlSavedList, SqlSavedQuery } from '../types'
import { Dots } from './common'
import { NAME_MAX } from './SqlSaveDialog'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from './ui/alert-dialog'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover'
import { Switch } from './ui/switch'

export interface SavedActions {
  open: (query: SqlSavedQuery) => void
  /** '' when renamed, else the API's message (shown in the menu). */
  rename: (query: SqlSavedQuery, name: string) => Promise<string>
  duplicate: (query: SqlSavedQuery) => void
  share: (query: SqlSavedQuery, shared: boolean) => void
  remove: (query: SqlSavedQuery) => void
}

/** The queries whose name (or, for shared ones, owner) has the search text, sorted by name. */
export function filterSaved(list: SqlSavedQuery[], find: string): SqlSavedQuery[] {
  const needle = find.trim().toLowerCase()
  return list
    .filter((q) => !needle || q.name.toLowerCase().includes(needle) || (!q.mine && q.owner_name.toLowerCase().includes(needle)))
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }))
}

const ROW_BUTTON = 'rounded-md focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-ring'
const ITEM = 'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px] transition-colors [&_svg]:size-3.5 [&_svg]:shrink-0'

function QueryMenu({ query, actions, onDone, onDelete }:
  { query: SqlSavedQuery; actions: SavedActions; onDone: () => void; onDelete: () => void }) {
  const [name, setName] = useState(query.name)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function rename(event: FormEvent) {
    event.preventDefault()
    if (busy || !name.trim()) return
    if (name.trim() === query.name) return onDone()
    setBusy(true)
    const problem = await actions.rename(query, name.trim())
    setBusy(false)
    if (problem) setError(problem)
    else onDone()
  }

  if (!query.mine) {
    return (
      <div className="flex flex-col gap-0.5">
        <button type="button" className={cn(ITEM, 'hover:bg-accent')} onClick={() => { onDone(); actions.open(query) }}>
          <FolderOpen aria-hidden="true" /> Open
        </button>
        <button type="button" className={cn(ITEM, 'hover:bg-accent')} onClick={() => { onDone(); actions.duplicate(query) }}>
          <Copy aria-hidden="true" /> Duplicate
        </button>
        <div className="mt-0.5 border-t border-border px-2 pt-1.5 text-[11px] text-muted-foreground">
          Shared by {query.owner_name} · changed {query.updated_text}
        </div>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-0.5">
      <form className="mb-1 flex gap-1.5" onSubmit={rename}>
        <Input value={name} maxLength={NAME_MAX} required aria-label={`New name for ${query.name}`}
          onChange={(event) => { setName(event.target.value); setError('') }} />
        <Button type="submit" size="sm" disabled={busy || !name.trim()}><Pencil /> Rename</Button>
      </form>
      {error && <div role="alert" className="mb-1 rounded-md bg-danger-soft px-2 py-1 text-[11.5px] text-destructive">{error}</div>}
      <button type="button" className={cn(ITEM, 'hover:bg-accent')} onClick={() => { onDone(); actions.duplicate(query) }}>
        <Copy aria-hidden="true" /> Duplicate
      </button>
      <div className={cn(ITEM, 'justify-between')}>
        <span id={`share-${query.id}`}>Share with all admins</span>
        <Switch checked={query.shared} aria-labelledby={`share-${query.id}`} onCheckedChange={(shared) => actions.share(query, shared)} />
      </div>
      <button type="button" className={cn(ITEM, 'text-destructive hover:bg-danger-soft')} onClick={() => { onDone(); onDelete() }}>
        <Trash2 aria-hidden="true" /> Delete
      </button>
      <div className="mt-0.5 border-t border-border px-2 pt-1.5 text-[11px] text-muted-foreground">Changed {query.updated_text}</div>
    </div>
  )
}

function QueryRow({ query, active, actions, onDelete }:
  { query: SqlSavedQuery; active: boolean; actions: SavedActions; onDelete: (query: SqlSavedQuery) => void }) {
  const [menu, setMenu] = useState(false)
  const Icon = query.shared ? Globe : Lock
  return (
    <li className={cn('group flex h-7 items-center gap-0.5 rounded-md hover:bg-accent', active && 'bg-primary-soft')}>
      <button type="button" onClick={() => actions.open(query)}
        title={`${query.name}\nChanged ${query.updated_text}${query.mine ? '' : ` · by ${query.owner_name}`}`}
        className={cn(ROW_BUTTON, 'flex h-full min-w-0 flex-1 items-center gap-1.5 px-1.5 text-left')}>
        {query.mine && (
          <Icon aria-hidden="true" size={13} className={cn('flex-none', query.shared ? 'text-primary' : 'text-muted-foreground')} />
        )}
        <span className="truncate font-medium">{query.name}</span>
        {query.mine && <>{' '}<span className="sr-only">{query.shared ? '(shared with all admins)' : '(private)'}</span></>}
        {!query.mine && <span className="ml-auto flex-none truncate text-[10.5px] text-muted-foreground">{query.owner_name}</span>}
      </button>
      <Popover open={menu} onOpenChange={setMenu}>
        <PopoverTrigger asChild>
          <button type="button" aria-label={`More for ${query.name}`} title="More"
            className={cn(ROW_BUTTON, 'grid size-6 flex-none place-items-center text-muted-foreground hover:text-foreground')}>
            <MoreHorizontal aria-hidden="true" size={14} />
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" side="bottom" className="ui-scope w-[min(17rem,calc(100vw-2rem))] p-2">
          <QueryMenu query={query} actions={actions} onDone={() => setMenu(false)} onDelete={() => onDelete(query)} />
        </PopoverContent>
      </Popover>
    </li>
  )
}

function SqlSavedPanel({ list, error, activeId, actions }:
  { list: SqlSavedList | null; error: string; activeId: number | null; actions: SavedActions }) {
  const [open, setOpen] = useState(true)
  const [find, setFind] = useState('')
  const [toDelete, setToDelete] = useState<SqlSavedQuery | null>(null)
  const mine = useMemo(() => filterSaved(list?.mine ?? [], find), [list, find])
  const shared = useMemo(() => filterSaved(list?.shared ?? [], find), [list, find])
  const total = list ? list.mine.length + list.shared.length : 0

  const group = (label: string, queries: SqlSavedQuery[], empty: string) => (
    <div>
      <div className="px-1.5 pt-1 pb-0.5 text-[10.5px] font-semibold tracking-wide text-muted-foreground uppercase">{label}</div>
      <ul aria-label={label}>
        {queries.map((query) => (
          <QueryRow key={query.id} query={query} active={query.id === activeId} actions={actions} onDelete={setToDelete} />
        ))}
        {queries.length === 0 && <li className="px-1.5 py-0.5 text-muted-foreground">{find.trim() ? 'Nothing matches.' : empty}</li>}
      </ul>
    </div>
  )

  return (
    <section aria-label="Saved queries" className="flex min-h-0 flex-none flex-col gap-1.5 text-[12.5px]">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className={cn(ROW_BUTTON, 'flex h-7 w-full items-center gap-1.5 px-1 text-left font-semibold hover:bg-accent')}>
        <ChevronRight aria-hidden="true" size={14} className={cn('flex-none text-muted-foreground transition-transform', open && 'rotate-90')} />
        Saved queries
        {list && <span className="ml-auto text-[11px] font-normal text-muted-foreground">{total}</span>}
      </button>
      {open && (
        <>
          <div className="relative flex-none">
            <Search aria-hidden="true" size={14} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground" />
            <Input type="text" value={find} onChange={(event) => setFind(event.target.value)} aria-label="Find a saved query"
              placeholder="Find a saved query" className="pl-8!" />
          </div>
          <div className="max-h-[38vh] min-h-0 overflow-auto [scrollbar-width:thin] max-[900px]:max-h-[220px]">
            {error ? (
              <div role="alert" className="rounded-lg border border-destructive/40 bg-danger-soft px-3 py-2 text-destructive">{error}</div>
            ) : !list ? (
              <div role="status" className="px-2 py-1 text-muted-foreground"><Dots /> Loading the saved queries…</div>
            ) : (
              <>
                {group('My queries', mine, 'None yet - Save (Ctrl+S) keeps the open query.')}
                {group('Shared by others', shared, 'None yet.')}
              </>
            )}
          </div>
        </>
      )}

      <AlertDialog open={toDelete !== null} onOpenChange={(next) => { if (!next) setToDelete(null) }}>
        <AlertDialogContent aria-describedby={undefined}>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {toDelete?.name}?</AlertDialogTitle>
            <p className="text-[12.5px] text-muted-foreground">
              {toDelete?.shared ? 'The other admins will not see it any more either. ' : ''}This cannot be undone.
            </p>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => { if (toDelete) actions.remove(toDelete) }}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}

export const SqlSaved = memo(SqlSavedPanel)
