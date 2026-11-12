// Audit log (staff): who did what and when - sign-ins, people, chats, memories, Excel downloads and MCP
// calls - newest first, 50 per page. The filters (user, action, dates, a word) live in the address
// (/audit?user=..&action=..&from=..&to=..&q=..&page=2), so Back works. A click on a line shows all its
// details and links to the questions it is about (staff open them, also those of a deleted chat).
// Read-only: the page (and the API) can never change or delete a line.
import { type FormEvent, Fragment, useEffect, useState } from 'react'
import { ApiError, AuthError, api, query } from '../api'
import { Link, questionPath, useRouter } from '../router'
import type { AuditData, AuditFilters, AuditLine } from '../types'
import { Loading, NoAccess, plural } from './common'

type Props = AuditFilters & { page: number }

/** The chip colour of an action: red for a failed sign-in or a deletion, amber for rights and switching
 *  off, blue for MCP, green for the rest. */
function chipClass(action: string): string {
  if (action === 'login_failed' || action.includes('delete')) return 'fail'
  if (['user_roles_changed', 'user_deactivated', 'password_reset'].includes(action)) return 'skip'
  if (action.startsWith('mcp_')) return 'info'
  return 'ok'
}

function who(line: AuditLine): string {
  return line.username || (line.action.startsWith('mcp_') ? 'MCP caller' : '-')
}

function Details({ line }: { line: AuditLine }) {
  return (
    <div className="audit-details">
      {line.questions.length > 0 && (
        <div className="audit-questions">
          Questions:{' '}
          {line.questions.map((id) => (
            <Link key={id} className="ex" to={questionPath(id)} title="Open this saved answer">#{id}</Link>
          ))}
        </div>
      )}
      <pre className="doc-text">{JSON.stringify(line.details, null, 2)}</pre>
      <div className="mut">Browser: {line.user_agent || '-'}</div>
    </div>
  )
}

function Line({ line, open, onToggle }: { line: AuditLine; open: boolean; onToggle: () => void }) {
  return (
    <Fragment>
      <tr className={`audit-line${open ? ' open' : ''}`} tabIndex={0} aria-expanded={open} onClick={onToggle}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle() } }}>
        <td style={{ whiteSpace: 'nowrap' }}>{line.created_text}</td>
        <td>{who(line)}</td>
        <td><span className={`chip ${chipClass(line.action)}`}>{line.action_text}</span></td>
        <td style={{ whiteSpace: 'nowrap' }}>{line.target || '-'}</td>
        <td className="audit-summary">{line.summary || '-'}</td>
        <td style={{ whiteSpace: 'nowrap' }}>{line.ip || '-'}</td>
      </tr>
      {open && (
        <tr className="audit-open">
          <td colSpan={6}><Details line={line} /></td>
        </tr>
      )}
    </Fragment>
  )
}

export default function AuditPage({ page, user, action, from, to, q }: Props) {
  const { navigate } = useRouter()
  const [data, setData] = useState<AuditData | null>(null)
  const [error, setError] = useState('')
  const [forbidden, setForbidden] = useState(false)
  const [form, setForm] = useState<AuditFilters>({ user, action, from, to, q })
  const [opened, setOpened] = useState<number | null>(null)

  useEffect(() => { setForm({ user, action, from, to, q }) }, [user, action, from, to, q])

  useEffect(() => {
    let gone = false
    setError('')
    setOpened(null)
    api.audit({ page: page > 1 ? page : undefined, user, action, from, to, q })
      .then((body) => { if (!gone) setData(body) })
      .catch((err) => {
        if (gone || err instanceof AuthError) return
        if (err instanceof ApiError && err.status === 403) setForbidden(true)
        else setError(err instanceof ApiError ? err.message : 'The audit log could not be loaded.')
      })
    return () => { gone = true }
  }, [page, user, action, from, to, q])

  const filters = { user, action, from, to, q }
  const pathFor = (n: number) => `/audit${query({ ...filters, page: n > 1 ? n : undefined })}`

  function filter(event: FormEvent) {
    event.preventDefault()
    navigate(`/audit${query({ ...form, user: form.user.trim(), q: form.q.trim() })}`)
  }

  const set = (name: keyof AuditFilters) => (value: string) => setForm((old) => ({ ...old, [name]: value }))

  if (forbidden) return <NoAccess />
  if (!data && error) return <div className="errbox">{error}</div>
  if (!data) return <Loading />
  const filtered = Object.values(filters).some(Boolean)

  return (
    <>
      <div className="card">
        <div className="h2">Who did what and when</div>
        <div className="mut">
          Sign-ins, changes to people, chat and memory actions, Excel downloads and MCP calls - newest first. The
          questions themselves are in each user's History. This log can only be read: nobody can change or delete
          a line. Never holds a password.
        </div>
        <form className="doc-form audit-form" onSubmit={filter}>
          <input type="text" value={form.user} placeholder="User" aria-label="User" maxLength={150}
                 onChange={(e) => set('user')(e.target.value)} />
          <select value={form.action} aria-label="Action" onChange={(e) => set('action')(e.target.value)}>
            <option value="">All actions</option>
            {data.actions.map((a) => <option key={a.code} value={a.code}>{a.text}</option>)}
          </select>
          <input type="date" value={form.from} aria-label="From" onChange={(e) => set('from')(e.target.value)} />
          <input type="date" value={form.to} aria-label="To" onChange={(e) => set('to')(e.target.value)} />
          <input type="text" value={form.q} placeholder="Search target, details, IP ..." aria-label="Search"
                 maxLength={200} onChange={(e) => set('q')(e.target.value)} />
          <button type="submit" className="btn primary">Filter</button>
          {filtered && <Link className="btn secondary" to="/audit">Clear</Link>}
        </form>
      </div>

      {error && <div className="errbox">{error}</div>}
      {data.lines.length ? (
        <>
          <div className="mut">{plural(data.count, 'line')}{filtered ? (data.count === 1 ? ' matches' : ' match') + ' the filters' : ''} - click a line for its details.</div>
          <div className="twrap scroll">
            <table className="t audit-table">
              <thead>
                <tr><th>Time</th><th>User</th><th>Action</th><th>Target</th><th>Details</th><th>IP</th></tr>
              </thead>
              <tbody>
                {data.lines.map((line) => (
                  <Line key={line.id} line={line} open={opened === line.id}
                        onToggle={() => setOpened((now) => (now === line.id ? null : line.id))} />
                ))}
              </tbody>
            </table>
          </div>
          {data.pages > 1 && (
            <div className="pager">
              {data.has_previous && <Link className="btn secondary small" to={pathFor(data.page - 1)}>← Newer</Link>}
              <span className="mut">Page {data.page} of {data.pages}</span>
              {data.has_next && <Link className="btn secondary small" to={pathFor(data.page + 1)}>Older →</Link>}
            </div>
          )}
        </>
      ) : (
        <div className="card">
          <div className="h2">Nothing found</div>
          <div className="mut">{filtered ? 'No audit lines match these filters.' : 'The audit log is still empty.'}</div>
        </div>
      )}
    </>
  )
}
