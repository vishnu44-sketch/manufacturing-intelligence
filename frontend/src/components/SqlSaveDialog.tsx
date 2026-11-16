// The small "Save query" dialog of the SQL page: a name box and a "Share with all admins" switch. Used for
// the first Save of a new tab and for every "Save as…". The API's message (a name taken, too long, the
// limit of saved queries) shows inside the dialog, which then stays open.
import { type FormEvent, useEffect, useState } from 'react'
import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from './ui/alert-dialog'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { Spinner } from './ui/spinner'
import { Switch } from './ui/switch'

export const NAME_MAX = 200

export interface SaveRequest {
  heading: string // "Save query" or "Save as"
  name: string // the name the box starts with
  shared: boolean
}

export function SqlSaveDialog({ request, busy, error, onSave, onCancel }:
  { request: SaveRequest | null; busy: boolean; error: string;
    onSave: (name: string, shared: boolean) => void; onCancel: () => void }) {
  const [name, setName] = useState('')
  const [shared, setShared] = useState(false)
  // each time the dialog opens it starts from the request's name and switch
  useEffect(() => {
    if (request) {
      setName(request.name)
      setShared(request.shared)
    }
  }, [request])

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!busy && name.trim()) onSave(name.trim(), shared)
  }

  return (
    <AlertDialog open={request !== null} onOpenChange={(open) => { if (!open && !busy) onCancel() }}>
      <AlertDialogContent aria-describedby={undefined}>
        <form onSubmit={submit} className="grid gap-4">
          <AlertDialogHeader>
            <AlertDialogTitle>{request?.heading ?? 'Save query'}</AlertDialogTitle>
          </AlertDialogHeader>
          <label className="grid gap-1.5 text-[12.5px] font-medium">
            Name
            <Input value={name} onChange={(event) => setName(event.target.value)} maxLength={NAME_MAX} required autoFocus
              aria-label="Name of the query" placeholder="e.g. Open orders by customer" />
          </label>
          <div className="flex items-center gap-2.5 text-[12.5px]">
            <Switch checked={shared} onCheckedChange={setShared} aria-label="Share with all admins" id="sql-save-share" />
            <label htmlFor="sql-save-share" className="cursor-pointer">
              Share with all admins
              <span className="block text-[11px] text-muted-foreground">They can open and copy it; only you can change it.</span>
            </label>
          </div>
          {error && (
            <div role="alert" className="rounded-lg border border-destructive/40 bg-danger-soft px-3 py-1.5 text-[12.5px] text-destructive">
              {error}
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
            <Button type="submit" disabled={busy || !name.trim()}>{busy && <Spinner />} Save</Button>
          </AlertDialogFooter>
        </form>
      </AlertDialogContent>
    </AlertDialog>
  )
}
