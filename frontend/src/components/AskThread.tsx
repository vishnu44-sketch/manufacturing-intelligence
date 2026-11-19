// The parts of a conversation that the Assistant (AskPage) and ML Insights (InsightsPage) share:
// - useAsk: asks a question with the streamed answer (/api/ask/stream; the plain /api/ask when the stream
//   cannot be used) and keeps what is shown while it runs - the question being asked, the steps so far and
//   the answer's text as it grows, or the message when it failed;
// - QuestionBubble / Bubble / QuestionTime: a question on the right (the copy button, the pencil to edit it);
// - PendingQuestion: the question being asked with "Thinking…", the live steps or the growing answer;
// - QuestionBox: the rounded (pill) question box with the round send button inside (Enter sends, Shift+Enter a new line);
// - useModelChoice / ModelPicker (18-Nov, administrators only): the small "which AI model answers" pill in the box.
// The finished answer is AnswerCard (AnswerCard.tsx). Colours are Tailwind token classes only (light and dark theme).
import { type KeyboardEvent, type ReactNode, type RefObject, useEffect, useRef, useState } from 'react'
import { ArrowUp, Check, ChevronDown, Copy, Cpu, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { copyText } from '../lib/clipboard'
import { AuthError, StreamUnavailable, api, problemText } from '../api'
import { Link } from '../router'
import type { AskMode, AskResponse, Card, ChatSummary, Me, ModelOption } from '../types'
import { Button } from './ui/button'
import { Card as Box } from './ui/card'
import { Dots } from './ui/dots'
import { Spinner } from './ui/spinner'
import { Textarea } from './ui/textarea'

/** The card of "Thinking…" and of the streamed steps. */
const WAIT_BOX = 'self-start max-w-full rounded-xl border border-border bg-card px-4 py-3 text-[13px] text-muted-foreground shadow-xs'

/** "Thinking…" under a sent question - or, while the answer streams, the steps so far (the last one is
 *  running); after 20 s and 60 s it says why it takes so long. */
export function Thinking({ text = 'Thinking… writing the SQL and checking it', steps = [] }: { text?: string; steps?: string[] }) {
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
      {/* pre-line: the answer's own line breaks show while it streams (a general answer's lists), as on the finished card */}
      <div className="answer text-[15px] leading-[1.65] whitespace-pre-line text-foreground [overflow-wrap:anywhere]">{text}<span className="caret" aria-hidden="true" /></div>
    </Box>
  )
}

/** What the streamed answer has shown so far: the steps that started, and the answer's text. */
export type Live = { steps: string[]; text: string }

export function scrollTo(el: HTMLElement | null, block: ScrollLogicalPosition) {
  el?.scrollIntoView?.({ block, behavior: 'smooth' }) // (jsdom has no scrollIntoView)
}

/** The grow-with-the-text height of a question box (up to `most` px; past it the box scrolls). */
export function grow(el: HTMLTextAreaElement | null, extra = 0, most = 220) {
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight + extra, most)}px`
}

/** The question box under a conversation: at most 6 rows of 24 px and its 2 x 6 px padding. */
const SMALL_BOX_MOST = 6 * 24 + 12

/** A question bubble (on the right, in the brand colour); keeps the class "bubble". */
export function Bubble({ text }: { text: string }) {
  return (
    <div className={cn('bubble max-w-[min(720px,88%)] rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-sm leading-normal',
      'whitespace-pre-wrap text-primary-foreground shadow-sm [overflow-wrap:anywhere] max-[700px]:max-w-full',
      // 12-Nov: text marked with the mouse was blue on the blue bubble - not to be seen. Marked text here is
      // the other way round: the bubble's text colour as the background, the bubble's colour as the text.
      'selection:bg-primary-foreground selection:text-primary')}>
      {text}
    </div>
  )
}

const HOVER_BUTTON = cn('opacity-0 transition-opacity group-hover/q:opacity-100 hover:bg-card hover:text-primary',
  'focus-visible:opacity-100 [@media(hover:none)]:opacity-100')

/** The copy button of a question: one click copies its whole text; a tick and "Copied" for 2 seconds say it worked. */
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 2000)
    return () => window.clearTimeout(timer)
  }, [copied])
  const copy = async () => {
    if (await copyText(text)) setCopied(true)
    else toast.error('The question could not be copied in this browser.')
  }
  return (
    <Button type="button" variant="ghost" size={copied ? 'sm' : 'icon-sm'} onClick={copy}
            title={copied ? 'Copied' : 'Copy this question'} aria-label={copied ? 'Copied' : 'Copy this question'}
            className={cn(HOVER_BUTTON, copied && 'gap-1 px-2 text-[11.5px] text-success opacity-100 hover:text-success')}>
      {copied ? <><Check aria-hidden="true" className="size-3.5" />Copied</> : <Copy aria-hidden="true" className="size-3.5" />}
    </Button>
  )
}

export function QuestionTime({ children }: { children: ReactNode }) {
  return <div className="mt-1 text-[11px] text-muted-foreground">{children}</div>
}

/** One question of a chat: its bubble (with the pencil when `onEdit` is given and it is editable), or the
 *  edit box while it is edited. */
export function QuestionBubble({ card, me, editable, onEdit }:
  { card: Card; me: Me; editable: boolean; onEdit?: (card: Card, text: string) => Promise<string> }) {
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
    if (sending || !onEdit) return
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
          <div className="flex w-full items-center justify-end gap-1">
            <CopyButton text={card.text} />
            {editable && onEdit && (
              <Button type="button" variant="ghost" size="icon-sm" title="Edit this question" aria-label="Edit this question"
                      className={cn(HOVER_BUTTON, 'mr-1')}
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

/** The question being asked: its bubble, then the live steps ("Thinking…" before the first one) or the
 *  answer growing as it streams. */
export function PendingQuestion({ text, live, itemRef }:
  { text: string; live: Live | null; itemRef?: RefObject<HTMLDivElement | null> }) {
  return (
    <div className="chat-item" ref={itemRef}>
      <div className="flex flex-col items-end"><Bubble text={text} /></div>
      {live?.text ? <LiveAnswer text={live.text} /> : <Thinking steps={live?.steps} />}
    </div>
  )
}

/** The chats of one page, newest first as the list comes: "ml" the ML Insights chats, '' the Assistant's own
 *  (every other). /ask opens the first of the Assistant's, /insights the first of the ML ones. */
export function chatsOf(chats: ChatSummary[], mode: AskMode): ChatSummary[] {
  return chats.filter((chat) => (chat.mode === 'ml') === (mode === 'ml'))
}

// ------------------------------------------------------------------------ the model choice (administrators)

/** Where the administrator's last model choice is kept in this browser. */
const MODEL_KEY = 'askModel'

/** The models list, asked for once per page load and then kept (null = it could not be read: no picker). */
let modelsLoad: Promise<ModelOption[] | null> | null = null

function loadModels(): Promise<ModelOption[] | null> {
  modelsLoad ??= api.models().then((reply) => {
    const list = Array.isArray(reply?.models) ? reply.models.filter((m) => m && typeof m.id === 'string') : []
    if (!list.length) return null
    // "Auto" is always there and first, even if the server's list left it out
    const auto = list.find((m) => m.id === 'auto') ?? { id: 'auto', label: 'Auto (recommended)', available: true }
    return [{ ...auto, available: true }, ...list.filter((m) => m.id !== 'auto')]
  }).catch(() => null)
  return modelsLoad
}

/** Forgets the kept models list (the tests start each test without it). */
export function forgetModels() {
  modelsLoad = null
}

function readModel(): string {
  try {
    return window.localStorage.getItem(MODEL_KEY) || 'auto'
  } catch {
    return 'auto' // no storage in this browser (private window ...): Auto
  }
}

function keepModel(id: string) {
  try {
    if (id === 'auto') window.localStorage.removeItem(MODEL_KEY)
    else window.localStorage.setItem(MODEL_KEY, id)
  } catch {
    // not kept - the choice still works until the page is left
  }
}

/** The model choice of the question box: `models` null = no picker (not an administrator, or the list could not
 *  be read); `model` the id to ask with ("auto" unless an administrator chose an available model). */
export type ModelChoice = { models: ModelOption[] | null; model: string; choose: (id: string) => void }

/** The model choice for an administrator (`staff`); for everyone else no picker, no /api/models call, always Auto. */
export function useModelChoice(staff: boolean): ModelChoice {
  const [models, setModels] = useState<ModelOption[] | null>(null)
  const [chosen, setChosen] = useState(readModel)
  useEffect(() => {
    if (!staff) return
    let live = true
    loadModels().then((list) => { if (live) setModels(list) })
    return () => { live = false }
  }, [staff])
  const shown = staff ? models : null
  // a kept choice that is not in the list now, or not available today, asks with Auto
  const model = shown?.some((m) => m.id === chosen && m.available) ? chosen : 'auto'
  const choose = (id: string) => { setChosen(id); keepModel(id) }
  return { models: shown, model, choose }
}

/** The small model pill in the question box (administrators only): a quiet "Auto" with a chip icon; a model
 *  chosen by hand shows its name in the brand colour, so it is not forgotten. It is a real <select> (keyboard,
 *  screen reader) laid invisibly over the pill; models that cannot be used today are greyed out with the reason. */
function ModelPicker({ choice, big }: { choice: ModelChoice; big: boolean }) {
  const models = choice.models ?? []
  const forced = choice.model !== 'auto'
  const name = forced ? (models.find((m) => m.id === choice.model)?.label ?? choice.model) : 'Auto'
  return (
    <label data-model-picker="" title="Which AI model answers (administrators only)"
           className={cn('relative inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-full px-2.5 text-xs font-medium',
             'transition-colors focus-within:ring-2 focus-within:ring-primary/30',
             forced ? 'bg-primary-soft text-primary' : 'text-muted-foreground hover:bg-secondary hover:text-foreground',
             big ? 'h-10' : 'h-9')}>
      <Cpu aria-hidden="true" className="size-3.5 shrink-0" />
      <span className="max-w-[9rem] truncate max-[700px]:max-w-[5.5rem]">{name}</span>
      <ChevronDown aria-hidden="true" className="size-3 shrink-0 opacity-70" />
      <select aria-label="AI model" value={choice.model} onChange={(e) => choice.choose(e.target.value)}
              className="absolute! inset-0 m-0! h-full! w-full! cursor-pointer appearance-none p-0! opacity-0">
        {models.map((m) => (
          <option key={m.id} value={m.id} disabled={!m.available} title={m.note || undefined}>
            {m.label}{!m.available && m.note ? ` - ${m.note}` : ''}
          </option>
        ))}
      </select>
    </label>
  )
}

// ------------------------------------------------------------------------------------------- asking

/** Asking with the streamed answer. `mode` "ml" asks as an ML Insights chat (it matters for a new chat only:
 *  the server keeps an existing chat's own mode). `staff`: an administrator, who can choose the model
 *  (`choice`, for the QuestionBox; it goes with every question asked here). run() shows the question as
 *  pending until the answer (or the problem) is there; askLive() is the call that streams. */
export function useAsk(mode?: AskMode, staff = false) {
  const choice = useModelChoice(staff)
  const [pending, setPending] = useState<string | null>(null)
  const [live, setLive] = useState<Live | null>(null) // the streamed progress of the pending question
  const [error, setError] = useState('')

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
        } else if (event.type === 'reset') {
          // the app's answer check sends the answer back once: the first text goes, the steps show the rewrite
          setLive((old) => old && { ...old, text: '' })
        }
      }, mode, choice.model)
    } catch (failure) {
      if (!(failure instanceof StreamUnavailable)) throw failure
      setLive(null) // "Thinking…" while the plain call runs
      return api.ask(text, target, mode, choice.model)
    }
  }

  /** Runs one question: `onReply` gets the answer (in the same update as the end of "pending", so the
   *  page never shows a moment without both); `onFail` runs when it failed (not for a sign-in problem:
   *  the app then shows the Login page). */
  async function run(text: string, call: () => Promise<AskResponse>, onReply: (reply: AskResponse) => void, onFail?: () => void) {
    setPending(text)
    setError('')
    toast.dismiss()
    try {
      onReply(await call())
    } catch (failure) {
      if (failure instanceof AuthError) return
      setError(problemText(failure, 'The question could not be asked.'))
      onFail?.()
    } finally {
      setPending(null)
      setLive(null)
    }
  }

  return { pending, live, error, setError, run, askLive, choice }
}

/** The question box, like ChatGPT's (17-Nov): one rounded pill (a rounded box once it grows to more lines)
 *  with a thin line and a soft shadow, the text on one row in it (no border of its own; it grows with the
 *  text up to 6 rows, on the start screen up to 220 px, then it scrolls) and the round send button inside
 *  at the right - grey and off while the box is empty, in the brand colour with a white arrow when there is
 *  text, the spinner while the answer comes (there is no "stop" for a running question). The text and the
 *  button are lined up at the bottom: centred on one row, the button stays at the bottom when the box grows.
 *  Focus: a soft glow in the brand colour around the pill. `big` (the Assistant's start screen): the same
 *  pill a little bigger. `choice` (from useAsk): for an administrator the small model pill sits just left of
 *  the send button; nothing for everyone else. */
export function QuestionBox({ boxRef, value, onChange, onSend, pending, big = false, maxLength, error = '',
  formId = 'composer', boxId = 'q', label = 'Your question', placeholder, choice }:
  { boxRef: RefObject<HTMLTextAreaElement | null>; value: string; onChange: (text: string) => void; onSend: () => void
    pending: boolean; big?: boolean; maxLength: number; error?: string; formId?: string; boxId?: string; label?: string
    placeholder: string; choice?: ModelChoice }) {
  const filled = value.trim() !== ''
  // the box grows with the text: big up to 220 px, small up to 6 rows
  useEffect(() => { grow(boxRef.current, 0, big ? 220 : SMALL_BOX_MOST) }, [value, big, boxRef])

  function onKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      onSend()
    }
  }

  return (
    <form id={formId} onSubmit={(e) => { e.preventDefault(); onSend() }}>
      {error && <div className="errbox" role="alert" style={{ marginBottom: 10 }}>{error}</div>}
      <div data-question-box=""
           className={cn('flex items-end gap-2 rounded-[28px] border border-border bg-card',
             'transition-[border-color,box-shadow] duration-150',
             // the soft glow on focus (a box-shadow ring) - also shows when the box is reached with the keyboard
             'focus-within:border-primary/60 focus-within:ring-4 focus-within:ring-primary/15',
             big ? 'py-2 pr-2 pl-6 shadow-xl shadow-shadow/10 max-[700px]:pl-5'
               : 'py-2 pr-2 pl-5 shadow-lg shadow-shadow/[0.07] max-[700px]:pl-4')}>
        <Textarea id={boxId} ref={boxRef} rows={1} maxLength={maxLength} required aria-label={label}
                  className={cn('min-w-0 flex-1 rounded-none! border-0! bg-transparent! px-0! shadow-none!',
                    // a long placeholder stays on one row (cut with "…" on a phone), so the empty box is one row high
                    'focus-visible:ring-0 placeholder:truncate placeholder:text-muted-foreground/80',
                    big ? 'max-h-[220px]! min-h-10! py-2! text-[15px]!' : 'max-h-[156px]! min-h-9! py-1.5!')}
                  value={value} readOnly={pending} onChange={(e) => onChange(e.target.value)}
                  onKeyDown={onKey} placeholder={placeholder} />
        {choice?.models && <ModelPicker choice={choice} big={big} />}
        <Button type="submit" size="icon" aria-label="Ask" title="Ask (Enter)" disabled={pending || !filled}
                className={cn('shrink-0 rounded-full', big ? 'size-10' : 'size-9',
                  // empty (or waiting for the answer): grey and off; with text: the brand colour (the Button's own)
                  !filled && 'bg-secondary text-muted-foreground shadow-none disabled:opacity-100')}>
          {pending ? <Spinner className="size-4" /> : <ArrowUp aria-hidden="true" className="size-[18px]" strokeWidth={2.4} />}
        </Button>
      </div>
    </form>
  )
}
