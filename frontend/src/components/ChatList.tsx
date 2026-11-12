// The user's chats on the left of the Ask page: "New chat" on top, the chats grouped Today / Yesterday /
// Previous 7 days / Older (the API sends them newest first with their group), the open one highlighted.
// The "..." on each chat (shown on hover) opens a small menu: Rename / Remove from list / Delete; removed
// chats sit folded at the bottom (Restore / Delete). Delete asks "Are you sure?" first (AskPage's dialog).
// On a phone the list is a drawer. Drawn with Tailwind + shadcn/ui (src/components/ui), with token colours
// only (light and dark theme): the open chat in the soft brand colour, Delete in the error red.
// The panel button next to "New chat" makes the list small (a slim rail with only "open again" and
// "New chat", so the answers get the room) - like the « of the left menu. The choice is kept in this
// browser (localStorage). On a phone (the drawer) there is no such button and the drawer shows the whole list.
import { type FormEvent, useEffect, useRef, useState } from 'react'
import { CircleX, Ellipsis, PanelLeftClose, PanelLeftOpen, Plus, Trash2, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Link, chatPath } from '../router'
import type { ChatSummary } from '../types'
import { plural } from './common'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover'

export interface ChatActions {
  rename: (chat: ChatSummary, title: string) => Promise<boolean> // true = renamed (closes the menu)
  remove: (chat: ChatSummary) => void
  restore: (chat: ChatSummary) => void
  erase: (chat: ChatSummary) => void
}

interface Props {
  chats: ChatSummary[] | null
  removed: ChatSummary[]
  activeId: number | null
  open: boolean
  onNew: () => void
  onClose: () => void
  actions: ChatActions
  slim?: boolean // made small (the rail)
  onSlim?: () => void // the panel button: small / open again
}

const SLIM_KEY = 'mi.chatListSlim'

/** Was the chat list made small in this browser? (No storage: open.) */
function readSlim(): boolean {
  try {
    return window.localStorage.getItem(SLIM_KEY) === '1'
  } catch {
    return false
  }
}

/** The small-or-open choice of the chat list, kept in this browser: [slim, toggle]. */
export function useSlimChatList(): [boolean, () => void] {
  const [slim, setSlim] = useState(readSlim)
  const toggle = () => {
    const next = !slim
    setSlim(next)
    try {
      if (next) window.localStorage.setItem(SLIM_KEY, '1')
      else window.localStorage.removeItem(SLIM_KEY)
    } catch {
      // storage blocked: small until the page is loaded again
    }
  }
  return [slim, toggle]
}

/** The question asked before a chat is deleted for good. */
export function deleteQuestion(chat: ChatSummary): string {
  return `Delete this chat and its ${plural(chat.questions ?? 0, 'question')} permanently? This cannot be undone.`
}

// a chat's title in the list (app.css gives every link the brand colour, so the colours here are marked important)
const CHAT_LINK = 'block min-w-0 flex-1 truncate py-2 pr-1 pl-3 text-[13px] leading-[1.35] text-foreground/80! hover:text-foreground!'

function ChatMenu({ chat, actions, onDone }: { chat: ChatSummary; actions: ChatActions; onDone: () => void }) {
  const [title, setTitle] = useState(chat.title)
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLInputElement>(null)
  useEffect(() => { box.current?.focus(); box.current?.select() }, [])

  async function rename(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    const done = await actions.rename(chat, title)
    setBusy(false)
    if (done) onDone()
  }

  const item = 'flex w-full items-start gap-2.5 rounded-lg px-2 py-1.5 text-left text-[12.5px] transition-colors [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:shrink-0'
  return (
    <div className="flex flex-col gap-1">
      <form className="mb-1 flex gap-1.5" onSubmit={rename}>
        <Input ref={box} value={title} maxLength={200} required aria-label="New title for this chat"
               onChange={(e) => setTitle(e.target.value)} />
        <Button type="submit" size="sm" disabled={busy}>Rename</Button>
      </form>
      <button type="button" className={cn(item, 'text-foreground hover:bg-accent')} onClick={() => { onDone(); actions.remove(chat) }}>
        <Trash2 aria-hidden="true" />
        <span className="flex flex-col gap-px font-medium">Remove from list<span className="text-[10.5px] font-normal text-faint">Hides it - its questions stay in History</span></span>
      </button>
      <button type="button" className={cn(item, 'text-destructive hover:bg-danger-soft')} onClick={() => { onDone(); actions.erase(chat) }}>
        <CircleX aria-hidden="true" />
        <span className="flex flex-col gap-px font-medium">Delete<span className="text-[10.5px] font-normal text-faint">For good - also removed from History</span></span>
      </button>
      <div className="mt-0.5 border-t border-border px-2 pt-1.5 text-[11px] text-muted-foreground">
        {plural(chat.questions ?? 0, 'question')} · last one {chat.updated_text}
      </div>
    </div>
  )
}

export default function ChatList({ chats, removed, activeId, open, onNew, onClose, actions, slim = false, onSlim }: Props) {
  const [menuFor, setMenuFor] = useState<number | null>(null)

  // made small: only the rail (open again, New chat); the phone drawer, when opened, shows the whole list
  if (slim && !open) {
    return (
      <aside className="chats slim" id="chats" aria-label="Your chats">
        <div className="flex flex-col items-center gap-2 px-2 py-3">
          <Button type="button" variant="ghost" size="icon" className="text-muted-foreground hover:text-primary"
                  onClick={onSlim} aria-expanded={false} aria-label="Show the chat list" title="Show the chat list">
            <PanelLeftOpen aria-hidden="true" className="size-[18px]" />
          </Button>
          <Button type="button" size="icon" onClick={onNew} aria-label="New chat" title="New chat">
            <Plus aria-hidden="true" strokeWidth={2.4} />
          </Button>
        </div>
      </aside>
    )
  }

  const groups: { label: string; chats: ChatSummary[] }[] = []
  for (const chat of chats ?? []) {
    const label = chat.group ?? ''
    if (!groups.length || groups[groups.length - 1].label !== label) groups.push({ label, chats: [] })
    groups[groups.length - 1].chats.push(chat)
  }
  const activeRemoved = removed.some((chat) => chat.id === activeId)

  return (
    <aside className={`chats${open ? ' open' : ''}`} id="chats" aria-label="Your chats">
      <div className="flex items-center gap-2 border-b border-border p-3">
        <Button type="button" className="flex-1" onClick={onNew}>
          <Plus aria-hidden="true" strokeWidth={2.4} />
          New chat
        </Button>
        {onSlim && (
          <Button type="button" variant="ghost" size="icon" className="text-muted-foreground hover:text-primary max-[901px]:hidden"
                  onClick={onSlim} aria-expanded={true} aria-label="Hide the chat list" title="Hide the chat list">
            <PanelLeftClose aria-hidden="true" className="size-[18px]" />
          </Button>
        )}
        <Button type="button" variant="secondary" size="icon" className="min-[901px]:hidden" onClick={onClose}
                aria-label="Close the chat list">
          <X aria-hidden="true" className="size-[18px]" />
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pt-1 pb-3.5 [scrollbar-width:thin]">
        {chats === null && <div className="px-2.5 py-4 text-[12.5px] leading-normal text-muted-foreground">Loading your chats…</div>}
        {chats !== null && groups.length === 0 && (
          <div className="px-2.5 py-4 text-[12.5px] leading-normal text-muted-foreground">
            No chats yet. Each conversation you start is kept here.
          </div>
        )}
        {groups.map((group) => (
          <div key={group.label}>
            {group.label && (
              <div className="px-2.5 pt-3.5 pb-1.5 text-[10.5px] font-semibold tracking-[.08em] text-faint uppercase">{group.label}</div>
            )}
            {group.chats.map((chat) => {
              const active = chat.id === activeId
              const menuOpen = menuFor === chat.id
              return (
                <div key={chat.id} className={cn('chat-row group/row', active && 'active')}>
                  <Popover open={menuOpen} onOpenChange={(next) => setMenuFor(next ? chat.id : null)}>
                    <div className={cn('flex items-center rounded-lg transition-colors hover:bg-muted',
                      active && 'bg-primary-soft hover:bg-primary-soft', menuOpen && !active && 'bg-muted')}>
                      <Link className={cn(CHAT_LINK, active && 'font-semibold text-primary! hover:text-primary!')}
                            to={chatPath(chat.id)} title={chat.title} aria-current={active ? 'page' : undefined}>
                        {chat.title}
                      </Link>
                      <PopoverTrigger asChild>
                        <Button type="button" variant="ghost" size="icon-sm"
                                className={cn('mr-1 size-7 opacity-0 transition-opacity hover:bg-card hover:text-primary focus-visible:opacity-100',
                                  'group-hover/row:opacity-100 data-[state=open]:bg-card data-[state=open]:text-primary data-[state=open]:opacity-100',
                                  'max-[901px]:opacity-100 [@media(hover:none)]:opacity-100', active && 'opacity-100')}
                                aria-label="Options for this chat" title="Rename, remove or delete">
                          <Ellipsis aria-hidden="true" />
                        </Button>
                      </PopoverTrigger>
                    </div>
                    <PopoverContent portal={false} align="end" side="bottom" className="w-[min(17rem,calc(100vw-2rem))] p-2.5">
                      <ChatMenu chat={chat} actions={actions} onDone={() => setMenuFor(null)} />
                    </PopoverContent>
                  </Popover>
                </div>
              )
            })}
          </div>
        ))}

        {removed.length > 0 && (
          <details className="mt-3.5 border-t border-border pt-1.5" open={activeRemoved || undefined}>
            <summary className="cursor-pointer rounded-md px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:text-primary">
              Removed chats ({removed.length})
            </summary>
            {removed.map((chat) => (
              <div key={chat.id} className={cn('flex items-center gap-0.5 rounded-lg', chat.id === activeId && 'bg-muted')}>
                <Link className={cn(CHAT_LINK, 'text-faint!')} to={chatPath(chat.id)} title={chat.title}>{chat.title}</Link>
                <Button type="button" variant="ghost" size="xs" className="text-[11.5px] text-info hover:bg-info-soft hover:text-info"
                        onClick={() => actions.restore(chat)}>Restore</Button>
                <Button type="button" variant="ghost" size="xs" className="text-[11.5px] text-destructive hover:bg-danger-soft hover:text-destructive"
                        onClick={() => actions.erase(chat)}>Delete</Button>
              </div>
            ))}
          </details>
        )}
      </div>
    </aside>
  )
}
