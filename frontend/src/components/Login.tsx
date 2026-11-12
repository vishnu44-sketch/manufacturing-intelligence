// The sign-in page (/login, and any page while signed out), the look of the old Django one: the brand
// banner on the left, the card on the right. It signs in through POST /api/login (a session cookie).
import { type FormEvent, useState } from 'react'
import { ApiError, api } from '../api'

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
    <div className="login-split">
      <div className="login-brand">
        <div className="lb-top">
          <div className="brand-mark lb-logo">MI</div>
          <div className="lb-sub">MANUFACTURING INTELLIGENCE</div>
        </div>
        <div className="lb-mid">
          <div className="lb-tag">
            Ask in plain English. <span>Get</span> the numbers.
          </div>
          <div className="lb-text">
            Type a question about sales, invoices or stock and get a short answer, the rows behind it and the SQL
            that was run.
          </div>
          <div className="lb-pills">
            <span>Plain-English questions</span>
            <span>Answer + rows</span>
            <span>SQL shown</span>
            <span>Excel download</span>
          </div>
        </div>
        <div className="lb-foot">Demo project · synthetic data</div>
      </div>

      <div className="login-side">
        <div className="login-card">
          <div>
            <div style={{ fontSize: 21, fontWeight: 600, color: '#32353A' }}>Sign in</div>
            <div style={{ fontSize: 13, color: '#6C757D', margin: '4px 0 8px' }}>
              Manufacturing Intelligence — authorised users only
            </div>
            <div
              style={{ height: 4, width: 64, borderRadius: 3, background: 'linear-gradient(90deg,#C00000,#E84545)' }}
            />
          </div>

          {error && (
            <div className="errbox" role="alert">
              {error}
            </div>
          )}

          <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div>
              <label className="f" htmlFor="id_username">User ID</label>
              <input type="text" id="id_username" autoFocus autoComplete="username" required value={username}
                     onChange={(e) => setUsername(e.target.value)} />
            </div>
            <div>
              <label className="f" htmlFor="id_password">Password</label>
              <input type="password" id="id_password" autoComplete="current-password" required value={password}
                     onChange={(e) => setPassword(e.target.value)} />
            </div>
            <button type="submit" className={`btn primary block${busy ? ' loading' : ''}`} disabled={busy}
                    style={{ padding: '13px 0', fontSize: 15 }}>
              {busy && <span className="spin" />}Sign in
            </button>
          </form>

          <div style={{ textAlign: 'center', fontSize: 12.5, color: '#6C757D' }}>
            Forgot password? Contact the administrator.
          </div>
        </div>
        <footer className="app-foot login-foot">
          <span>© {new Date().getFullYear()} Manufacturing Intelligence · demo project with synthetic data</span>
        </footer>
      </div>
    </div>
  )
}
