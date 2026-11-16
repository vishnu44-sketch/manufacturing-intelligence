// The real SQL editor (CodeMirror) in the test browser: it starts with the kept text, puts a name in at the
// cursor, gives the selection (or the whole text) to run, Ctrl+Enter runs, and the schema becomes lang-sql's
// autocomplete namespace (a column shows its type).
import { fireEvent, render, waitFor } from '@testing-library/react'
import { createRef } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { SqlTable } from '../types'
import SqlEditor, { type SqlEditorHandle, schemaOf } from './SqlEditor'

const TABLES: SqlTable[] = [
  { name: 'dim_customers', rows: 5001, columns: [{ name: 'customer_id', type: 'int' }, { name: 'customer_name', type: 'varchar(200)' }] },
]

function editor(initialText = 'SELECT 1') {
  const ref = createRef<SqlEditorHandle>()
  const onChange = vi.fn()
  const onRun = vi.fn()
  const view = render(<SqlEditor ref={ref} initialText={initialText} tables={TABLES} onChange={onChange} onRun={onRun} />)
  const content = view.container.querySelector('.cm-content') as HTMLElement
  return { ref, onChange, onRun, content }
}

describe('SqlEditor', () => {
  it('starts with the kept text and gives the whole text to run', () => {
    const { ref, content } = editor('SELECT * FROM dim_customers')
    expect(content).toHaveAttribute('aria-label', 'SQL editor')
    expect(content).toHaveTextContent('SELECT * FROM dim_customers')
    expect(ref.current?.runText()).toBe('SELECT * FROM dim_customers')
  })

  it('puts a name in at the cursor, with a space after a word, and tells the page', async () => {
    const { ref, onChange } = editor('SELECT')
    ref.current?.setText('SELECT')
    ref.current?.insert('customer_id')
    expect(ref.current?.runText()).toBe('SELECT customer_id')
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith('SELECT customer_id'))

    ref.current?.setText('')
    ref.current?.insert('dim_customers')
    expect(ref.current?.runText()).toBe('dim_customers')
  })

  it('Ctrl+Enter runs (and adds no line)', () => {
    const { ref, onRun, content } = editor('SELECT 1')
    fireEvent.keyDown(content, { key: 'Enter', code: 'Enter', keyCode: 13, ctrlKey: true })
    expect(onRun).toHaveBeenCalledTimes(1)
    expect(ref.current?.runText()).toBe('SELECT 1')
  })

  it('makes the autocomplete schema from the tables', () => {
    expect(schemaOf(TABLES)).toEqual({
      dim_customers: {
        self: { label: 'dim_customers', type: 'type', detail: '5,001 rows' },
        children: [
          { label: 'customer_id', type: 'property', detail: 'int' },
          { label: 'customer_name', type: 'property', detail: 'varchar(200)' },
        ],
      },
    })
  })
})
