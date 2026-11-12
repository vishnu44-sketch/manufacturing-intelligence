// Documents (staff): what the AI can read - every piece in the vector store (a file and a text filter)
// and a test search that shows the pieces the AI would get for a question, best first, with their
// score. The filters live in the address (/documents?source=..&find=..&q=..), so Back works.
// Read-only: no AI call and nothing is written.
import { type FormEvent, useEffect, useState } from 'react'
import { ApiError, AuthError, api, query } from '../api'
import { Link, useRouter } from '../router'
import type { DocumentsData } from '../types'
import { Loading, NoAccess } from './common'

function kindChip(kind: string): string {
  return kind === 'example' ? 'ok' : kind === 'rule' ? 'skip' : 'info'
}

export default function DocumentsPage({ source, find, q }: { source: string; find: string; q: string }) {
  const { navigate } = useRouter()
  const [data, setData] = useState<DocumentsData | null>(null)
  const [error, setError] = useState('')
  const [forbidden, setForbidden] = useState(false)
  const [question, setQuestion] = useState(q)
  const [file, setFile] = useState(source)
  const [word, setWord] = useState(find)

  useEffect(() => { setQuestion(q); setFile(source); setWord(find) }, [q, source, find])

  useEffect(() => {
    let gone = false
    setError('')
    api.documents({ source, find, q })
      .then((body) => { if (!gone) setData(body) })
      .catch((err) => {
        if (gone || err instanceof AuthError) return
        if (err instanceof ApiError && err.status === 403) setForbidden(true)
        else setError(err instanceof ApiError ? err.message : 'The documents could not be loaded.')
      })
    return () => { gone = true }
  }, [source, find, q])

  const go = (params: { source?: string; find?: string; q?: string }) => navigate(`/documents${query(params)}`)

  function search(event: FormEvent) {
    event.preventDefault()
    go({ q: question.trim() })
  }

  function filter(event: FormEvent) {
    event.preventDefault()
    go({ source: file, find: word.trim() })
  }

  if (forbidden) return <NoAccess />
  if (error) return <div className="errbox">{error}</div>
  if (!data) return <Loading />

  return (
    <>
      <div className="card">
        <div className="h2">What the AI can read</div>
        <div className="mut">
          The pieces of docs/ stored in the vector store. For every question the AI gets the 5 pieces closest to it.
          After a change in docs/, an admin runs <code>python manage.py ingest_docs</code>. This page only reads - it
          never asks the AI.
        </div>
        <div className="mut doc-db">Vector DB: <b>{data.vector_db}</b></div>
        {data.total > 0 && (
          <div className="doc-counts">
            <Link className={`ex${!source ? ' on' : ''}`} to="/documents">All files · {data.total} pieces</Link>
            {data.counts.map(({ source: name, count }) => (
              <Link key={name} className={`ex${source === name ? ' on' : ''}`} to={`/documents${query({ source: name })}`}>
                {name} · {count}
              </Link>
            ))}
          </div>
        )}
      </div>

      {data.store_error ? (
        <div className="errbox">{data.store_error}</div>
      ) : !data.total ? (
        <div className="errbox">{data.store_empty}</div>
      ) : (
        <>
          <div className="card">
            <div className="h2">Test search</div>
            <div className="mut">Type a question to see which pieces the AI would get for it, best first.</div>
            <form className="doc-form" onSubmit={search}>
              <input type="text" value={question} maxLength={1000} placeholder="What is our current stock value?"
                     aria-label="Question" onChange={(e) => setQuestion(e.target.value)} />
              <button type="submit" className="btn primary">Search</button>
            </form>
            {data.search_error ? (
              <div className="errbox" style={{ marginTop: 12 }}>{data.search_error}</div>
            ) : data.question ? (
              <>
                <div className="doc-hits">
                  {data.hits.length ? data.hits.map((hit, i) => (
                    <details className="doc-piece" key={i}>
                      <summary>
                        <span className="doc-rank">{i + 1}</span>
                        <span className={`chip ${kindChip(hit.kind)}`}>{hit.kind.toUpperCase()}</span>
                        <span className="doc-score" title="cosine similarity, 1.00 = same meaning">
                          score {hit.score === null ? '-' : hit.score.toFixed(2)}
                        </span>
                        <span className="doc-head">{hit.heading}</span>
                        <span className="mut">{hit.source}</span>
                      </summary>
                      <pre className="doc-text">{hit.text}</pre>
                    </details>
                  )) : <div className="mut">No pieces found.</div>}
                </div>
                {data.tables && (
                  <div className="mut doc-tables">
                    {data.tables.all
                      ? 'The SQL step would show the columns of every table for this question.'
                      : `The SQL step would show the columns of: ${data.tables.names.join(', ')} (the other tables are only named).`}
                  </div>
                )}
              </>
            ) : null}
          </div>

          <div className="card">
            <div className="h2">All pieces</div>
            <form className="doc-form" onSubmit={filter}>
              <select aria-label="File" value={file} onChange={(e) => setFile(e.target.value)}>
                <option value="">All files</option>
                {data.counts.map(({ source: name }) => <option key={name} value={name}>{name}</option>)}
              </select>
              <input type="text" value={word} placeholder="Find a word in a heading or text" aria-label="Find"
                     onChange={(e) => setWord(e.target.value)} />
              <button type="submit" className="btn secondary">Filter</button>
              {(source || find) && <Link className="btn secondary" to="/documents">Clear</Link>}
            </form>
            <div className="mut" style={{ margin: '10px 0 6px' }}>
              Showing {data.pieces.length} of {data.total} pieces. Click a piece to read its full text.
            </div>
            <div className="doc-list">
              {data.pieces.length ? data.pieces.map((piece) => (
                <details className="doc-piece" key={piece.id || piece.no}>
                  <summary>
                    <span className="doc-rank">{piece.no}</span>
                    <span className={`chip ${kindChip(piece.kind)}`}>{piece.kind.toUpperCase()}</span>
                    <span className="doc-head">{piece.heading}</span>
                    <span className="mut">{piece.source}</span>
                  </summary>
                  <pre className="doc-text">{piece.text}</pre>
                </details>
              )) : <div className="mut">No piece matches this filter.</div>}
            </div>
          </div>
        </>
      )}
    </>
  )
}
