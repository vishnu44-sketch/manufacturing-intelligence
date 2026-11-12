// The Ask page: the chat list on the left, the open chat on the right (question bubbles and answer
// cards) and the question box at the bottom. Three views on the right:
// - a chat (/c/<id>): its questions oldest first; the newest answer loads its rows at once; each
//   question has a pencil to edit it (its new answer takes the old one's place);
// - one saved answer (/q/<id>): the card with its rows; asking there continues its chat;
// - the start screen (/new, or /ask without chats): a big heading, the question box in the middle of the
//   page and four starter cards (AskStart.tsx). After the first question the box sits at the bottom.
// Asking streams the answer (/api/ask/stream): the steps show as they run ("Search the notes in Qdrant …"),
// then the answer grows word by word, and the finished card takes its place. When the stream cannot be
// used (nothing comes back, e.g. a proxy), it asks the plain way (/api/ask) and shows "Thinking…".
// History's "Ask again" lands here (/new with the question in the navigation state) and asks at once.
// Drawn with Tailwind + shadcn/ui (src/components/ui); the page's root has the class "ui-scope" (see
// src/tailwind.css). The grid / scrolling / phone-drawer layout still comes from app.css (ask-layout,
// chats, conv, conv-scroll, composer ...). Messages (a chat removed or deleted, a failed chat action) show
// as toasts; deleting a chat asks in a dialog first. Colours are Tailwind token classes only (no fixed
// colours), so the page follows the light and the dark theme.
import { type KeyboardEvent, type ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUp, Check, Ellipsis, Info, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { AuthError, StreamUnavailable, api, problemText } from '../api'
import { ASK_PATH, Link, chatPath, useRouter } from '../router'
import type { AskResponse, Card, ChatDetail, ChatSummary, Me, SavedAnswer } from '../types'
import AnswerCard from './AnswerCard'
import AskStart from './AskStart'
import { type ChatActions, ChatMenu, deleteQuestion } from './ChatMenu'
import { plural } from './common'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from './ui/alert-dialog'
import { Button } from './ui/button'
import { Card as Box } from './ui/card'
import { Dots } from './ui/dots'
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover'
import { Toaster } from './ui/sonner'
import { Spinner } from './ui/spinner'
import { Textarea } from './ui/textarea'

/** What History's "Ask again" passes along when it opens this page. */
export interface AskAgain {
  again: { id: number; text: string }
}

function isAskAgain(state: unknown): state is AskAgain {
  const again = (state as AskAgain | null)?.again
  return !!again && typeof again.id === 'number' && typeof again.text === 'string'
}

/** The card of "Thinking…" and of the streamed steps. */
const WAIT_BOX = 'self-start max-w-full rounded-xl border border-border bg-card px-4 py-3 text-[13px] text-muted-foreground shadow-xs'

/** "Thinking…" under a sent question - or, while the answer streams, the steps so far (the last one is
 *  running); after 20 s and 60 s it says why it takes so long. */
function Thinking({ text = 'Thinking… writing the SQL and checking it', steps = [] }: { text?: string; steps?: string[] }) {
  const [slow, setSlow] = useState(0)
  useEffect(() => {
    const first = window.setTimeout(() => setSlow(1), 20000)
    const second = window.setTimeout(() => setSlow(2), 60000)
    return () => { window.clearTimeout(first); window.clearTimeout(second) }
  }, [])
  const slowText = slow === 1 ? 'Still working… the AI service is busy, so this can take up to a minute.'
    : slow === 2 ? <>Still working… the answer is saved as soon as it is ready - you can also find it in <Link to="/history">History</Link>.</>
    : null
  if (steps.length) {
    // a small progress list: a green tick on a finished step, the dots on the running one
    // (the <li> keep the class names "done" / "now")
    return (
      <div className={cn(WAIT_BOX, 'flex w-[min(420px,100%)] flex-col gap-2')} role="status">
        <ol aria-label="Steps"
            className={cn('flex flex-col gap-2 [&>li]:flex [&>li]:items-center [&>li]:gap-2.5',
              '[&>li.done]:text-muted-foreground [&>li.now]:font-medium [&>li.now]:text-heading')}>
          {steps.map((label, i) => (i < steps.length - 1
            ? (
              <li key={i} className="done">
                <span className="grid size-5 shrink-0 place-items-center rounded-full bg-success-soft text-success" aria-hidden="true">
                  <Check className="size-3" strokeWidth={3} />
                </span>
                {label}
              </li>
            ) : (
              <li key={i} className="now" aria-current="step">
                <span className="grid size-5 shrink-0 place-items-center rounded-full bg-primary-soft" aria-hidden="true">
                  <Dots className="gap-[2px] [&>i]:size-1" />
                </span>
                {label}…
              </li>
            )))}
        </ol>
        {slowText && <div className="border-t border-border pt-2 text-xs">{slowText}</div>}
      </div>
    )
  }
  return (
    <div className={cn(WAIT_BOX, 'inline-flex items-center gap-2.5')} role="status">
      <Dots />{' '}
      {slowText ?? text}
    </div>
  )
}

/** The answer while it is being written (streamed), until the finished card takes its place. */
function LiveAnswer({ text }: { text: string }) {
  return (
    <Box className="live-answer px-5 py-4 max-[760px]:px-3.5" aria-live="polite" aria-busy="true">
      <div className="answer text-[15px] leading-[1.65] text-foreground [overflow-wrap:anywhere]">{text}<span className="caret" aria-hidden="true" /></div>
    </Box>
  )
}

/** What the streamed answer has shown so far: the steps that started, and the answer's text. */
type Live = { steps: string[]; text: string }

function scrollTo(el: HTMLElement | null, block: ScrollLogicalPosition) {
  el?.scrollIntoView?.({ block, behavior: 'smooth' }) // (jsdom has no scrollIntoView)
}

/** The grow-with-the-text height of a question box (up to 220 px). */
function grow(el: HTMLTextAreaElement | null, extra = 0) {
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight + extra, 220)}px`
}

/** A question bubble (on the right, in the brand colour); keeps the class "bubble". */
function Bubble({ text }: { text: string }) {
  return (
    <div className={cn('bubble max-w-[min(720px,88%)] rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-sm leading-normal',
      'whitespace-pre-wrap text-primary-foreground shadow-sm [overflow-wrap:anywhere] max-[700px]:max-w-full')}>
      {text}
    </div>
  )
}

function QuestionTime({ children }: { children: ReactNode }) {
  return <div className="mt-1 text-[11px] text-muted-foreground">{children}</div>
}

/** One question of a chat: its bubble with the pencil, or the edit box while it is edited. */
function QuestionBubble({ card, me, editable, onEdit }:
  { card: Card; me: Me; editable: boolean; onEdit: (card: Card, text: string) => Promise<string> }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(card.text)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const box = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!editing) return
    grow(box.current, 2)
    box.current?.focus()
    box.current?.setSelectionRange(box.current.value.length, box.current.value.length)
  }, [editing])
  useEffect(() => { grow(box.current, 2) }, [text])

  function cancel() {
    if (sending) return
    setEditing(false)
    setText(card.text)
    setError('')
  }

  async function save() {
    if (!text.trim()) { box.current?.focus(); return }
    if (sending) return
    setSending(true)
    setError('')
    const problem = await onEdit(card, text.trim())
    setSending(false) // on success this bubble is replaced by the new question's
    if (problem) setError(problem)
  }

  function onKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Escape') { event.stopPropagation(); cancel(); return }
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      save()
    }
  }

  return (
    <>
      <div className="group/q flex flex-col items-end">
        {!editing && (
          <div className="flex w-full items-center justify-end gap-2">
            {editable && (
              <Button type="button" variant="ghost" size="icon-sm" title="Edit this question" aria-label="Edit this question"
                      className={cn('opacity-0 transition-opacity group-hover/q:opacity-100 hover:bg-card hover:text-primary',
                        'focus-visible:opacity-100 [@media(hover:none)]:opacity-100')}
                      onClick={() => setEditing(true)}>
                <Pencil aria-hidden="true" className="size-3.5" />
              </Button>
            )}
            <Bubble text={card.text} />
          </div>
        )}
        {editing && (
          <form className="w-[min(720px,100%)] rounded-2xl border border-primary bg-card px-3 py-2.5 shadow-md ring-3 ring-primary/10"
                onSubmit={(e) => { e.preventDefault(); save() }}>
            <Textarea ref={box} rows={2} maxLength={me.max_question_chars} required aria-label="Edit the question"
                      className="min-h-11 border-0! bg-transparent! px-0.5! py-1! shadow-none focus-visible:ring-0"
                      value={text} readOnly={sending} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} />
            <div className="mt-1 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-2">
              <span className="mr-auto text-[11.5px] text-muted-foreground">The new answer replaces this one here; the old version stays in History.</span>
              <Button type="button" variant="outline" size="sm" onClick={cancel} disabled={sending}>Cancel</Button>
              <Button type="submit" size="sm" disabled={sending}>
                {sending && <Spinner />}Save &amp; ask
              </Button>
            </div>
          </form>
        )}
        <QuestionTime>{card.created_text}{card.edited && ' · edited'}</QuestionTime>
      </div>
      {error && <div className="errbox" role="alert">{error}</div>}
      {sending && <Thinking text="Thinking… asking the edited question" />}
    </>
  )
}

// the tips behind the (i) under the question box
const TIPS = 'Follow-up questions work ("and for Sep?", "same for export") - the AI sees the last 3 questions of '
  + 'this chat. A month name means the NOP sales month (21st to 20th) unless you say "calendar month".'

export default function AskPage({ me }: { me: Me }) {
  const { route, state, navigate } = useRouter()
  const [chats, setChats] = useState<ChatSummary[] | null>(null)
  const [removed, setRemoved] = useState<ChatSummary[]>([])
  const [detail, setDetail] = useState<ChatDetail | null>(null)
  const [single, setSingle] = useState<SavedAnswer | null>(null)
  const [loadError, setLoadError] = useState('')
  const [pending, setPending] = useState<string | null>(null)
  const [live, setLive] = useState<Live | null>(null) // the streamed progress of the pending question
  const [askError, setAskError] = useState('')
  const [question, setQuestion] = useState(route.kind === 'new' ? route.q.slice(0, me.max_question_chars) : '')
  const [justAsked, setJustAsked] = useState<number | null>(null)
  const [notices, setNotices] = useState<Record<number, string>>({}) // one-time token notices, by card id
  const [menuOpen, setMenuOpen] = useState(false) // the "..." menu of the open chat (rename / remove / delete)
  const [toDelete, setToDelete] = useState<ChatSummary | null>(null) // the chat the "Are you sure?" dialog asks about
  const [askingDelete, setAskingDelete] = useState(false) // that dialog is open
  const box = useRef<HTMLTextAreaElement>(null)
  const newest = useRef<HTMLDivElement>(null)
  const sending = useRef<HTMLDivElement>(null)
  const againDone = useRef<unknown>(null) // the "Ask again" already sent (React's dev mode runs effects twice)
  const chatId = route.kind === 'chat' ? route.id : null
  const questionId = route.kind === 'question' ? route.id : null

  // the desktop layout of the Ask page (only the conversation scrolls) hangs on this body class
  useEffect(() => {
    document.body.classList.add('page-ask')
    return () => document.body.classList.remove('page-ask')
  }, [])

  const refreshChats = useCallback(() => {
    return api.chats().then((data) => {
      setChats(data.chats)
      setRemoved(data.removed)
      return data
    }).catch((error) => {
      if (!(error instanceof AuthError)) setChats((old) => old ?? [])
      return null
    })
  }, [])
  useEffect(() => { refreshChats() }, [refreshChats])

  // /ask opens the most recently used chat (or the new-chat screen when there is none)
  useEffect(() => {
    if (route.kind === 'latest' && chats && chats.length) navigate(chatPath(chats[0].id), { replace: true })
  }, [route, chats, navigate])

  // /new?q=... (an example link) fills the box
  useEffect(() => {
    if (route.kind === 'new' && route.q) setQuestion(route.q.slice(0, me.max_question_chars))
  }, [route, me.max_question_chars])

  // open a chat: its saved cards (no AI call); a chat just made by asking is already here
  useEffect(() => {
    if (chatId === null) {
      setDetail(null)
      return
    }
    if (detail?.chat.id === chatId) return
    let gone = false
    setLoadError('')
    api.chat(chatId)
      .then((data) => { if (!gone) setDetail(data) })
      .catch((error) => {
        if (gone || error instanceof AuthError) return
        setDetail(null)
        setLoadError(error.status === 404 ? 'This chat was not found.' : problemText(error))
      })
    return () => { gone = true }
  }, [chatId]) // eslint-disable-line react-hooks/exhaustive-deps

  // open one saved answer: its card; the box gets its question, asking continues its chat
  useEffect(() => {
    setSingle(null)
    if (questionId === null) return
    let gone = false
    setLoadError('')
    api.question(questionId)
      .then((data) => {
        if (gone) return
        setSingle(data)
        setQuestion(data.card.text)
      })
      .catch((error) => {
        if (gone || error instanceof AuthError) return
        setLoadError(error.status === 404 ? 'This answer was not found.' : problemText(error))
      })
    return () => { gone = true }
  }, [questionId])

  // show the newest answer (or the question being asked)
  useEffect(() => { scrollTo(newest.current, 'start') }, [detail?.chat.id, detail?.cards.length])
  useEffect(() => { if (pending) scrollTo(sending.current, 'end') }, [pending])
  useEffect(() => { grow(box.current) }, [question])

  /** Shows a just-asked answer: in the chat already on screen, or opens its chat. */
  function showAnswer(reply: AskResponse, startedIn: number | null) {
    setNotices((old) => ({ ...old, [reply.card.id]: reply.card.token_notice }))
    setJustAsked(reply.card.id)
    if (detail && detail.chat.id === reply.chat.id) {
      setDetail({ ...detail, chat: reply.chat, total: detail.total + 1, cards: [...detail.cards, reply.card] })
    } else if (startedIn === null) {
      setDetail({ chat: reply.chat, total: 1, earlier: 0, cards: [reply.card] }) // a new chat: this is all of it
    } else {
      setDetail(null) // its chat has more questions: load them
    }
    if (chatId !== reply.chat.id) navigate(chatPath(reply.chat.id))
    refreshChats()
  }

  async function run(text: string, call: () => Promise<AskResponse>, startedIn: number | null, keep: string) {
    setPending(text)
    setAskError('')
    toast.dismiss()
    try {
      showAnswer(await call(), startedIn)
    } catch (error) {
      if (error instanceof AuthError) return // the app shows the Login page
      setAskError(problemText(error, 'The question could not be asked.'))
      setQuestion(keep) // keep what was typed
    } finally {
      setPending(null)
      setLive(null)
    }
  }

  /** Asks with the streamed answer, or the plain way when the stream cannot be used at all. */
  async function askLive(text: string, target: number | null): Promise<AskResponse> {
    setLive({ steps: [], text: '' })
    try {
      return await api.askStream(text, target, (event) => {
        if (event.type === 'step') {
          setLive((old) => old && (old.steps[old.steps.length - 1] === event.label ? old
            : { ...old, steps: [...old.steps, event.label] }))
        } else if (event.type === 'token') {
          setLive((old) => old && { ...old, text: old.text + event.text })
        }
      })
    } catch (error) {
      if (!(error instanceof StreamUnavailable)) throw error
      setLive(null) // "Thinking…" while the plain call runs
      return api.ask(text, target)
    }
  }

  function send() {
    const text = question.trim()
    if (!text || pending) {
      box.current?.focus()
      return
    }
    const target = chatId ?? single?.chat?.id ?? null
    setQuestion('')
    run(text, () => askLive(text, target), target, text)
  }

  // History's "Ask again": asks at once in a new chat (once, also after Back)
  useEffect(() => {
    if (route.kind !== 'new' || !isAskAgain(state) || againDone.current === state) return
    againDone.current = state
    const { id, text } = state.again
    window.history.replaceState(null, '', window.location.pathname) // a refresh does not ask again
    run(text, () => api.askAgain(id), null, text)
  }, [route, state]) // eslint-disable-line react-hooks/exhaustive-deps

  /** Edit an old question: '' when done, else the message to show under its box. */
  async function edit(card: Card, text: string): Promise<string> {
    try {
      const reply = await api.edit(card.id, text)
      setNotices((old) => ({ ...old, [reply.card.id]: reply.card.token_notice }))
      setJustAsked(reply.card.id)
      setDetail((old) => old && {
        ...old,
        chat: reply.chat ?? old.chat,
        cards: old.cards.map((c) => (c.id === reply.replaced ? reply.card : c)),
      })
      refreshChats()
      return ''
    } catch (error) {
      if (error instanceof AuthError) return ''
      return problemText(error, 'The edited question could not be asked.')
    }
  }

  /** Deletes a chat for good (after "Delete" in the dialog). */
  async function eraseNow(chat: ChatSummary) {
    try {
      const reply = await api.deleteChat(chat.id)
      toast.success(reply.message)
      if (chat.id === chatId) {
        setDetail(null)
        navigate(ASK_PATH, { replace: true })
      }
      refreshChats()
    } catch (error) {
      if (!(error instanceof AuthError)) toast.error(problemText(error))
    }
  }

  // the chat menu
  const actions: ChatActions = {
    rename: async (chat, title) => {
      try {
        const reply = await api.renameChat(chat.id, title)
        setDetail((old) => (old && old.chat.id === chat.id ? { ...old, chat: { ...old.chat, title: reply.chat.title } } : old))
        refreshChats()
        return true
      } catch (error) {
        if (!(error instanceof AuthError)) toast.error(problemText(error))
        return false
      }
    },
    remove: async (chat) => {
      try {
        const reply = await api.removeChat(chat.id)
        toast.success(reply.message)
        if (chat.id === chatId) navigate(ASK_PATH, { replace: true }) // never back into the removed chat
        refreshChats()
      } catch (error) {
        if (!(error instanceof AuthError)) toast.error(problemText(error))
      }
    },
    restore: async (chat) => {
      try {
        await api.restoreChat(chat.id)
        toast.dismiss()
        setDetail((old) => (old && old.chat.id === chat.id ? { ...old, chat: { ...old.chat, archived: false } } : old))
        if (chat.id !== chatId) navigate(chatPath(chat.id))
        refreshChats()
      } catch (error) {
        if (!(error instanceof AuthError)) toast.error(problemText(error))
      }
    },
    erase: (chat) => { // asks first: the dialog at the bottom; "Delete" there runs eraseNow
      setToDelete(chat)
      setAskingDelete(true)
    },
  }

  function onKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      send()
    }
  }

  function fillExample(text: string) {
    setQuestion(text)
    box.current?.focus()
  }

  const chat = route.kind === 'chat' ? detail?.chat ?? null : null
  const showWelcome = !chat && !single && !loadError && route.kind !== 'question' && route.kind !== 'chat'
    && (route.kind === 'new' || (route.kind === 'latest' && chats !== null && chats.length === 0))
  // the start screen: a new / empty chat with nothing being asked - the question box is in the middle of the page
  const start = showWelcome && !pending
  const cards = route.kind === 'chat' ? detail?.cards ?? [] : []
  const withNotice = (card: Card) => (notices[card.id] ? { ...card, token_notice: notices[card.id] } : card)
  const listedChat = (id: number) => [...(chats ?? []), ...removed].find((c) => c.id === id)
  const filled = question.trim() !== ''
  // the first question moves the box from the middle of the page to the bottom: the cursor stays in it
  useEffect(() => { if (!start && pending) box.current?.focus() }, [start]) // eslint-disable-line react-hooks/exhaustive-deps

  // The question box: a rounded card with the text and a round send button (in the brand colour when there
  // is text, grey when empty): two rows of text and, under them, the button at the right. The same box on the
  // start screen (bigger shadow) and under a conversation.
  const sendButton = (
    <Button type="submit" size="icon" aria-label="Ask" title="Ask (Enter)" disabled={pending !== null}
            className={cn('rounded-full', start ? 'size-10' : 'size-9',
              !filled && 'bg-secondary text-muted-foreground shadow-none hover:bg-secondary hover:text-foreground')}>
      {pending ? <Spinner /> : <ArrowUp aria-hidden="true" className="size-[18px]" strokeWidth={2.4} />}
    </Button>
  )
  const composer = (
    <form id="composer" onSubmit={(e) => { e.preventDefault(); send() }}>
      {askError && <div className="errbox" role="alert" style={{ marginBottom: 10 }}>{askError}</div>}
      <div className={cn('border border-border bg-card transition-[border-color,box-shadow]',
        'focus-within:border-primary focus-within:ring-3 focus-within:ring-primary/15',
        'flex flex-col rounded-3xl px-5 max-[700px]:px-4',
        start ? 'gap-2 pt-4 pb-3 shadow-lg' : 'gap-1 pt-3 pb-2 shadow-sm')}>
        <Textarea id="q" ref={box} rows={2} maxLength={me.max_question_chars} required aria-label="Your question"
                  className={cn('max-h-[220px] flex-1 rounded-none! border-0! bg-transparent! px-0! shadow-none focus-visible:ring-0',
                    start ? 'min-h-12 py-0! text-[15px]!' : 'min-h-11 py-0!')}
                  value={question} readOnly={pending !== null} onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={onKey}
                  placeholder="Ask about sales, customers, orders, stock or documents…" />
        <div className="flex items-center justify-end">{sendButton}</div>
      </div>
    </form>
  )

  return (
    // no chat list here (12-Nov): "New chat" and "History" (its Chats tab) are in the top bar of the frame
    <div className="ask-layout chats-none ui-scope">
      <section className="conv" aria-label="Conversation">
        <div className="conv-head">
          <div className="min-w-0 flex-1">
            {route.kind === 'question' ? (
              <>
                <div className="conv-title">Saved answer</div>
                <div className="mt-0.5 text-[12.5px] text-muted-foreground [overflow-wrap:anywhere]">
                  {single?.chat && <>From the chat <Link to={chatPath(single.chat.id)}>{single.chat.title}</Link> · </>}
                  the rows come from running the saved SQL again (no AI call).
                </div>
              </>
            ) : chat ? (
              <>
                <div className="conv-title" title={chat.title}>{chat.title}</div>
                <div className="mt-0.5 text-[12.5px] text-muted-foreground">{plural(detail!.total, 'question')} · started {chat.created_text}</div>
              </>
            ) : (
              <>
                <div className="conv-title">New chat</div>
                <div className="mt-0.5 text-[12.5px] text-muted-foreground [overflow-wrap:anywhere]">
                  Your questions and answers are saved - you find this chat again under History.
                </div>
              </>
            )}
          </div>
          {chat && route.kind === 'chat' && (
            <Popover open={menuOpen} onOpenChange={setMenuOpen}>
              <PopoverTrigger asChild>
                <Button type="button" variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-primary"
                        aria-label="Options for this chat" title="Rename, remove or delete">
                  <Ellipsis aria-hidden="true" />
                </Button>
              </PopoverTrigger>
              <PopoverContent portal={false} align="end" side="bottom" className="w-[min(17rem,calc(100vw-2rem))] p-2.5">
                <ChatMenu key={chat.id} chat={listedChat(chat.id) ?? { ...chat, questions: detail?.total }}
                          actions={actions} onDone={() => setMenuOpen(false)} />
              </PopoverContent>
            </Popover>
          )}
        </div>

        <div className="conv-scroll" id="conv-scroll">
          {chat?.archived && (
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2.5 rounded-lg border border-warning/25 bg-warning-soft py-2 pr-3 pl-3.5 text-[12.5px] font-medium text-warning">
              <span>This chat was removed from your list.</span>
              <Button type="button" variant="outline" size="sm"
                      onClick={() => actions.restore(listedChat(chat.id) ?? chat)}>Restore it</Button>
            </div>
          )}
          {loadError && <div className="errbox">{loadError}</div>}

          <div className="thread" id="thread">
            {single && (
              <div className="chat-item" id={`q-${single.card.id}`}>
                <div className="flex flex-col items-end">
                  <Bubble text={single.card.text} />
                  <QuestionTime>{single.card.created_text}</QuestionTime>
                </div>
                <AnswerCard card={single.card} autoRows />
              </div>
            )}
            {detail && route.kind === 'chat' && detail.earlier > 0 && (
              <div className="text-center text-[12.5px] text-muted-foreground">
                {detail.earlier} earlier question{detail.earlier === 1 ? ' of this chat is' : 's of this chat are'} in{' '}
                <Link to="/history">History</Link>.
              </div>
            )}
            {cards.map((card, i) => {
              const last = i === cards.length - 1
              return (
                <div className="chat-item" id={`q-${card.id}`} key={card.id} ref={last ? newest : undefined}>
                  <QuestionBubble card={card} me={me} editable={!pending} onEdit={edit} />
                  <AnswerCard card={withNotice(card)} autoRows={last || card.id === justAsked} />
                </div>
              )
            })}
            {pending && (
              <div className="chat-item" ref={sending}>
                <div className="flex flex-col items-end"><Bubble text={pending} /></div>
                {live?.text ? <LiveAnswer text={live.text} /> : <Thinking steps={live?.steps} />}
              </div>
            )}
            {start && <AskStart examples={me.examples} onPick={fillExample}>{composer}</AskStart>}
          </div>
        </div>

        {!start && (
          <div className="composer">
            {composer}
            {/* one short line; the longer tips sit behind the (i) - on hover, and read out by a screen reader */}
            <div className="mt-2 flex items-center justify-center gap-1.5 text-[11px] leading-normal text-faint">
              <span>Enter to send · Shift+Enter for a new line</span>
              <span className="inline-flex cursor-help" title={TIPS}>
                <Info aria-hidden="true" className="size-3.5" />
                <span className="sr-only">{TIPS}</span>
              </span>
            </div>
          </div>
        )}
        <Toaster position="top-center" duration={6000} />
      </section>

      <AlertDialog open={askingDelete} onOpenChange={setAskingDelete}>
        <AlertDialogContent aria-describedby={undefined}>
          <AlertDialogHeader>
            <AlertDialogTitle>{toDelete && deleteQuestion(toDelete)}</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => { if (toDelete) eraseNow(toDelete) }}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
