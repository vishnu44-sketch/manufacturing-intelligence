// The Ask page: the chat list on the left, the open chat on the right (question bubbles and answer
// cards) and the question box at the bottom. Three views on the right:
// - a chat (/c/<id>): its questions oldest first; the newest answer loads its rows at once; each
//   question has a pencil to edit it (its new answer takes the old one's place);
// - one saved answer (/q/<id>): the card with its rows; asking there continues its chat;
// - the start screen (/new, or /ask without chats): a big heading, the question box in the middle of the
//   page and four starter cards (AskStart.tsx). After the first question the box sits at the bottom.
// Asking streams the answer (/api/ask/stream): the steps show as they run ("Search the SQL notes (vector DB Qdrant: mi_docs) …"),
// then the answer grows word by word, and the finished card takes its place. When the stream cannot be
// used (nothing comes back, e.g. a proxy), it asks the plain way (/api/ask) and shows "Thinking…".
// History's "Ask again" lands here (/new with the question in the navigation state) and asks at once.
// 16-Nov ("I can't read my chat properly"): the conversation gets the room - no title row above it (the browser
// tab shows the chat's title), the chat's "..." menu floats at its top right, the thread and the question box
// sit in a centred column (at most 920 px wide) and the box under a conversation is one row that grows with the text.
// Drawn with Tailwind + shadcn/ui (src/components/ui); the page's root has the class "ui-scope" (see
// src/tailwind.css). The grid / scrolling / phone-drawer layout still comes from app.css (ask-layout,
// chats, conv, conv-scroll, composer ...). Messages (a chat removed or deleted, a failed chat action) show
// as toasts; deleting a chat asks in a dialog first. Colours are Tailwind token classes only (no fixed
// colours), so the page follows the light and the dark theme.
// 17-Nov: the conversation parts (bubbles, live steps, streamed answer, question box) and the asking itself
// (useAsk) moved to AskThread.tsx - ML Insights uses them too. The ML Insights chats (mode "ml") open on
// that page: /ask skips them, and a /c/<id> of one goes on to /insights?chat=<id>.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Ellipsis, Info } from 'lucide-react'
import { toast } from 'sonner'
import { copyText } from '../lib/clipboard'

export { copyText }
import { cn } from '@/lib/utils'
import { AuthError, api, problemText } from '../api'
import { ASK_PATH, Link, chatPath, insightsPath, openChatPath, useRouter } from '../router'
import type { AskResponse, Card, ChatDetail, ChatSummary, Me, SavedAnswer } from '../types'
import AnswerCard from './AnswerCard'
import AskStart from './AskStart'
import { Bubble, PendingQuestion, QuestionBox, QuestionBubble, QuestionTime, chatsOf, scrollTo, useAsk } from './AskThread'
import { type ChatActions, ChatMenu, deleteQuestion } from './ChatMenu'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from './ui/alert-dialog'
import { Button } from './ui/button'
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover'
import { Toaster } from './ui/sonner'
import { tabTitle } from '../lib/brand'

/** What History's "Ask again" passes along when it opens this page. */
export interface AskAgain {
  again: { id: number; text: string }
}

function isAskAgain(state: unknown): state is AskAgain {
  const again = (state as AskAgain | null)?.again
  return !!again && typeof again.id === 'number' && typeof again.text === 'string'
}

// the tips behind the (i) under the question box
const TIPS = 'Follow-up questions work ("and for Sep?", "same for export") - the AI sees the last 3 questions of '
  + 'this chat. A month name means the sales month (21st to 20th) unless you say "calendar month".'

export default function AskPage({ me }: { me: Me }) {
  const { route, state, navigate } = useRouter()
  const [chats, setChats] = useState<ChatSummary[] | null>(null)
  const [removed, setRemoved] = useState<ChatSummary[]>([])
  const [detail, setDetail] = useState<ChatDetail | null>(null)
  const [single, setSingle] = useState<SavedAnswer | null>(null)
  const [loadError, setLoadError] = useState('')
  // the question being asked, its streamed progress and the message when it failed (AskThread.tsx)
  const { pending, live, error: askError, run: runAsk, askLive, choice } = useAsk('', me.is_staff)
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

  // the Assistant's own chats: the ML Insights chats (mode "ml") open on that page instead
  const ownChats = useMemo(() => chats && chatsOf(chats, ''), [chats])
  // /ask opens the most recently used chat (or the new-chat screen when there is none)
  useEffect(() => {
    if (route.kind === 'latest' && ownChats && ownChats.length) navigate(chatPath(ownChats[0].id), { replace: true })
  }, [route, ownChats, navigate])

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
      .then((data) => {
        if (gone) return
        // an ML Insights chat opens on its own page (with the ML results under it)
        if (data.chat.mode === 'ml') navigate(insightsPath(data.chat.id), { replace: true })
        else setDetail(data)
      })
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

  function run(text: string, call: () => Promise<AskResponse>, startedIn: number | null, keep: string) {
    // a failed question keeps what was typed in the box (a sign-in problem shows the Login page instead)
    return runAsk(text, call, (reply) => showAnswer(reply, startedIn), () => setQuestion(keep))
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

  function fillExample(text: string) {
    setQuestion(text)
    box.current?.focus()
  }

  const chat = route.kind === 'chat' ? detail?.chat ?? null : null
  const showWelcome = !chat && !single && !loadError && route.kind !== 'question' && route.kind !== 'chat'
    && (route.kind === 'new' || (route.kind === 'latest' && ownChats !== null && ownChats.length === 0))
  // the start screen: a new / empty chat with nothing being asked - the question box is in the middle of the page
  const start = showWelcome && !pending
  const cards = route.kind === 'chat' ? detail?.cards ?? [] : []
  const withNotice = (card: Card) => (notices[card.id] ? { ...card, token_notice: notices[card.id] } : card)
  const listedChat = (id: number) => [...(chats ?? []), ...removed].find((c) => c.id === id)
  // the first question moves the box from the middle of the page to the bottom: the cursor stays in it
  useEffect(() => { if (!start && pending) box.current?.focus() }, [start]) // eslint-disable-line react-hooks/exhaustive-deps

  // the browser tab shows the open chat's title ("<chat title> · SS Manufacturing"); the frame's
  // "Assistant · SS Manufacturing" comes back when the chat is closed
  const chatTitle = chat?.title ?? ''
  useEffect(() => {
    if (!chatTitle) return
    const before = document.title
    document.title = tabTitle(chatTitle)
    return () => { document.title = before }
  }, [chatTitle])

  // The column of the thread and of the question box: centred, at most 920 px wide; with the chat's "..."
  // button 44 px stay free on each side for it (on a phone the button has a small row of its own: full width).
  const column = cn('conv-col mx-auto flex w-full flex-col',
    chat ? 'max-w-[min(920px,calc(100%_-_88px))] max-[700px]:max-w-full' : 'max-w-[920px]')

  // The question box (AskThread.tsx): on the start screen big, in the middle of the page; under a conversation
  // (16-Nov) one row that grows with the text, the send button inside at the right.
  const composer = (
    <QuestionBox boxRef={box} value={question} onChange={setQuestion} onSend={send} pending={pending !== null} big={start}
                 maxLength={me.max_question_chars} error={askError} choice={choice}
                 placeholder="Ask about sales, customers, orders, stock or documents…" />
  )

  return (
    // no chat list here (12-Nov): "New chat" and "History" (its Chats tab) are in the top bar of the frame
    <div className="ask-layout chats-none ui-scope">
      <section className="conv" aria-label="Conversation">
        <div className={cn('conv-scroll', chat && 'has-menu')} id="conv-scroll">
          {/* 16-Nov: no head row - the chat's "..." menu (rename / remove / delete) floats at the top right and
              stays there while the conversation scrolls (app.css, .conv-menu) */}
          {chat && (
            <div className="conv-menu">
              <Popover open={menuOpen} onOpenChange={setMenuOpen}>
                <PopoverTrigger asChild>
                  <Button type="button" variant="ghost" size="icon-sm"
                          className="rounded-full bg-background/80 text-muted-foreground backdrop-blur-sm hover:text-primary"
                          aria-label="Options for this chat" title="Rename, remove or delete">
                    <Ellipsis aria-hidden="true" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent portal={false} align="end" side="bottom" className="w-[min(17rem,calc(100vw-2rem))] p-2.5">
                  <ChatMenu key={chat.id} chat={listedChat(chat.id) ?? { ...chat, questions: detail?.total }}
                            actions={actions} onDone={() => setMenuOpen(false)} />
                </PopoverContent>
              </Popover>
            </div>
          )}

          <div className={cn(column, 'flex-1')}>
            {/* a slim line at the top instead of the old head: a removed chat, or where a saved answer comes from */}
            {chat?.archived && (
              <div className="mb-4 flex flex-wrap items-center gap-x-2 gap-y-0.5 self-start rounded-lg bg-warning-soft px-3 py-1.5 text-[12.5px] font-medium text-warning">
                <span>This chat was removed from your list.</span>
                <Button type="button" variant="link" size="xs" className="h-auto p-0 text-[12.5px] font-semibold text-warning underline"
                        onClick={() => actions.restore(listedChat(chat.id) ?? chat)}>Restore it</Button>
              </div>
            )}
            {route.kind === 'question' && (
              <div className="saved-note mb-4 text-[12.5px] text-muted-foreground [overflow-wrap:anywhere]">
                <span className="font-semibold text-heading">Saved answer</span>
                {' · '}
                {single?.chat && <>From the chat <Link to={openChatPath(single.chat)}>{single.chat.title}</Link> · </>}
                the rows come from running the saved SQL again (no AI call).
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
                  <AnswerCard card={single.card} autoRows staff={me.is_staff} />
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
                    <AnswerCard card={withNotice(card)} autoRows={last || card.id === justAsked} staff={me.is_staff} />
                  </div>
                )
              })}
              {pending && <PendingQuestion text={pending} live={live} itemRef={sending} />}
              {start && <AskStart examples={me.examples} onPick={fillExample}>{composer}</AskStart>}
            </div>
          </div>
        </div>

        {!start && (
          <div className={cn('composer', column)}>
            {composer}
            {/* one short line, small and light; the longer tips sit behind the (i) - on hover, and read out by a screen reader */}
            <div className="mt-1.5 flex items-center justify-center gap-1.5 text-[10.5px] leading-normal text-faint">
              <span>Enter to send · Shift+Enter for a new line</span>
              <span className="inline-flex cursor-help" title={TIPS}>
                <Info aria-hidden="true" className="size-3" />
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
