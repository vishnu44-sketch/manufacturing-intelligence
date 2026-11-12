// History's "Chats" tab: the user's chats, newest first, grouped Today / Yesterday / Previous 7 days / Older
// (the API sends them with their group). A click opens the chat on the Ask page; the "..." of a chat opens
// its menu (Rename / Remove from list / Delete - ChatMenu); removed chats sit under the list (Restore /
// Delete). Delete asks "Are you sure?" first. This tab took the place of the chat list that sat on the left
// of the Ask page until 12-Nov. Tailwind + shadcn/ui, token colours only (light and dark theme).
import { useCallback, useEffect, useState } from 'react'
import { Ellipsis, MessageSquare, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { AuthError, api, problemText } from '../api'
import { Link, chatPath } from '../router'
import type { ChatSummary } from '../types'
import { type ChatActions, ChatMenu, deleteQuestion } from './ChatMenu'
import { Loading, plural } from './common'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from './ui/alert-dialog'
import { Button, buttonVariants } from './ui/button'
import { Card } from './ui/card'
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover'
import { Toaster } from './ui/sonner'

// app.css gives every link the brand colour: the colours of a chat's title are marked important
const TITLE = 'block truncate text-[13.5px] font-medium text-foreground! hover:text-primary!'

export default function HistoryChats() {
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

  const groups: { label: string; chats: ChatSummary[] }[] = []
  for (const chat of chats) {
    const label = chat.group ?? ''
    if (!groups.length || groups[groups.length - 1].label !== label) groups.push({ label, chats: [] })
    groups[groups.length - 1].chats.push(chat)
  }

  return (
    <div className="ui-scope flex flex-col gap-4">
      {error && <div className="errbox" role="alert">{error}</div>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-[13px] text-muted-foreground">
          Your chats, newest first. Open one to read it or to ask a follow-up question.
        </div>
        <Link to="/new" className={cn(buttonVariants({ size: 'sm' }), 'text-primary-foreground!')}>
          <Plus aria-hidden="true" strokeWidth={2.4} />New chat
        </Link>
      </div>

      {groups.length === 0 && !error && (
        <Card className="items-center gap-2 px-6 py-10 text-center">
          <MessageSquare aria-hidden="true" className="size-7 text-muted-foreground" />
          <div className="text-[15px] font-semibold text-heading">No chats yet</div>
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
                    <Link className={TITLE} to={chatPath(chat.id)} title={chat.title}>{chat.title}</Link>
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

      {removed.length > 0 && (
        <details className="rounded-lg border border-border bg-card px-3 py-2">
          <summary className="cursor-pointer rounded-md px-1 py-1 text-[12.5px] font-medium text-muted-foreground hover:text-primary">
            Removed chats ({removed.length})
          </summary>
          <ul className="mt-1 divide-y divide-border">
            {removed.map((chat) => (
              <li key={chat.id} className="flex items-center gap-1 py-1.5 pl-1">
                <Link className={cn(TITLE, 'min-w-0 flex-1 font-normal text-muted-foreground!')} to={chatPath(chat.id)} title={chat.title}>
                  {chat.title}
                </Link>
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
