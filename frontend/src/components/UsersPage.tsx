// Users (staff): everyone who can sign in, and - with the admin's permissions - add a person, change
// a person's details, switch someone off / on and set a new password. The server makes every check
// (the admin's forms and password rules); this page shows its messages next to the fields. Only a
// superuser makes someone staff / superuser or changes a superuser; nobody switches himself off.
import { type FormEvent, type ReactNode, useCallback, useEffect, useState } from 'react'
import { ApiError, AuthError, api, problemText } from '../api'
import type { PeopleList, Person } from '../types'
import { Loading, NoAccess } from './common'

type Editor = { mode: 'add' } | { mode: 'edit'; person: Person } | { mode: 'password'; person: Person } | null
type Fields = Record<string, string | boolean>
type Flash = { kind: 'ok' | 'error'; text: string } | null

const EMPTY: Fields = {
  username: '', first_name: '', last_name: '', email: '', password1: '', password2: '', is_staff: false, is_superuser: false,
}

function Field({ label, name, errors, children }: { label: string; name: string; errors: Record<string, string[]>; children: ReactNode }) {
  return (
    <div className="person-field">
      <label className="f" htmlFor={`person-${name}`}>{label}</label>
      {children}
      {(errors[name] ?? []).map((message) => <div className="field-error" key={message}>{message}</div>)}
    </div>
  )
}

function PersonForm({ editor, list, onSaved, onCancel }:
  { editor: Exclude<Editor, null>; list: PeopleList; onSaved: (message: string) => void; onCancel: () => void }) {
  const person = editor.mode === 'add' ? null : editor.person
  const [fields, setFields] = useState<Fields>(() => (person
    ? { ...EMPTY, username: person.username, first_name: person.first_name, last_name: person.last_name,
        email: person.email, is_staff: person.is_staff, is_superuser: person.is_superuser }
    : EMPTY))
  const [errors, setErrors] = useState<Record<string, string[]>>({})
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState(false)

  const text = (name: string) => String(fields[name] ?? '')
  const set = (name: string, value: string | boolean) => setFields((old) => ({ ...old, [name]: value }))
  const input = (name: string, type = 'text', autoComplete = 'off') => (
    <input id={`person-${name}`} type={type} value={text(name)} autoComplete={autoComplete}
           onChange={(e) => set(name, e.target.value)} />
  )

  async function save(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setErrors({})
    setProblem('')
    try {
      const { password1, password2, ...details } = fields
      const reply = editor.mode === 'add' ? await api.addPerson(fields)
        : editor.mode === 'edit' ? await api.changePerson(editor.person.id, details)
        : await api.setPassword(editor.person.id, String(password1), String(password2))
      onSaved(reply.message)
    } catch (err) {
      if (err instanceof AuthError) return
      if (err instanceof ApiError) {
        setErrors(err.errors)
        setProblem([err.message, ...(err.errors.__all__ ?? [])].join(' '))
      } else {
        setProblem('Saving did not work - please try again.')
      }
      setBusy(false)
    }
  }

  const title = editor.mode === 'add' ? 'Add a person'
    : editor.mode === 'edit' ? `Change ${editor.person.username}` : `New password for ${editor.person.username}`
  return (
    <form className="card person-form" onSubmit={save} aria-label={title}>
      <div className="h2">{title}</div>
      {problem && <div className="errbox" role="alert">{problem}</div>}
      <div className="person-grid">
        {editor.mode !== 'password' && (
          <>
            <Field label="User ID (sign-in name)" name="username" errors={errors}>{input('username')}</Field>
            <Field label="Email" name="email" errors={errors}>{input('email', 'email')}</Field>
            <Field label="First name" name="first_name" errors={errors}>{input('first_name')}</Field>
            <Field label="Last name" name="last_name" errors={errors}>{input('last_name')}</Field>
          </>
        )}
        {editor.mode !== 'edit' && (
          <>
            <Field label="Password" name="password1" errors={errors}>{input('password1', 'password', 'new-password')}</Field>
            <Field label="Password again" name="password2" errors={errors}>{input('password2', 'password', 'new-password')}</Field>
          </>
        )}
      </div>
      {editor.mode !== 'password' && list.can_set_roles && (
        <div className="person-roles">
          <label><input type="checkbox" checked={Boolean(fields.is_staff)} onChange={(e) => set('is_staff', e.target.checked)} /> Staff (Admin pages)</label>
          <label><input type="checkbox" checked={Boolean(fields.is_superuser)} onChange={(e) => set('is_superuser', e.target.checked)} /> Superuser (every right)</label>
        </div>
      )}
      {editor.mode !== 'edit' && (
        <div className="mut">At least 8 characters, not only numbers, not a common password and not like the user's name.</div>
      )}
      <div className="person-buttons">
        <button type="button" className="btn secondary" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className={`btn primary${busy ? ' loading' : ''}`} disabled={busy}>
          {busy && <span className="spin" />}{editor.mode === 'add' ? 'Add the person' : 'Save'}
        </button>
      </div>
    </form>
  )
}

export default function UsersPage() {
  const [list, setList] = useState<PeopleList | null>(null)
  const [error, setError] = useState('')
  const [forbidden, setForbidden] = useState(false)
  const [editor, setEditor] = useState<Editor>(null)
  const [flash, setFlash] = useState<Flash>(null)

  const load = useCallback(() => {
    api.people()
      .then(setList)
      .catch((err) => {
        if (err instanceof AuthError) return
        if (err instanceof ApiError && err.status === 403) setForbidden(true)
        else setError(problemText(err, 'The people could not be loaded.'))
      })
  }, [])
  useEffect(load, [load])

  function saved(message: string) {
    setEditor(null)
    setFlash({ kind: 'ok', text: message })
    load()
  }

  async function switchActive(person: Person) {
    setFlash(null)
    try {
      const reply = await api.setActive(person.id, !person.is_active)
      setFlash({ kind: 'ok', text: reply.message })
      load()
    } catch (err) {
      if (!(err instanceof AuthError)) setFlash({ kind: 'error', text: problemText(err) })
    }
  }

  if (forbidden) return <NoAccess />
  if (error) return <div className="errbox">{error}</div>
  if (!list) return <Loading />

  const mayChange = (person: Person) => list.can_change && (!person.is_superuser || list.can_set_roles)
  return (
    <>
      <div className="card">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <div className="h2" style={{ marginBottom: 2 }}>People who can sign in</div>
            <div className="mut">Add a person, change details, switch someone off or set a new password here - or in Django admin.</div>
          </div>
          <a className="btn secondary" style={{ marginLeft: 'auto' }} href={list.admin_url}>Open in admin</a>
          {list.can_add && (
            <button type="button" className="btn primary" onClick={() => { setFlash(null); setEditor({ mode: 'add' }) }}>
              + Add a person
            </button>
          )}
        </div>
      </div>

      {flash && <div className={flash.kind === 'ok' ? 'okbox' : 'errbox'} role="status">{flash.text}</div>}
      {editor && (
        <PersonForm key={editor.mode === 'add' ? 'add' : `${editor.mode}-${editor.person.id}`} editor={editor} list={list}
                    onSaved={saved} onCancel={() => setEditor(null)} />
      )}

      <div className="twrap scroll">
        <table className="t">
          <thead>
            <tr><th>Person</th><th>Sign-in name</th><th>Role</th><th>Access</th><th>Last sign-in</th><th /></tr>
          </thead>
          <tbody>
            {list.people.map((person) => (
              <tr key={person.id} style={person.is_active ? undefined : { opacity: 0.55 }}>
                <td>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
                    <span className="person-avatar">{person.username.slice(0, 2).toUpperCase()}</span>
                    <span>
                      <span style={{ fontWeight: 600, color: '#212529' }}>{person.name}</span>
                      {person.is_me && <span className="mut"> (you)</span>}<br />
                      <span className="mut">{person.email || 'no email'}</span>
                    </span>
                  </span>
                </td>
                <td>{person.username}</td>
                <td>
                  {person.is_superuser ? <span className="chip fail">SUPERUSER</span>
                    : person.is_staff ? <span className="chip info">STAFF</span>
                    : <span className="chip skip">USER</span>}
                </td>
                <td>
                  {person.is_active
                    ? <span style={{ color: '#1B7F3B' }}>● Can sign in</span>
                    : <span className="mut">● Switched off</span>}
                </td>
                <td>{person.last_login || 'never'}</td>
                <td>
                  {mayChange(person) && (
                    <div className="actions">
                      <button type="button" className="btn secondary small" aria-label={`Edit ${person.username}`}
                              onClick={() => { setFlash(null); setEditor({ mode: 'edit', person }) }}>Edit</button>
                      <button type="button" className="btn secondary small" aria-label={`New password for ${person.username}`}
                              onClick={() => { setFlash(null); setEditor({ mode: 'password', person }) }}>Password</button>
                      {!person.is_me && (
                        <button type="button" className="btn secondary small" onClick={() => switchActive(person)}
                                aria-label={`${person.is_active ? 'Switch off' : 'Switch on'} ${person.username}`}>
                          {person.is_active ? 'Switch off' : 'Switch on'}
                        </button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
