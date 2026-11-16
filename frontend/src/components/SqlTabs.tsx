// The tabs above the SQL editor (like MySQL Workbench): one per open query, with its title, a dot when it
// has unsaved changes and an x to close it (a middle click closes too). Closing a tab with unsaved changes
// asks "Close without saving?" first. The "+" opens a new empty tab.
import { Globe, Plus, X } from 'lucide-react'
import { type KeyboardEvent, useState } from 'react'
import { cn } from '@/lib/utils'
import { type SqlTab, isDirty } from './sqlTabModel'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from './ui/alert-dialog'

export function SqlTabs({ tabs, active, onSelect, onClose, onNew }:
  { tabs: SqlTab[]; active: string; onSelect: (id: string) => void; onClose: (id: string) => void; onNew: () => void }) {
  const [asking, setAsking] = useState<SqlTab | null>(null)

  const close = (tab: SqlTab) => {
    if (isDirty(tab)) setAsking(tab)
    else onClose(tab.id)
  }

  // the arrow keys move between the tabs (the usual tab list keys)
  const key = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const step = { ArrowLeft: -1, ArrowRight: 1 }[event.key]
    if (step === undefined) return
    event.preventDefault()
    const next = tabs[(index + step + tabs.length) % tabs.length]
    onSelect(next.id)
    document.getElementById(`sql-tab-${next.id}`)?.focus()
  }

  return (
    <div className="flex min-w-0 flex-none items-end gap-0.5 border-b border-border">
      <div role="tablist" aria-label="Open queries" className="flex min-w-0 items-end gap-0.5 overflow-x-auto [scrollbar-width:thin]">
        {tabs.map((tab, index) => {
          const selected = tab.id === active
          const dirty = isDirty(tab)
          return (
            <div key={tab.id} onAuxClick={(event) => { if (event.button === 1) { event.preventDefault(); close(tab) } }}
              className={cn(
                'group -mb-px flex h-8 max-w-[220px] flex-none items-center rounded-t-lg border border-b-0 text-[12.5px]',
                selected ? 'border-border bg-card text-foreground' : 'border-transparent text-muted-foreground hover:bg-accent hover:text-foreground')}>
              <button type="button" role="tab" id={`sql-tab-${tab.id}`} aria-selected={selected} tabIndex={selected ? 0 : -1}
                onClick={() => onSelect(tab.id)} onKeyDown={(event) => key(event, index)}
                title={tab.savedId !== null && !tab.mine ? `${tab.title} (shared by ${tab.ownerName})` : tab.title}
                className="flex h-full min-w-0 items-center gap-1.5 rounded-t-lg pr-1 pl-3 outline-none focus-visible:ring-2 focus-visible:ring-ring/40">
                {tab.savedId !== null && !tab.mine && <Globe aria-hidden="true" size={12} className="flex-none text-muted-foreground" />}
                <span className={cn('truncate', selected && 'font-medium')}>{tab.title}</span>
                {dirty && <><span aria-hidden="true" className="flex-none text-primary">●</span>{' '}<span className="sr-only">(unsaved changes)</span></>}
              </button>
              <button type="button" onClick={() => close(tab)} aria-label={`Close ${tab.title}`} title="Close"
                className="mr-1 grid size-5 flex-none place-items-center rounded text-muted-foreground opacity-70 outline-none hover:bg-accent hover:text-foreground hover:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/40">
                <X aria-hidden="true" size={12} />
              </button>
            </div>
          )
        })}
      </div>
      <button type="button" onClick={onNew} aria-label="New tab" title="New tab"
        className="mb-0.5 grid size-7 flex-none place-items-center rounded-md text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/40">
        <Plus aria-hidden="true" size={15} />
      </button>

      <AlertDialog open={asking !== null} onOpenChange={(next) => { if (!next) setAsking(null) }}>
        <AlertDialogContent aria-describedby={undefined}>
          <AlertDialogHeader>
            <AlertDialogTitle>Close without saving?</AlertDialogTitle>
            <p className="text-[12.5px] text-muted-foreground">The changes in "{asking?.title}" will be lost.</p>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => { if (asking) onClose(asking.id) }}>Close without saving</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
