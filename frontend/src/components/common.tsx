// Small pieces several pages use: the loading dots, the "no access" and "not found" cards, a page's
// loading / error line, and the Excel download link (it shows the server's message when MySQL cannot
// run the saved SQL now).
import { type MouseEvent, type ReactNode, useState } from 'react'
import { AuthError, download, problemText } from '../api'
import { Link } from '../router'

export const Dots = () => <span className="dots"><i /><i /><i /></span>

export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n} ${n === 1 ? word : many}`
}

/** A staff-only page for someone who is not staff (or the API said 403). */
export function NoAccess() {
  return (
    <div className="card">
      <div className="h2">You do not have access to this page</div>
      <div className="mut" style={{ margin: '6px 0 16px' }}>
        Only administrators can open it. If you need it, ask an administrator.
      </div>
      <Link className="btn primary" to="/ask">Go to Ask AI</Link>
    </div>
  )
}

export function NotFound() {
  return (
    <div className="card">
      <div className="h2">This page does not exist</div>
      <div className="mut" style={{ margin: '6px 0 16px' }}>The address may be old or mistyped.</div>
      <Link className="btn primary" to="/ask">Go to Ask AI</Link>
    </div>
  )
}

/** "Loading…" while a page waits for its data. */
export function Loading({ children = 'Loading…' }: { children?: ReactNode }) {
  return <div className="rows-wait mut" role="status"><Dots /> {children}</div>
}

/** The Excel download: a real link (works as a plain download too); a click fetches the file so a
 *  failure shows as a friendly message instead of an error page. The Ask page passes its own look
 *  (className, and busyIcon while the file is made); without them it is the old "btn secondary small". */
export function ExcelLink({ url, children, className, busyIcon }:
  { url: string; children: ReactNode; className?: string; busyIcon?: ReactNode }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function fetchFile(event: MouseEvent<HTMLAnchorElement>) {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await download(url)
    } catch (err) {
      if (!(err instanceof AuthError)) setError(problemText(err, 'The Excel file could not be made.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <a className={className ?? `btn secondary small${busy ? ' loading' : ''}`} href={url} onClick={fetchFile}
         aria-busy={className && busy ? true : undefined}>
        {busy && (busyIcon ?? <span className="spin" />)}{children}
      </a>
      {error && <span className="errbox excel-error" role="alert">{error}</span>}
    </>
  )
}
