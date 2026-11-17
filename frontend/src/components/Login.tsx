// The sign-in page (/login, and any page while signed out): one card in the middle - the SSAGE mark and name,
// what it is for, then the form. It signs in through POST /api/login (a session cookie).
import { type FormEvent, useState } from 'react'
import { ApiError, api } from '../api'
import { APP_NAME, APP_SUBTITLE, FOOTER_TEXT } from '../lib/brand'
import BrandMark from './BrandMark'

export default function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await api.login(username, password)
      onSignedIn()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Signing in did not work - please try again.')
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <main className="login-card">
        <div className="lc-brand">
          <BrandMark size={46} />
          <div className="lc-brand-text">
            <div className="lc-name">{APP_NAME}</div>
            <div className="lc-sub">{APP_SUBTITLE}</div>
          </div>
        </div>
        <p className="lc-text">
          Ask about sales, orders, stock and company documents across SS Manufacturing - in plain English.
        </p>
        <div className="lc-pills" aria-label="What you can ask about">
          <span>Sales &amp; invoices</span>
          <span>Orders &amp; stock</span>
          <span>Company PDFs</span>
        </div>

        {error && (
          <div className="errbox" role="alert">
            {error}
          </div>
        )}

        <form onSubmit={submit} className="lc-form">
          <div>
            <label className="f" htmlFor="id_username">User ID</label>
            <input type="text" id="id_username" autoFocus autoComplete="username" required value={username}
                   placeholder="Enter your user ID" onChange={(e) => setUsername(e.target.value)} />
          </div>
          <div>
            <label className="f" htmlFor="id_password">Password</label>
            <input type="password" id="id_password" autoComplete="current-password" required value={password}
                   placeholder="Enter your password" onChange={(e) => setPassword(e.target.value)} />
          </div>
          <button type="submit" className={`btn primary block lc-submit${busy ? ' loading' : ''}`} disabled={busy}>
            {busy && <span className="spin" />}Sign in
          </button>
        </form>

        <div className="lc-note">
          Authorised users only. For access or a new password, contact your administrator.
        </div>
      </main>
      <footer className="login-foot">© {new Date().getFullYear()} {FOOTER_TEXT}</footer>
    </div>
  )
}
