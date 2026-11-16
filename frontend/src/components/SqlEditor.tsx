// The SQL editor of the SQL page: CodeMirror 6 with the MySQL dialect, line numbers, undo, bracket
// matching and autocomplete of the ai_gold tables and columns (from the schema the page loaded).
// Ctrl+Enter (Cmd+Enter on a Mac) runs the query. The colours are the site's CSS variables, so the editor
// follows the light / dark look on its own; the dark flag only tells CodeMirror's own base styles.
// SqlPage loads this file lazily: CodeMirror is its own chunk, fetched only on the SQL page. Each editor tab
// of the page has its own editor (its own text, cursor and undo); the hidden ones wait in the page.
import { autocompletion, closeBrackets, closeBracketsKeymap, completionKeymap } from '@codemirror/autocomplete'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { MySQL, type SQLNamespace, sql } from '@codemirror/lang-sql'
import { HighlightStyle, bracketMatching, syntaxHighlighting } from '@codemirror/language'
import { Compartment, EditorState, Prec } from '@codemirror/state'
import {
  EditorView, drawSelection, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers, placeholder,
} from '@codemirror/view'
import { tags as t } from '@lezer/highlight'
import { type Ref, useEffect, useImperativeHandle, useRef } from 'react'
import { useTheme } from '@/lib/theme'
import type { SqlTable } from '../types'

/** What the page can do with the editor. */
export interface SqlEditorHandle {
  /** Puts a name in at the cursor (with a space before it when it would touch the word before). */
  insert: (text: string) => void
  /** Replaces the whole text (Ctrl+Z brings the old text back). */
  setText: (text: string) => void
  /** The selected text, or the whole text when nothing is selected. */
  runText: () => string
  focus: () => void
}

export interface SqlEditorProps {
  initialText: string
  tables: SqlTable[]
  onChange: (text: string) => void
  onRun: () => void
  /** false while the editor's tab is hidden: when it is shown again the editor measures itself again */
  active?: boolean
  ref?: Ref<SqlEditorHandle>
}

/** The tables and their columns as lang-sql's schema, so both autocomplete (a column shows its type). */
export function schemaOf(tables: SqlTable[]): SQLNamespace {
  const schema: Record<string, SQLNamespace> = {}
  for (const table of tables) {
    schema[table.name] = {
      self: { label: table.name, type: 'type', detail: table.rows == null ? 'table' : `${table.rows.toLocaleString('en-US')} rows` },
      children: table.columns.map((column) => ({ label: column.name, type: 'property', detail: column.type })),
    }
  }
  return schema
}

// the look: only the site's colour variables (styles/app.css), so light and dark both work
const look = EditorView.theme({
  '&': { height: '100%', color: 'var(--ink)', backgroundColor: 'var(--surface)', fontSize: '13px' },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace", lineHeight: '1.6',
  },
  '.cm-content': { caretColor: 'var(--ink)', padding: '8px 0' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--ink)' },
  '.cm-gutters': { backgroundColor: 'var(--surface-2)', color: 'var(--faint)', borderRight: '1px solid var(--line)' },
  '.cm-activeLine': { backgroundColor: 'color-mix(in srgb, var(--brand) 5%, transparent)' },
  '.cm-activeLineGutter': { backgroundColor: 'color-mix(in srgb, var(--brand) 9%, transparent)', color: 'var(--ink)' },
  '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection': {
    backgroundColor: 'color-mix(in srgb, var(--brand) 24%, transparent)',
  },
  '.cm-placeholder': { color: 'var(--faint)' },
  '&.cm-focused .cm-matchingBracket': { backgroundColor: 'color-mix(in srgb, var(--brand) 18%, transparent)', outline: 'none' },
  '.cm-tooltip': {
    backgroundColor: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--line-strong)', borderRadius: '8px',
    overflow: 'hidden', boxShadow: '0 12px 28px -16px color-mix(in srgb, var(--shadow-c) 45%, transparent)',
  },
  '.cm-tooltip.cm-tooltip-autocomplete > ul': { fontFamily: 'inherit', maxHeight: '15em' },
  '.cm-tooltip.cm-tooltip-autocomplete > ul > li': { padding: '2px 8px' },
  '.cm-tooltip.cm-tooltip-autocomplete > ul > li[aria-selected]': { backgroundColor: 'var(--brand)', color: 'var(--on-brand)' },
  '.cm-completionDetail': { color: 'inherit', opacity: '.65', marginLeft: '1em', fontStyle: 'normal' },
  '.cm-completionMatchedText': { textDecoration: 'none', fontWeight: '700' },
})

// the colours of the SQL words
const colours = HighlightStyle.define([
  { tag: t.keyword, color: 'var(--brand)', fontWeight: '600' },
  { tag: [t.string, t.special(t.string)], color: 'var(--green)' },
  { tag: [t.number, t.bool, t.null], color: 'var(--amber)' },
  { tag: [t.lineComment, t.blockComment, t.comment], color: 'var(--faint)', fontStyle: 'italic' },
  { tag: [t.typeName, t.standard(t.name)], color: 'var(--purple)' },
  { tag: [t.operator, t.punctuation, t.bracket], color: 'var(--text-2)' },
  { tag: t.special(t.name), color: 'var(--blue)' },
])

const language = (tables: SqlTable[]) => sql({ dialect: MySQL, schema: schemaOf(tables), upperCaseKeywords: true })

export default function SqlEditor({ initialText, tables, onChange, onRun, active = true, ref }: SqlEditorProps) {
  const box = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  const [theme] = useTheme()
  // the parts that change after the editor is made: the schema (autocomplete) and the dark flag
  const parts = useRef({ language: new Compartment(), dark: new Compartment() })
  // the latest callbacks, so the editor (made once) always calls the current ones
  const calls = useRef({ onChange, onRun })
  calls.current = { onChange, onRun }
  // what the editor starts with (read once: later changes of the props reach it through the effects below)
  const start = useRef({ initialText, tables, dark: theme === 'dark' })

  useEffect(() => {
    if (!box.current) return
    const { language: lang, dark } = parts.current
    const made = new EditorView({
      parent: box.current,
      state: EditorState.create({
        doc: start.current.initialText,
        extensions: [
          lineNumbers(),
          highlightActiveLineGutter(),
          highlightActiveLine(),
          history(),
          drawSelection(),
          bracketMatching(),
          closeBrackets(),
          autocompletion(),
          // Ctrl+Enter / Cmd+Enter runs; before the default keys (there Mod-Enter would add a blank line)
          Prec.highest(keymap.of([{ key: 'Mod-Enter', run: () => { calls.current.onRun(); return true }, preventDefault: true }])),
          keymap.of([...closeBracketsKeymap, ...defaultKeymap, ...historyKeymap, ...completionKeymap, indentWithTab]),
          lang.of(language(start.current.tables)),
          syntaxHighlighting(colours),
          look,
          dark.of(EditorView.darkTheme.of(start.current.dark)),
          placeholder('SELECT * FROM dim_customers LIMIT 10;'),
          EditorView.contentAttributes.of({ 'aria-label': 'SQL editor' }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) calls.current.onChange(update.state.doc.toString())
          }),
        ],
      }),
    })
    view.current = made
    return () => {
      made.destroy()
      view.current = null
    }
  }, [])

  // the schema came (or changed): autocomplete knows the tables and columns
  useEffect(() => {
    view.current?.dispatch({ effects: parts.current.language.reconfigure(language(tables)) })
  }, [tables])

  useEffect(() => {
    view.current?.dispatch({ effects: parts.current.dark.reconfigure(EditorView.darkTheme.of(theme === 'dark')) })
  }, [theme])

  // a tab shown again: its editor was hidden (no size), so it measures its lines again
  useEffect(() => {
    if (active) view.current?.requestMeasure()
  }, [active])

  useImperativeHandle(ref, () => ({
    insert(text: string) {
      const editor = view.current
      if (!editor) return
      const { from } = editor.state.selection.main
      const before = from > 0 ? editor.state.sliceDoc(from - 1, from) : ''
      editor.dispatch(editor.state.replaceSelection(/[\w)`'"]/.test(before) ? ` ${text}` : text))
      editor.focus()
    },
    setText(text: string) {
      const editor = view.current
      if (!editor) return
      editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: text }, selection: { anchor: text.length } })
      editor.focus()
    },
    runText() {
      const editor = view.current
      if (!editor) return ''
      const { from, to } = editor.state.selection.main
      return from === to ? editor.state.doc.toString() : editor.state.sliceDoc(from, to)
    },
    focus() {
      view.current?.focus()
    },
  }), [])

  return <div ref={box} className="h-full min-h-0 overflow-hidden" data-testid="sql-editor" />
}
