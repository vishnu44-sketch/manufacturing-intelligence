// The frame of every page: a top bar across the window (the "MI" mark and the product name on the left; on the
// right "New chat", "History", the dark-mode button and the user's round badge, which opens a small menu with
// the name, the role and "Sign out"), and under it the light menu on the left, in groups: Home (Home, Assistant),
// Intelligence (Knowledge graph), Tools (History, Memory) and - for staff only - Administration (Users,
// Documents, Data, Audit). The page it is on is a filled pill. The browser tab shows "<page> · Manufacturing Intelligence".
// Above the page is a row with its title (a page can go without it: header={false}, as Home does).
// The « button under the menu makes it small (icons only, the name on hover) on every page; » opens it again. The
// choice is kept in this browser (localStorage). On a phone the menu is a drawer, opened by the ☰ button in the top bar.
// Colours are the names of src/tailwind.css (light and dark); the layout is in shell.css.
import {
  Brain, ChevronsLeft, ChevronsRight, Clock, Database, FileText, History, House, LogOut, type LucideIcon, Menu,
  MessageSquareText, Moon, Network, Plus, ShieldCheck, Sun, Users,
} from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { useTheme } from '@/lib/theme'
import { Link, useRouter } from '../router'
import type { Me } from '../types'
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover'
import './shell.css'

export type MenuItem = 'home' | 'ask' | 'history' | 'memory' | 'graph' | 'users' | 'documents' | 'data' | 'audit' | ''

/** A time as the clock shows it, in India time: "Friday, 06 November 2026 · 10:56 AM IST". */
export function istText(at: Date): string {
  const parts: Record<string, string> = {}
  new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata', weekday: 'long', day: '2-digit', month: 'long', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: true,
  }).formatToParts(at).forEach((p) => { parts[p.type] = p.value })
  return `${parts.weekday}, ${parts.day} ${parts.month} ${parts.year} · ${parts.hour}:${parts.minute} ${(parts.dayPeriod || '').toUpperCase()} IST`
}

/** The time now, changing exactly when the minute changes (the clock in the Home banner). */
export function useMinute(): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    let every: number | undefined
    const first = window.setTimeout(() => {
      setNow(new Date())
      every = window.setInterval(() => setNow(new Date()), 60000)
    }, 60000 - (Date.now() % 60000))
    return () => { window.clearTimeout(first); window.clearInterval(every) }
  }, [])
  return now
}

interface Entry { to: string; item: MenuItem; name: string; icon: LucideIcon }
interface Group { name: string; staffOnly?: boolean; entries: Entry[] }

/** The left menu, group by group. */
const MENU: Group[] = [
  { name: 'Home', entries: [
    { to: '/', item: 'home', name: 'Home', icon: House },
    { to: '/ask', item: 'ask', name: 'Assistant', icon: MessageSquareText },
  ] },
  { name: 'Intelligence', entries: [
    { to: '/graph', item: 'graph', name: 'Knowledge graph', icon: Network },
  ] },
  { name: 'Tools', entries: [
    { to: '/history', item: 'history', name: 'History', icon: History },
    { to: '/memory', item: 'memory', name: 'Memory', icon: Brain },
  ] },
  { name: 'Administration', staffOnly: true, entries: [
    { to: '/users', item: 'users', name: 'Users', icon: Users },
    { to: '/documents', item: 'documents', name: 'Documents', icon: FileText },
    { to: '/data', item: 'data', name: 'Data', icon: Database },
    { to: '/audit', item: 'audit', name: 'Audit', icon: ShieldCheck },
  ] },
]

const SLIM_KEY = 'mi.menuSlim'

/** Was the menu made small in this browser? (No storage: open.) */
function readSlim(): boolean {
  try {
    return window.localStorage.getItem(SLIM_KEY) === '1'
  } catch {
    return false
  }
}

// a button or link of the top bar: text with an icon, a soft tint under the mouse
const TOP_ITEM = 'inline-flex h-9 flex-none items-center justify-center gap-1.5 rounded-full px-3 text-[13.5px] font-medium transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring'
// a round icon button of the top bar
const TOP_ICON = 'inline-flex size-9 flex-none items-center justify-center rounded-full transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring'

function MenuLink({ entry, active, slim }: { entry: Entry; active: MenuItem; slim: boolean }) {
  const on = entry.item === active
  const Icon = entry.icon
  return (
    // the colour is on the row: the link takes it over (shell.css), so the site's link colour does not show
    <li className={on ? 'text-primary-foreground' : 'text-sidebar-foreground'}>
      <Link to={entry.to} aria-current={on ? 'page' : undefined} title={slim ? entry.name : undefined}
        className={cn(
          'mi-shell-link flex h-10 items-center gap-3 rounded-full px-3.5 text-[13.5px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
          on ? 'bg-primary font-semibold' : 'font-medium hover:bg-sidebar-accent')}>
        <Icon size={17} strokeWidth={1.8} className="flex-none" />
        <span className="mi-shell-text truncate">{entry.name}</span>
      </Link>
    </li>
  )
}

export default function Shell({ me, title, active, onSignOut, header = true, children }:
  { me: Me; title: string; active: MenuItem; onSignOut: () => void; header?: boolean; children: ReactNode }) {
  useEffect(() => {
    document.title = `${title} · Manufacturing Intelligence`
  }, [title])

  const [slim, setSlim] = useState(readSlim)
  const toggleMenu = () => {
    const next = !slim
    setSlim(next)
    try {
      if (next) window.localStorage.setItem(SLIM_KEY, '1')
      else window.localStorage.removeItem(SLIM_KEY)
    } catch {
      // storage blocked: small until the page is loaded again
    }
  }

  // the phone drawer: closed again on every new page and by the Esc key
  const [drawer, setDrawer] = useState(false)
  const { route } = useRouter()
  useEffect(() => setDrawer(false), [route])
  useEffect(() => {
    if (!drawer) return
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setDrawer(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawer])

  const [theme, toggleTheme] = useTheme()
  const dark = theme === 'dark'
  const themeName = dark ? 'Light mode' : 'Dark mode' // what a press switches to

  return (
    <div className={cn('mi-shell ui-scope bg-background text-foreground', slim && 'mi-shell-slim', drawer && 'mi-shell-drawer-open')}>
      <header className="mi-shell-top flex items-center gap-2 border-b border-border bg-card px-3 text-foreground sm:px-5">
        <button type="button" className={cn(TOP_ICON, 'mi-shell-burger')} aria-label="Menu" aria-expanded={drawer}
          aria-controls="mi-shell-menu" onClick={() => setDrawer(!drawer)}>
          <Menu size={19} strokeWidth={1.8} />
        </button>
        <Link to="/" className="mi-shell-link flex min-w-0 items-center gap-2.5 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
          <span aria-hidden="true" className="grid size-9 flex-none place-items-center rounded-[10px] bg-primary text-[13px] font-bold tracking-wide text-primary-foreground">MI</span>
          <span className="mi-shell-brand flex min-w-0 flex-col leading-tight">
            <span className="truncate text-[15px] font-semibold">Manufacturing Intelligence</span>
            <span className="text-[10px] font-semibold uppercase tracking-[.14em] text-muted-foreground">Intelligence Platform</span>
          </span>
        </Link>

        <div className="ml-auto flex flex-none items-center gap-1">
          <Link to="/new" className={cn(TOP_ITEM, 'mi-shell-link')}>
            <Plus size={17} strokeWidth={2} className="flex-none" />
            <span className="mi-shell-label">New chat</span>
          </Link>
          <Link to="/history" className={cn(TOP_ITEM, 'mi-shell-link')}>
            <Clock size={16} strokeWidth={1.8} className="flex-none" />
            <span className="mi-shell-label">History</span>
          </Link>
          <button type="button" className={TOP_ICON} aria-label={themeName} title={themeName} aria-pressed={dark} onClick={toggleTheme}>
            {dark ? <Sun size={17} strokeWidth={1.8} /> : <Moon size={17} strokeWidth={1.8} />}
          </button>
          <Popover>
            <PopoverTrigger asChild>
              <button type="button" aria-label="User menu" title={me.name}
                className="ml-1 inline-flex size-9 flex-none items-center justify-center rounded-full bg-primary text-[12.5px] font-bold text-primary-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
                {me.username.slice(0, 2).toUpperCase()}
              </button>
            </PopoverTrigger>
            <PopoverContent align="end" sideOffset={8} portal={false} className="w-56 p-2">
              <div className="px-2.5 pt-1.5 pb-2">
                <div className="truncate text-[13.5px] font-semibold">{me.name}</div>
                <div className="text-[12px] text-muted-foreground">{me.is_staff ? 'Admin' : 'User'}</div>
              </div>
              <div className="border-t border-border pt-1.5">
                <button type="button" onClick={onSignOut}
                  className="flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[13.5px] font-medium transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring">
                  <LogOut size={16} strokeWidth={1.8} className="flex-none" />
                  Sign out
                </button>
              </div>
            </PopoverContent>
          </Popover>
        </div>
      </header>

      <div className="mi-shell-body">
        {/* behind the open phone drawer: a tap on it closes the drawer */}
        {drawer && <div className="mi-shell-backdrop" onClick={() => setDrawer(false)} />}
        <aside id="mi-shell-menu" className="mi-shell-menu gap-4 border-r border-border bg-sidebar px-3 pt-4 pb-3 text-sidebar-foreground">
          <nav aria-label="Main menu" className="flex flex-col gap-4">
            {MENU.filter((group) => !group.staffOnly || me.is_staff).map((group) => (
              <div key={group.name} role="group" aria-labelledby={`mi-shell-group-${group.name}`} className="mi-shell-group border-border">
                <p id={`mi-shell-group-${group.name}`}
                  className="mi-shell-group-name m-0 px-3.5 pb-1.5 text-[11px] font-semibold uppercase tracking-[.1em] text-sidebar-muted">
                  {group.name}
                </p>
                <ul className="m-0 flex list-none flex-col gap-1 p-0">
                  {group.entries.map((entry) => <MenuLink key={entry.item} entry={entry} active={active} slim={slim} />)}
                </ul>
              </div>
            ))}
          </nav>
          <button type="button" onClick={toggleMenu} aria-expanded={!slim}
            aria-label={slim ? 'Open the menu' : 'Make the menu small'} title={slim ? 'Open the menu' : 'Make the menu small'}
            className="mi-shell-slim-toggle mt-auto ml-auto inline-flex size-9 flex-none items-center justify-center rounded-full text-sidebar-muted transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
            {slim ? <ChevronsRight size={17} strokeWidth={1.8} /> : <ChevronsLeft size={17} strokeWidth={1.8} />}
          </button>
        </aside>

        <div className="mi-shell-main">
          {/* the page title (Home has none: its banner has the greeting and the clock) */}
          {header && (
            <div className="mi-shell-title">
              <h1 className="m-0 text-[20px] leading-tight font-semibold text-foreground">{title}</h1>
            </div>
          )}
          <div className="content">{children}</div>
          <footer className="app-foot">
            <span>© {new Date().getFullYear()} Manufacturing Intelligence · demo project with synthetic data</span>
          </footer>
        </div>
      </div>
    </div>
  )
}
