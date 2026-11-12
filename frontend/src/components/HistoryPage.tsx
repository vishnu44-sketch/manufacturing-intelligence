// History: two tabs. "Chats" (the first one shown): the user's chats, to open, rename, remove or delete
// (HistoryChats). "Questions" (?tab=questions, or a ?page=): the AI usage box of this app (all users), then
// the user's own questions, newest first, 25 per page (?page=2), with their answer, rows, seconds, tokens and status. "Ask again" asks the
// question again in a new chat (the Ask page shows "Thinking…"); "Excel" downloads its rows.
import { useEffect, useState } from 'react'
import { AuthError, api, problemText } from '../api'
import { Link, questionPath, useRouter } from '../router'
import type { HistoryLine, HistoryPage as Page, Status, Usage } from '../types'
import type { AskAgain } from './AskPage'
import { ExcelLink, Loading, plural } from './common'
import HistoryChats from './HistoryChats'
import { Segmented, SegmentedItem } from './ui/segmented'

const CHIPS: Record<Status, [string, string]> = {
  ok: ['ok', 'ANSWERED'],
  docs: ['doc', 'FROM DOCUMENTS'],
  nodata: ['info', 'NO DATA'],
  refused: ['skip', 'REFUSED'],
  error: ['fail', 'FAILED'],
  memory: ['ok', 'MEMORY UPDATED'],
}

/** The AI usage of this app: the daily period, Groq's rolling 24 h count and this week. */
export function UsageBox({ usage }: { usage: Usage }) {
  const join = (parts: string[]) => parts.join(' - ')
  return (
    <div className="card usage-card">
      <div className="h2">AI usage (this app)</div>
      <div className="usage-sub">
        {usage.period_start
          ? `Daily period since ${usage.period_start} - it resets 24 hours after its first question.`
          : 'Daily period: starts with your next question.'}
      </div>
      <div className="usage-lines">
        {usage.rows.map((row) => (
          <div className="usage-line" key={row.model}>
            <span className="usage-model">{row.model}</span>
            <span className="usage-num">{row.tokens} of {row.limit} tokens ({row.pct} %)</span>
            <span className="usage-bar">
              <span className={`usage-fill${row.pct >= 70 ? ' high' : ''}`} style={{ width: `${Math.min(row.pct, 100)}%` }} />
            </span>
            <span className="usage-left">
              about {plural(row.questions_left, 'question')} left{usage.period_end && ` - resets ${usage.period_end}`}
            </span>
          </div>
        ))}
      </div>
      <div className="usage-extra mut">
        Groq's real count (rolling last 24 h, this app): {join(usage.rows.map((row) => `${row.model} ${row.rolling}`))}
      </div>
      <div className="usage-extra">
        This week (since {usage.week_start}):{' '}
        {join(usage.rows.map((row) => `${row.model} ${row.week_tokens} tokens, ${plural(row.week_questions, 'question')}`))}
        {' '}- resets {usage.week_end}
      </div>
      <div className="mut">
        Counted from the questions of all users of this app. Tests and other tools that use the same Groq key are not
        included, so Groq's own count can be higher.
      </div>
    </div>
  )
}

function Line({ line }: { line: HistoryLine }) {
  const { navigate } = useRouter()
  const [chipClass, chipText] = CHIPS[line.status] ?? CHIPS.error
  const again: AskAgain = { again: { id: line.id, text: line.ask_again } }
  return (
    <tr>
      <td style={{ whiteSpace: 'nowrap' }}>{line.created_text}</td>
      <td style={{ color: '#212529', fontWeight: 500 }}>
        <Link to={questionPath(line.id)} className="history-q" title="Open this answer">{line.text}</Link>
        {line.understood_as && <div className="mut">Understood as: {line.understood_as}</div>}
        {line.edited && <div className="mut">edited - replaced by a newer version</div>}
      </td>
      <td>{line.answer || '-'}</td>
      <td className="num">{line.rows_count ?? '-'}</td>
      <td className="num">{line.secs_text}</td>
      <td className="num">{line.tokens_text}</td>
      <td>
        <span className={`chip ${chipClass}`}>{chipText}</span>
        {line.backup && <div className="mut" title={line.model}>backup model</div>}
      </td>
      <td>
        <div className="actions">
          <button type="button" className="btn secondary small" onClick={() => navigate('/new', { state: again })}>
            Ask again
          </button>
          {line.excel_url && <ExcelLink url={line.excel_url}>Excel</ExcelLink>}
        </div>
      </td>
    </tr>
  )
}

type Tab = 'chats' | 'questions'

/** The tab History opens with: Questions for ?tab=questions or a ?page= (its pager), else Chats. */
function firstTab(): Tab {
  const params = new URLSearchParams(window.location.search)
  return params.get('tab') === 'questions' || params.has('page') ? 'questions' : 'chats'
}

export default function HistoryPage({ page }: { page: number }) {
  const [tab, setTab] = useState<Tab>(firstTab)
  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <Segmented aria-label="What History shows">
          <SegmentedItem pressed={tab === 'chats'} onClick={() => setTab('chats')}>Chats</SegmentedItem>
          <SegmentedItem pressed={tab === 'questions'} onClick={() => setTab('questions')}>Questions</SegmentedItem>
        </Segmented>
      </div>
      {tab === 'chats' ? <HistoryChats /> : <Questions page={page} />}
    </>
  )
}

/** The "Questions" tab: the AI usage box, then the user's own questions (one page of them). */
function Questions({ page }: { page: number }) {
  const [data, setData] = useState<Page | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let gone = false
    setError('')
    api.history(page)
      .then((body) => { if (!gone) setData(body) })
      .catch((err) => { if (!gone && !(err instanceof AuthError)) setError(problemText(err)) })
    return () => { gone = true }
  }, [page])

  if (error) return <div className="errbox">{error}</div>
  if (!data) return <Loading />
  return (
    <>
      <UsageBox usage={data.usage} />
      <div className="mut">Your own questions, newest first.</div>
      {data.questions.length ? (
        <>
          <div className="twrap scroll">
            <table className="t">
              <thead>
                <tr>
                  <th>Asked on</th><th>Question</th><th>Answer</th><th className="num">Rows</th>
                  <th className="num">Seconds</th><th className="num">Tokens</th><th>Status</th><th />
                </tr>
              </thead>
              <tbody>
                {data.questions.map((line) => <Line key={line.id} line={line} />)}
              </tbody>
            </table>
          </div>
          {data.pages > 1 && (
            <div className="pager">
              {data.has_previous && <Link className="btn secondary small" to={`/history?page=${data.page - 1}`}>← Newer</Link>}
              <span className="mut">Page {data.page} of {data.pages} · {plural(data.count, 'question')}</span>
              {data.has_next && <Link className="btn secondary small" to={`/history?page=${data.page + 1}`}>Older →</Link>}
            </div>
          )}
        </>
      ) : (
        <div className="card">
          <div className="h2">No questions yet</div>
          <div className="mut" style={{ marginBottom: 14 }}>You have not asked anything yet. Your questions will show up here.</div>
          <Link className="btn primary" to="/ask">Go to the Assistant</Link>
        </div>
      )}
    </>
  )
}
