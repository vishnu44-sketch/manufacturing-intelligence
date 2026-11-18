// History's "Chats" tab: the user's chats, newest first, grouped Today / Yesterday / Previous 7 days / Older
// (the API sends them with their group). A click opens the chat on the Ask page; the "..." of a chat opens
// its menu (Rename / Remove from list / Delete - ChatMenu); removed chats sit under the list (Restore /
// Delete). Delete asks "Are you sure?" first. This tab took the place of the chat list that sat on the left
// of the Ask page until 12-Nov. Tailwind + shadcn/ui, token colours only (light and dark theme).
// 17-Nov: a chat started on ML Insights (mode "ml") has a small "ML" badge and opens on that page
// (/insights?chat=<id>); the other chats open on the Assistant as before.
// 18-Nov: a switch at the top - "Assistant (N)" (the first one) | "ML Insights (N)" | "All (N)" - shows the
// chats of one place or both (the removed ones filtered the same way). The Questions tab has the same switch;
// the last choice is kept in this browser (localStorage) for both.
import { useCallback, useEffect, useState } from 'react'
import { Ellipsis, MessageSquare, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { AuthError, api, problemText } from '../api'
import { Link, NEW_ML_CHAT_PATH, openChatPath } from '../router'
import type { ChatSummary, HistoryMode } from '../types'
import { type ChatActions, ChatMenu, deleteQuestion } from './ChatMenu'
import { Loading, plural } from './common'
import { Badge } from './ui/badge'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from './ui/alert-dialog'
import { Button, buttonVariants } from './ui/button'
import { Card } from './ui/card'
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover'
import { Segmented, SegmentedItem } from './ui/segmented'
import { Toaster } from './ui/sonner'

// app.css gives every link the brand colour: the colours of a chat's title are marked important
const TITLE = 'block truncate text-[13.5px] font-medium text-foreground! hover:text-primary!'

/** The small "ML" badge of a chat (or a question) of ML Insights (nothing for the Assistant's). */
export function MlBadge({ mode, title = 'A chat of ML Insights - it opens there', label = ' Insights chat' }:
  { mode?: string; title?: string; label?: string }) {
  if (mode !== 'ml') return null
  return (
    <Badge variant="info" title={title} className="h-5 flex-none px-1.5 text-[10.5px] font-semibold">
      ML<span className="sr-only">{label}</span>
    </Badge>
  )
}

// ---------- History's switch: Assistant | ML Insights | All (18-Nov) ----------
const MODE_KEY = 'mi.historyMode'
const MODES: [HistoryMode, string][] = [['assistant', 'Assistant'], ['ml', 'ML Insights'], ['all', 'All']]

/** The switch's last choice in this browser (no storage, or nothing kept: the Assistant). */
export function readHistoryMode(): HistoryMode {
  try {
    const kept = window.localStorage.getItem(MODE_KEY)
    return kept === 'ml' || kept === 'all' ? kept : 'assistant'
  } catch {
    return 'assistant'
  }
}

/** Keeps the switch's choice for the next visit (the Assistant, the first one, is kept as nothing). */
export function saveHistoryMode(mode: HistoryMode) {
  try {
    if (mode === 'assistant') window.localStorage.removeItem(MODE_KEY)
    else window.localStorage.setItem(MODE_KEY, mode)
  } catch {
    // storage blocked: the choice lasts until the page is loaded again
  }
}

/** Does a chat (or a question) of this mode ('ml' / '') show under this choice of the switch? */
export const inMode = (choice: HistoryMode, mode?: string) => choice === 'all' || (mode === 'ml') === (choice === 'ml')

/** The switch: "Assistant (3)" | "ML Insights (1)" | "All (4)" (no counts yet: the names alone). */
export function ModeSwitch({ value, counts, onChange, label }:
  { value: HistoryMode; counts?: Record<HistoryMode, number>; onChange: (mode: HistoryMode) => void; label: string }) {
  return (
    <Segmented aria-label={label} className="max-w-full overflow-x-auto">
      {MODES.map(([mode, name]) => (
        <SegmentedItem key={mode} pressed={value === mode} onClick={() => onChange(mode)}>
          {counts ? `${name} (${counts[mode]})` : name}
        </SegmentedItem>
      ))}
    </Segmented>
  )
}

export default function HistoryChats() {
  const [mode, setMode] = useState<HistoryMode>(readHistoryMode)
  const [chats, setChats] = useState<ChatSummary[] | null>(null)
  const [removed, setRemoved] = useState<ChatSummary[]>([])
  const [error, setError] = useState('')
  const [menuFor, setMenuFor] = useState<number | null>(null)
  const [toDelete, setToDelete] = useState<ChatSummary | null>(null) // the chat the "Are you sure?" dialog asks about
  const [askingDelete, setAskingDelete] = useState(false)

  const refresh = useCallback(() => {
    return api.chats().then((data) => {
      setChats(data.chats)
      setRemoved(data.removed)
      setError('')
    }).catch((err) => {
      if (err instanceof AuthError) return
      setError(problemText(err))
      setChats((old) => old ?? [])
    })
  }, [])
  useEffect(() => { refresh() }, [refresh])

  /** One chat action: the API call, its message, the list again; a failure is shown as a message. */
  async function run(call: () => Promise<{ message?: string }>): Promise<boolean> {
    try {
      const reply = await call()
      if (reply.message) toast.success(reply.message)
      await refresh()
      return true
    } catch (err) {
      if (!(err instanceof AuthError)) toast.error(problemText(err))
      return false
    }
  }
  const actions: ChatActions = {
    rename: (chat, title) => run(async () => { await api.renameChat(chat.id, title); return {} }),
    remove: (chat) => { run(() => api.removeChat(chat.id)) },
    restore: (chat) => { run(async () => { await api.restoreChat(chat.id); return {} }) },
    erase: (chat) => { // asks first: the dialog below; "Delete" there deletes
      setToDelete(chat)
      setAskingDelete(true)
    },
  }

  if (chats === null) return <Loading />

  const choose = (next: HistoryMode) => {
    setMode(next)
    saveHistoryMode(next)
    setMenuFor(null)
  }
  const ml = chats.filter((chat) => chat.mode === 'ml').length
  const counts = { assistant: chats.length - ml, ml, all: chats.length }
  const shown = chats.filter((chat) => inMode(mode, chat.mode))
  const shownRemoved = removed.filter((chat) => inMode(mode, chat.mode))

  const groups: { label: string; chats: ChatSummary[] }[] = []
  for (const chat of shown) {
    const label = chat.group ?? ''
    if (!groups.length || groups[groups.length - 1].label !== label) groups.push({ label, chats: [] })
    groups[groups.length - 1].chats.push(chat)
  }

  return (
    <div className="ui-scope flex flex-col gap-4">
      {error && <div className="errbox" role="alert">{error}</div>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ModeSwitch label="Which chats to show" value={mode} counts={counts} onChange={choose} />
        {/* on ML Insights' switch a new chat starts there; otherwise on the Assistant */}
        <Link to={mode === 'ml' ? NEW_ML_CHAT_PATH : '/new'} className={cn(buttonVariants({ size: 'sm' }), 'text-primary-foreground!')}>
          <Plus aria-hidden="true" strokeWidth={2.4} />New chat
        </Link>
      </div>
      <div className="-mt-1 text-[13px] text-muted-foreground">
        Your chats, newest first. Open one to read it or to ask a follow-up question.
      </div>

      {groups.length === 0 && !error && (
        <Card className="items-center gap-2 px-6 py-10 text-center">
          <MessageSquare aria-hidden="true" className="size-7 text-muted-foreground" />
          <div className="text-[15px] font-semibold text-heading">
            {chats.length === 0 || mode === 'all' ? 'No chats yet' : mode === 'ml' ? 'No ML Insights chats yet' : 'No Assistant chats yet'}
          </div>
          <div className="text-[13px] text-muted-foreground">Each conversation you start is kept here.</div>
        </Card>
      )}

      {groups.map((group) => (
        <section key={group.label} aria-label={group.label || 'Chats'}>
          {group.label && (
            <div className="px-1 pb-1.5 text-[10.5px] font-semibold tracking-[.08em] text-faint uppercase">{group.label}</div>
          )}
          <Card className="gap-0 p-0">
            <ul className="divide-y divide-border">
              {group.chats.map((chat) => (
                <li key={chat.id} className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-muted">
                  <MessageSquare aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-2">
                      <Link className={cn(TITLE, 'min-w-0')} to={openChatPath(chat)} title={chat.title}>{chat.title}</Link>
                      <MlBadge mode={chat.mode} />
                    </div>
                    <div className="mt-0.5 text-[11.5px] text-muted-foreground">
                      {plural(chat.questions ?? 0, 'question')} · last one {chat.updated_text}
                    </div>
                  </div>
                  <Popover open={menuFor === chat.id} onOpenChange={(next) => setMenuFor(next ? chat.id : null)}>
                    <PopoverTrigger asChild>
                      <Button type="button" variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-primary"
                              aria-label={`Options for the chat ${chat.title}`} title="Rename, remove or delete">
                        <Ellipsis aria-hidden="true" />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent portal={false} align="end" side="bottom" className="w-[min(17rem,calc(100vw-2rem))] p-2.5">
                      <ChatMenu chat={chat} actions={actions} onDone={() => setMenuFor(null)} />
                    </PopoverContent>
                  </Popover>
                </li>
              ))}
            </ul>
          </Card>
        </section>
      ))}

      {shownRemoved.length > 0 && (
        <details className="rounded-lg border border-border bg-card px-3 py-2">
          <summary className="cursor-pointer rounded-md px-1 py-1 text-[12.5px] font-medium text-muted-foreground hover:text-primary">
            Removed chats ({shownRemoved.length})
          </summary>
          <ul className="mt-1 divide-y divide-border">
            {shownRemoved.map((chat) => (
              <li key={chat.id} className="flex items-center gap-1 py-1.5 pl-1">
                <Link className={cn(TITLE, 'min-w-0 flex-1 font-normal text-muted-foreground!')} to={openChatPath(chat)} title={chat.title}>
                  {chat.title}
                </Link>
                <MlBadge mode={chat.mode} />
                <Button type="button" variant="ghost" size="xs" className="text-[11.5px] text-info hover:bg-info-soft hover:text-info"
                        onClick={() => actions.restore(chat)}>Restore</Button>
                <Button type="button" variant="ghost" size="xs" className="text-[11.5px] text-destructive hover:bg-danger-soft hover:text-destructive"
                        onClick={() => actions.erase(chat)}>Delete</Button>
              </li>
            ))}
          </ul>
        </details>
      )}

      <Toaster position="top-center" duration={6000} />
      <AlertDialog open={askingDelete} onOpenChange={setAskingDelete}>
        <AlertDialogContent aria-describedby={undefined}>
          <AlertDialogHeader>
            <AlertDialogTitle>{toDelete && deleteQuestion(toDelete)}</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => { if (toDelete) run(() => api.deleteChat(toDelete.id)) }}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
