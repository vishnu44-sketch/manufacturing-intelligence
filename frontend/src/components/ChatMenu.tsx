// The small menu of one chat: Rename / Remove from list / Delete. It is opened by the "..." in the head of an
// open chat (AskPage) and on each chat of History's "Chats" tab (HistoryChats). Delete asks "Are you sure?"
// first (the page's own dialog). Until 12-Nov the chats sat in a list on the left of the Ask page; the top
// bar's "New chat" and "History" took its place. Token colours only (light and dark theme).
import { type FormEvent, useEffect, useRef, useState } from 'react'
import { CircleX, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ChatSummary } from '../types'
import { plural } from './common'
import { Button } from './ui/button'
import { Input } from './ui/input'

export interface ChatActions {
  rename: (chat: ChatSummary, title: string) => Promise<boolean> // true = renamed (closes the menu)
  remove: (chat: ChatSummary) => void
  restore: (chat: ChatSummary) => void
  erase: (chat: ChatSummary) => void
}

/** The question asked before a chat is deleted for good. */
export function deleteQuestion(chat: ChatSummary): string {
  return `Delete this chat and its ${plural(chat.questions ?? 0, 'question')} permanently? This cannot be undone.`
}

export function ChatMenu({ chat, actions, onDone }: { chat: ChatSummary; actions: ChatActions; onDone: () => void }) {
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
