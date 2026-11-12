// Memory (every user): the facts the user asked the app to remember ("Remember that I only work with export
// sales"), newest first with their date. They are used in all the user's later chats. Add one by hand, delete
// one, or delete all (after "Are you sure?"). Only the user's own memories - nobody else sees them.
import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { AuthError, api, problemText } from '../api'
import { Link, questionPath } from '../router'
import type { Memory, MemoryList } from '../types'
import { Loading, plural } from './common'

type Flash = { kind: 'ok' | 'error'; text: string } | null

export function deleteAllQuestion(count: number): string {
  return `Delete all ${plural(count, 'memory', 'memories')}? Your next questions will no longer use them. This cannot be undone.`
}

export default function MemoryPage() {
  const [list, setList] = useState<MemoryList | null>(null)
  const [error, setError] = useState('')
  const [flash, setFlash] = useState<Flash>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api.memories()
      .then(setList)
      .catch((err) => {
        if (!(err instanceof AuthError)) setError(problemText(err, 'Your memories could not be loaded.'))
      })
  }, [])
  useEffect(load, [load])

  async function change(work: () => Promise<{ message: string }>) {
    setFlash(null)
    setBusy(true)
    try {
      const reply = await work()
      setFlash({ kind: 'ok', text: reply.message })
      load()
      return true
    } catch (err) {
      if (!(err instanceof AuthError)) setFlash({ kind: 'error', text: problemText(err) })
      return false
    } finally {
      setBusy(false)
    }
  }

  async function add(event: FormEvent) {
    event.preventDefault()
    if (!text.trim() || busy) return
    if (await change(() => api.addMemory(text))) setText('')
  }

  function remove(memory: Memory) {
    void change(() => api.deleteMemory(memory.id))
  }

  function removeAll() {
    if (!list || !window.confirm(deleteAllQuestion(list.memories.length))) return
    void change(() => api.deleteAllMemories())
  }

  if (error) return <div className="errbox">{error}</div>
  if (!list) return <Loading />

  const full = list.memories.length >= list.limit
  return (
    <>
      <div className="card">
        <div className="h2">What I remember about you</div>
        <div className="mut">
          Tell me something to keep in mind, e.g. "Remember that I only work with export sales", "From now on show
          amounts in lakhs", "Always ...", "Never show ..." or "I only work with ...". It is saved here (no AI call) and
          used in all your later chats: the SQL and the answer follow it when it fits the question, and the answer says
          when it did. A question that asks for something else still wins, and a memory never changes the safety rules.
          If a memory is wrong or no longer true, delete it - your next questions will not use it.
        </div>
        <div className="doc-counts">
          <span className="ex on">{plural(list.memories.length, 'memory', 'memories')} of {list.limit}</span>
          {list.memories.length > 0 && (
            <button type="button" className="btn secondary small" onClick={removeAll} disabled={busy}>Delete all</button>
          )}
        </div>
      </div>

      {flash && <div className={flash.kind === 'ok' ? 'okbox' : 'errbox'} role="status">{flash.text}</div>}

      <div className="card">
        <div className="h2">Add a memory</div>
        <form className="doc-form" onSubmit={add}>
          <input type="text" value={text} maxLength={list.max_chars} aria-label="New memory"
                 placeholder="I only work with export sales" disabled={full}
                 onChange={(e) => setText(e.target.value)} />
          <button type="submit" className={`btn primary${busy ? ' loading' : ''}`} disabled={busy || full || !text.trim()}>
            {busy && <span className="spin" />}Add
          </button>
        </form>
        {full && <div className="mut">Your memory is full - delete some memories first.</div>}
      </div>

      <div className="twrap scroll">
        <table className="t">
          <thead>
            <tr><th>Memory</th><th>Saved</th><th /></tr>
          </thead>
          <tbody>
            {list.memories.length ? list.memories.map((memory) => (
              <tr key={memory.id}>
                <td style={{ color: '#212529', fontWeight: 500 }}>{memory.text}</td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  {memory.created_text}
                  {memory.question_id != null && (
                    <div><Link to={questionPath(memory.question_id)} className="history-q">from a question</Link></div>
                  )}
                </td>
                <td>
                  <button type="button" className="btn secondary small" disabled={busy}
                          aria-label={`Delete "${memory.text}"`} onClick={() => remove(memory)}>Delete</button>
                </td>
              </tr>
            )) : (
              <tr><td colSpan={3} className="mut">Nothing saved yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  )
}
