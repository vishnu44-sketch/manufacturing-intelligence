// The frame of every page: the top bar (brand, New chat, History, dark mode, the user's badge with Sign out),
// the left menu in groups, which can be made small (icons only) and opened again - the choice is kept in this
// browser - and the page title row on every page but Home (header={false}).
import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ASHA, BOSS, renderAt } from '../test/render'
import Shell from './Shell'

afterEach(() => {
  delete document.documentElement.dataset.theme
})

function page(onSignOut = () => {}) {
  return renderAt('/history', <Shell me={ASHA} title="History" active="history" onSignOut={onSignOut}><p>Page</p></Shell>)
}

/** The left menu (the top bar has its own "History" link). */
const menu = () => within(screen.getByRole('navigation', { name: 'Main menu' }))
const topBar = () => within(screen.getByRole('banner'))

describe('Shell: the small menu (04-Nov)', () => {
  it('« makes the menu small, the links keep their names, » opens it again', () => {
    const { container } = page()
    expect(container.querySelector('.mi-shell')).not.toHaveClass('mi-shell-slim')

    fireEvent.click(screen.getByRole('button', { name: 'Make the menu small' }))
    expect(container.querySelector('.mi-shell')).toHaveClass('mi-shell-slim')
    const history = menu().getByRole('link', { name: 'History' })                   // still read out by its name
    expect(history).toHaveAttribute('title', 'History')                             // and shown on hover
    expect(window.localStorage.getItem('mi.menuSlim')).toBe('1')

    fireEvent.click(screen.getByRole('button', { name: 'Open the menu' }))
    expect(container.querySelector('.mi-shell')).not.toHaveClass('mi-shell-slim')
    expect(menu().getByRole('link', { name: 'History' })).not.toHaveAttribute('title')
    expect(window.localStorage.getItem('mi.menuSlim')).toBeNull()
  })

  it('stays small on the next page and after a refresh', () => {
    window.localStorage.setItem('mi.menuSlim', '1')
    const { container } = page()
    expect(container.querySelector('.mi-shell')).toHaveClass('mi-shell-slim')
    expect(screen.getByRole('button', { name: 'Open the menu' })).toHaveAttribute('aria-expanded', 'false')
  })
})

describe('Shell: the menu (05-Nov)', () => {
  it('has Home first (at /) and Ask AI at /ask, also in the small menu', () => {
    window.localStorage.setItem('mi.menuSlim', '1')
    renderAt('/', <Shell me={ASHA} title="Home" active="home" onSignOut={() => {}}><p>Page</p></Shell>)
    const links = menu().getAllByRole('link')
    expect(links[0]).toHaveAccessibleName('Home')
    expect(links[0]).toHaveAttribute('href', '/')
    expect(links[0]).toHaveAttribute('aria-current', 'page')
    expect(links[0]).toHaveAttribute('title', 'Home')                       // the name on hover in the small menu
    expect(links[0].querySelector('svg')).not.toBeNull()
    expect(menu().getByRole('link', { name: 'Ask AI' })).toHaveAttribute('href', '/ask')
    expect(document.title).toBe('Home · Manufacturing Intelligence')
  })

  it('is in groups: Home, Intelligence, Tools - and Administration for staff only (12-Nov)', () => {
    const names = (group: string) => within(menu().getByRole('group', { name: group })).getAllByRole('link').map((a) => a.textContent)
    const first = page()
    expect(menu().getAllByRole('group').map((g) => g.querySelector('p')?.textContent)).toEqual(['Home', 'Intelligence', 'Tools'])
    expect(names('Home')).toEqual(['Home', 'Ask AI'])
    expect(names('Intelligence')).toEqual(['Knowledge graph'])
    expect(names('Tools')).toEqual(['History', 'Memory'])
    expect(menu().getAllByRole('link').filter((a) => a.getAttribute('aria-current') === 'page').map((a) => a.textContent)).toEqual(['History'])
    first.unmount()

    renderAt('/users', <Shell me={BOSS} title="Users" active="users" onSignOut={() => {}}><p>Page</p></Shell>)
    expect(names('Administration')).toEqual(['Users', 'Documents', 'Data', 'Audit'])
    expect(menu().getByRole('link', { name: 'Users' })).toHaveAttribute('aria-current', 'page')
  })
})

describe('Shell: the page title row (06-Nov)', () => {
  it('shows the page title by default', () => {
    const { container } = page()
    expect(screen.getByRole('heading', { level: 1, name: 'History' })).toBeInTheDocument()
    expect(container.querySelector('.mi-shell-title')).toHaveTextContent('History')
  })

  it('header={false} (Home) leaves the title row out, the tab title stays', () => {
    const { container } = renderAt('/', <Shell me={ASHA} title="Home" active="home" onSignOut={() => {}} header={false}><p>Page</p></Shell>)
    expect(container.querySelector('.mi-shell-title')).toBeNull()
    expect(screen.queryByRole('heading', { level: 1 })).not.toBeInTheDocument()
    expect(screen.getByText('Page')).toBeInTheDocument()
    expect(document.title).toBe('Home · Manufacturing Intelligence')
  })
})

describe('Shell: the top bar (12-Nov)', () => {
  it('has the brand, "New chat" to /new and "History" to /history', () => {
    page()
    expect(topBar().getByText('Manufacturing Intelligence')).toBeInTheDocument()
    expect(topBar().getByText('Intelligence Platform')).toBeInTheDocument()
    expect(topBar().getByRole('link', { name: 'New chat' })).toHaveAttribute('href', '/new')
    expect(topBar().getByRole('link', { name: 'History' })).toHaveAttribute('href', '/history')

    fireEvent.click(topBar().getByRole('link', { name: 'New chat' }))
    expect(window.location.pathname).toBe('/new')
  })

  it('the round badge opens a small menu with the name, the role and Sign out', async () => {
    const onSignOut = vi.fn()
    page(onSignOut)
    const badge = screen.getByRole('button', { name: 'User menu' })
    expect(badge).toHaveTextContent('AS')
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument()

    fireEvent.click(badge)
    const signOut = await screen.findByRole('button', { name: 'Sign out' })
    const box = within(signOut.closest('[data-slot="popover-content"]') as HTMLElement)
    expect(box.getByText('Asha')).toBeInTheDocument()
    expect(box.getByText('User')).toBeInTheDocument()

    fireEvent.click(signOut)
    expect(onSignOut).toHaveBeenCalledTimes(1)
  })

  it('the moon button switches to the dark look and back, and the choice is kept', () => {
    page()
    const moon = screen.getByRole('button', { name: 'Dark mode' })
    expect(moon).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(moon)
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(window.localStorage.getItem('mi.theme')).toBe('dark')
    const sun = screen.getByRole('button', { name: 'Light mode' })
    expect(sun).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(sun)
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(screen.getByRole('button', { name: 'Dark mode' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('starts in the dark look when that was chosen before', () => {
    window.localStorage.setItem('mi.theme', 'dark')
    page()
    expect(screen.getByRole('button', { name: 'Light mode' })).toHaveAttribute('aria-pressed', 'true')
  })
})

describe('Shell: the phone drawer (12-Nov)', () => {
  it('the ☰ button opens the menu, the backdrop, Esc and a new page close it', () => {
    const { container } = page()
    const shell = container.querySelector('.mi-shell')
    const burger = screen.getByRole('button', { name: 'Menu' })
    expect(burger).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(burger)
    expect(shell).toHaveClass('mi-shell-drawer-open')
    expect(burger).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(container.querySelector('.mi-shell-backdrop')!)
    expect(shell).not.toHaveClass('mi-shell-drawer-open')

    fireEvent.click(burger)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(shell).not.toHaveClass('mi-shell-drawer-open')

    fireEvent.click(burger)
    fireEvent.click(menu().getByRole('link', { name: 'Memory' }))
    expect(window.location.pathname).toBe('/memory')
    expect(shell).not.toHaveClass('mi-shell-drawer-open')
  })
})
