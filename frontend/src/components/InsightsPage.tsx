// ML Insights (/insights, every user): the page's own question box "Ask about forecasts and insights…" with 6 ready
// questions to click (17-Nov). Asking there starts an ML chat (mode "ml") and shows the conversation right there - the
// same live steps, streamed answer and answer cards as the Assistant (AskThread.tsx, AnswerCard.tsx); follow-ups
// continue the same chat. The chat's address is /insights?chat=<id> (History opens ML chats here); /insights alone
// reopens the latest ML chat (18-Nov), and the top bar's "New chat" on this page starts a new one (/insights?new=1).
// 18-Nov: the 6 ML result cards moved to their own page, the ML Dashboard (/ml-dashboard, MlDashboard.tsx); a small
// link at the top opens it. A card's "Ask about this" there comes back here as /insights?new=1&ask=<question>: the
// question is asked once in a new ML chat, and the address then names that chat (a refresh does not ask again).
import { ArrowRight, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { AuthError, api, problemText } from '../api'
import { Link, ML_DASHBOARD_PATH, NEW_ML_CHAT_PATH, insightsPath, useRouter } from '../router'
import type { Card as AnswerData, ChatDetail, Me } from '../types'
import AnswerCard from './AnswerCard'
import { PendingQuestion, QuestionBox, QuestionBubble, chatsOf, scrollTo, useAsk } from './AskThread'
import { ASK } from './MlDashboard'
import { Toaster } from './ui/sonner'

const NOTE = 'text-xs leading-relaxed text-muted-foreground'

// ------------------------------------------------------------------------------------------------ the ML chat

/** The ready questions under the box: the questions of the 6 cards. */
const READY = [ASK.forecast, ASK.risk, ASK.segments, ASK.alerts, ASK.pairs, ASK.stock]

/** The page's own conversation: the open ML chat (the address's ?chat=<id>) and the question being asked.
 *  18-Nov: /insights alone (e.g. the menu link) opens the latest ML chat again, as /ask opens the latest Assistant
 *  chat; the top bar's "New chat" on this page goes to /insights?new=1 - an empty ML chat that stays empty. */
function useMlChat(me: Me) {
  const { route, navigate } = useRouter()
  const chatId = route.kind === 'insights' ? route.chat : null
  const [detail, setDetail] = useState<ChatDetail | null>(null)
  const [loadError, setLoadError] = useState('')
  const [question, setQuestion] = useState('')
  const [justAsked, setJustAsked] = useState<number | null>(null)
  const [notices, setNotices] = useState<Record<number, string>>({}) // one-time token notices, by card id
  const asking = useAsk('ml', me.is_staff)
  const box = useRef<HTMLTextAreaElement>(null)
  const asked = useRef(0) // questions asked on this page: a chat list that comes later must not open another chat
  const openChat = useRef(chatId) // the chat of the address now (an answer can come after "New chat")
  useEffect(() => { openChat.current = chatId }, [chatId])

  // /insights alone: the latest ML chat again, the address names it (no extra Back step); no ML chat yet: the empty box
  useEffect(() => {
    if (route.kind !== 'insights' || route.chat !== null || route.fresh) return
    let gone = false
    const before = asked.current
    api.chats()
      .then((list) => {
        const latest = chatsOf(list.chats, 'ml')[0]
        if (!gone && latest && asked.current === before) navigate(insightsPath(latest.id), { replace: true })
      })
      .catch(() => {}) // the list can't be read: the empty box, as with no ML chat
    return () => { gone = true }
  }, [route, navigate])

  // the top bar's "New chat" here (/insights?new=1): an empty conversation and box; the old chat stays in History
  useEffect(() => {
    if (route.kind !== 'insights' || !route.fresh) return
    setDetail(null)
    setQuestion('')
    setLoadError('')
    asking.setError('')
    box.current?.focus()
  }, [route]) // eslint-disable-line react-hooks/exhaustive-deps

  // a card's "Ask about this" on the ML Dashboard (/insights?new=1&ask=<question>): ask it once, in a new ML chat.
  // The address drops ?ask= at once (a refresh while it runs does not ask again), then names the new chat.
  const askedFromAddress = useRef<unknown>(null) // the address already asked (React runs effects twice in dev)
  useEffect(() => {
    if (route.kind !== 'insights' || !route.ask || askedFromAddress.current === route) return
    askedFromAddress.current = route
    navigate(NEW_ML_CHAT_PATH, { replace: true })
    ask(route.ask, true)
  }, [route]) // eslint-disable-line react-hooks/exhaustive-deps

  // open the chat of the address: its saved cards (no AI call); a chat just made by asking is already here
  useEffect(() => {
    if (chatId === null) {
      setDetail(null)
      setLoadError('')
      return
    }
    if (detail?.chat.id === chatId) return
    let gone = false
    setLoadError('')
    api.chat(chatId)
      .then((reply) => { if (!gone) setDetail(reply) })
      .catch((err) => {
        if (gone || err instanceof AuthError) return
        setDetail(null)
        setLoadError(err.status === 404 ? 'This chat was not found.' : problemText(err))
      })
    return () => { gone = true }
  }, [chatId]) // eslint-disable-line react-hooks/exhaustive-deps

  /** Asks in the open ML chat (or starts one; always a new one with `fresh`); a failed question goes back into the box. */
  function ask(typed: string, fresh = false) {
    const text = typed.trim().slice(0, me.max_question_chars)
    if (!text || asking.pending) {
      box.current?.focus()
      return
    }
    const target = fresh ? null : detail?.chat.id ?? null
    asked.current += 1
    setQuestion('')
    asking.run(text, () => asking.askLive(text, target), (reply) => {
      setNotices((old) => ({ ...old, [reply.card.id]: reply.card.token_notice }))
      setJustAsked(reply.card.id)
      // the chat on screen gets the answer; a new chat is just this answer; an older chat left by "New chat"
      // meanwhile is loaded again whole when the address names it below
      setDetail((old) => (old && old.chat.id === reply.chat.id
        ? { ...old, chat: reply.chat, total: old.total + 1, cards: [...old.cards, reply.card] }
        : target === null ? { chat: reply.chat, total: 1, earlier: 0, cards: [reply.card] } : null))
      // the address names the chat (a refresh opens it again); a new chat takes the place of the empty page
      const here = openChat.current
      if (here !== reply.chat.id) navigate(insightsPath(reply.chat.id), { replace: here === null })
    }, () => setQuestion(text))
  }

  return { detail, loadError, question, setQuestion, justAsked, notices, asking, box, ask }
}

/** The question box at the top of the page, its conversation and the ready questions. */
function MlChat({ me, chat }: { me: Me; chat: ReturnType<typeof useMlChat> }) {
  const { detail, loadError, question, setQuestion, justAsked, notices, asking, box, ask } = chat
  const newest = useRef<HTMLDivElement>(null)
  const sending = useRef<HTMLDivElement>(null)
  const cards = detail?.cards ?? []
  const withNotice = (card: AnswerData) => (notices[card.id] ? { ...card, token_notice: notices[card.id] } : card)
  const busy = asking.pending !== null

  // show the newest answer, or the question being asked (also one asked from a card of the ML Dashboard)
  useEffect(() => { if (detail) scrollTo(newest.current, 'start') }, [detail?.chat.id, cards.length]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (asking.pending) scrollTo(sending.current, 'start') }, [asking.pending])

  return (
    <section aria-label="Ask about forecasts and insights" className="flex min-w-0 flex-col gap-3" data-ml-chat="">
      {/* 18-Nov: no "New ML chat" button here - the top bar's "New chat" starts a new ML chat on this page */}
      <div className="flex min-w-0 items-start gap-2.5">
        <span aria-hidden="true" className="flex size-8 flex-none items-center justify-center rounded-full bg-primary-soft text-primary">
          <Sparkles className="size-4" />
        </span>
        <div className="min-w-0">
          <h2 className="m-0 text-[15px] leading-snug font-semibold text-heading">Ask about forecasts and insights</h2>
          <div className={NOTE}>The AI answers from the latest ML results and the sales data. Follow-up questions continue the same chat.</div>
        </div>
      </div>

      {loadError && <div className="errbox">{loadError}</div>}
      {(cards.length > 0 || busy) && (
        <div className="thread" aria-label="ML chat">
          {detail && detail.earlier > 0 && (
            <div className="text-center text-[12.5px] text-muted-foreground">
              {detail.earlier} earlier question{detail.earlier === 1 ? ' of this chat is' : 's of this chat are'} in History.
            </div>
          )}
          {cards.map((card, i) => {
            const last = i === cards.length - 1
            return (
              <div className="chat-item" key={card.id} ref={last ? newest : undefined}>
                <QuestionBubble card={card} me={me} editable={false} />
                <AnswerCard card={withNotice(card)} autoRows={last || card.id === justAsked} staff={me.is_staff} />
              </div>
            )
          })}
          {asking.pending && <PendingQuestion text={asking.pending} live={asking.live} itemRef={sending} />}
        </div>
      )}

      <QuestionBox boxRef={box} value={question} onChange={setQuestion} onSend={() => ask(question)} pending={busy}
                   maxLength={me.max_question_chars} error={asking.error} formId="ml-composer" boxId="ml-q" choice={asking.choice}
                   label="Your question about forecasts and insights" placeholder="Ask about forecasts and insights…" />
      <ul aria-label="Ready questions" className="flex flex-wrap gap-2">
        {READY.map((text) => (
          <li key={text}>
            <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => ask(text)}
                    className="h-auto rounded-full px-3 py-1.5 text-[12.5px] font-medium whitespace-normal text-heading hover:border-primary/50 hover:text-primary">
              {text}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  )
}

// ------------------------------------------------------------------------------------------------ the page

export default function InsightsPage({ me }: { me: Me }) {
  const chat = useMlChat(me)
  return (
    <div className="ui-scope flex min-w-0 flex-col gap-4">
      {/* the ML results are on their own page now */}
      <Link to={ML_DASHBOARD_PATH} data-dashboard-link=""
        className="group inline-flex items-center gap-1 self-end rounded-md text-[13px] font-medium text-primary outline-none hover:text-primary-hover focus-visible:ring-3 focus-visible:ring-ring/40">
        Open ML Dashboard
        <ArrowRight aria-hidden="true" className="size-3.5 transition-transform group-hover:translate-x-0.5" />
      </Link>
      <MlChat me={me} chat={chat} />
      <Toaster position="top-center" duration={6000} />
    </div>
  )
}
