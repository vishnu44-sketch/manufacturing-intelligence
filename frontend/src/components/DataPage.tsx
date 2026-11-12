// Data (staff): how many records each table of the NOP data (MySQL ai_gold) has, counted now with the
// read-only user, the invoice dates and the last data load. Main data first, then the lookups, then
// the load history. Read-only: it never asks the AI.
import { useEffect, useState } from 'react'
import { ApiError, AuthError, api } from '../api'
import type { DataTables } from '../types'
import { Loading, NoAccess } from './common'

function kindChip(kind: string): string {
  return kind === 'Main data' ? 'ok' : kind === 'Lookup' ? 'info' : 'skip'
}

export default function DataPage() {
  const [data, setData] = useState<DataTables | null>(null)
  const [error, setError] = useState('')
  const [forbidden, setForbidden] = useState(false)

  useEffect(() => {
    let gone = false
    api.data()
      .then((body) => { if (!gone) setData(body) })
      .catch((err) => {
        if (gone || err instanceof AuthError) return
        if (err instanceof ApiError && err.status === 403) setForbidden(true)
        else setError(err instanceof ApiError ? err.message : 'The table counts could not be loaded.')
      })
    return () => { gone = true }
  }, [])

  if (forbidden) return <NoAccess />
  if (error) return <div className="errbox">{error}</div>
  if (!data) return <Loading>Counting the records…</Loading>

  return (
    <>
      <div className="card">
        <div className="h2">Records in each table</div>
        <div className="mut">
          The tables of the NOP data (MySQL {data.database || 'ai_gold'}) that the AI reads, counted now with the
          read-only user. After a data load the new counts show here at once. This page only reads - it never asks the AI.
        </div>
        {data.tables.length > 0 && (
          <div className="doc-counts">
            <span className="ex on">{data.total} records in {data.table_count} tables</span>
            {data.invoices_from && <span className="ex">Invoices: {data.invoices_from} to {data.invoices_to}</span>}
            {data.last_load && <span className="ex">Last data load: {data.last_load}</span>}
          </div>
        )}
      </div>

      {data.mysql_error ? (
        <div className="errbox">The NOP data (MySQL) cannot be read right now: {data.mysql_error}</div>
      ) : (
        <>
          <div className="twrap scroll">
            <table className="t">
              <thead>
                <tr><th>Table</th><th>What it holds</th><th>Type</th><th className="num">Records</th></tr>
              </thead>
              <tbody>
                {data.tables.length ? data.tables.map((table) => (
                  <tr key={table.name}>
                    <td><code>{table.name}</code></td>
                    <td>{table.note || '-'}</td>
                    <td><span className={`chip ${kindChip(table.kind)}`}>{table.kind.toUpperCase()}</span></td>
                    <td className="num">{table.rows_text}</td>
                  </tr>
                )) : (
                  <tr><td colSpan={4} className="mut">No tables found.</td></tr>
                )}
                {data.tables.length > 0 && (
                  <tr>
                    <td colSpan={3} style={{ fontWeight: 600, color: '#212529' }}>Total</td>
                    <td className="num" style={{ fontWeight: 600, color: '#212529' }}>{data.total}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="mut">
            Most lookup tables also hold one "Unknown" row (id -1), which is counted here (for lines whose customer,
            product ... was not found).
          </div>
        </>
      )}
    </>
  )
}
