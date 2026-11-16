// The editor tabs of the SQL page (like MySQL Workbench): each tab has its own SQL text and may point to a
// saved query. The open tabs (not their results) are kept in this browser (localStorage), so a reload brings
// them back. Until 16-Nov the page had one editor whose text was kept in sessionStorage ("mi.sqlText"): that
// text becomes the first tab once, and the old key is removed.
import type { SqlSavedQuery } from '../types'

export const TABS_KEY = 'mi.sqlTabs' // localStorage: the open tabs and which one is shown
export const OLD_TEXT_KEY = 'mi.sqlText' // sessionStorage: the text of the old single editor

export interface SqlTab {
  id: string // this browser's own id of the tab (not the saved query's id)
  title: string // the saved query's name, the file's name, or "Query 1", "Query 2" ...
  text: string
  base: string // the text as last saved or opened: text !== base means unsaved changes
  savedId: number | null // the saved query this tab shows (null: not saved yet)
  mine: boolean // false: someone else's shared query (only Save as works)
  ownerName: string // the owner of the saved query (for the "Only ... can change" note)
}

export interface TabsState {
  tabs: SqlTab[]
  active: string
}

let counter = 0
/** A new id for a tab (unique in this browser). */
export function tabId(): string {
  counter += 1
  return `t${Date.now().toString(36)}${counter}`
}

/** True when the tab has changes that are not saved. */
export const isDirty = (tab: SqlTab) => tab.text !== tab.base

/** True when the tab is empty and unchanged (opening a saved query may use it instead of a new tab). */
export const isBlank = (tab: SqlTab) => tab.savedId === null && !tab.text && !tab.base

/** "Query N" with the smallest N no open tab uses. */
export function nextTitle(tabs: SqlTab[]): string {
  const used = new Set(tabs.map((tab) => tab.title))
  let n = 1
  while (used.has(`Query ${n}`)) n += 1
  return `Query ${n}`
}

export function newTab(tabs: SqlTab[], text = ''): SqlTab {
  return { id: tabId(), title: nextTitle(tabs), text, base: '', savedId: null, mine: true, ownerName: '' }
}

/** A tab showing a saved query (no unsaved changes). */
export function savedTab(query: SqlSavedQuery): SqlTab {
  return { id: tabId(), title: query.name, text: query.sql, base: query.sql, savedId: query.id, mine: query.mine, ownerName: query.owner_name }
}

function validTab(value: unknown): value is SqlTab {
  if (!value || typeof value !== 'object') return false
  const tab = value as Record<string, unknown>
  return typeof tab.id === 'string' && typeof tab.title === 'string' && typeof tab.text === 'string'
}

/** The tabs kept in this browser; else the old single editor's text as the first tab; else one empty tab. */
export function readTabs(): TabsState {
  try {
    const kept: unknown = JSON.parse(window.localStorage.getItem(TABS_KEY) ?? 'null')
    if (kept && typeof kept === 'object' && Array.isArray((kept as TabsState).tabs)) {
      const tabs = (kept as TabsState).tabs.filter(validTab).map((tab) => ({
        id: tab.id, title: tab.title, text: tab.text,
        base: typeof tab.base === 'string' ? tab.base : '',
        savedId: typeof tab.savedId === 'number' ? tab.savedId : null,
        mine: tab.mine !== false,
        ownerName: typeof tab.ownerName === 'string' ? tab.ownerName : '',
      }))
      if (tabs.length) {
        const active = (kept as TabsState).active
        return { tabs, active: tabs.some((tab) => tab.id === active) ? active : tabs[0].id }
      }
    }
  } catch {
    // storage blocked or a broken value: start fresh below
  }
  let old = ''
  try {
    old = window.sessionStorage.getItem(OLD_TEXT_KEY) ?? '' // removed once the tabs are kept (keepTabs)
  } catch {
    old = ''
  }
  const first = newTab([], old)
  return { tabs: [first], active: first.id }
}

export function keepTabs(state: TabsState) {
  try {
    window.localStorage.setItem(TABS_KEY, JSON.stringify(state))
    window.sessionStorage.removeItem(OLD_TEXT_KEY) // the old single text now lives in the first tab
  } catch {
    // storage blocked or full: the tabs last until the page is loaded again
  }
}

/** A file name for the tab's text: the title without characters a file name cannot have, plus ".sql". */
export function sqlFileName(title: string): string {
  const name = title.replace(/[\\/:*?"<>|]+/g, '_').trim().replace(/\.(sql|txt)$/i, '')
  return `${name || 'query'}.sql`
}
