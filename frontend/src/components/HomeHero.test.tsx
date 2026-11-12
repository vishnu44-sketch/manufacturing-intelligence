// The Home welcome banner: the greeting, the India-time clock inside it (changing every minute), the NOP month and
// FY badges (no separate date badge: the clock has the date), no big buttons (the feature cards below have them),
// the quick start opening the Ask page with the question, and the movement only when motion is fine.
import { act, cleanup, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderAt } from '../test/render'
import type { HomeCalendar } from '../types'
import heroSource from './HomeHero.tsx?raw'
import HomeHero from './HomeHero'

const CAL: HomeCalendar = { today: '06-Nov-2026', month: 'Nov 2026', month_from: '21-Oct-2026', month_to: '20-Nov-2026',
  fy: '2627', fy_label: 'FY 2026-27' }
const EXAMPLES = ['Top 5 customers?', 'Open orders?']

function hero(props: Partial<Parameters<typeof HomeHero>[0]> = {}) {
  renderAt('/', <HomeHero name="Asha" calendar={CAL} loading={false} examples={EXAMPLES} {...props} />)
  return screen.getByRole('region', { name: 'Welcome' })
}

/** The browser says motion is fine (true) or asks for less (false). */
function motion(ok: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce') ? !ok : false }))
}

afterEach(() => { vi.useRealTimers() })

describe('HomeHero', () => {
  it('greets by name and shows the NOP month and FY badges, without a separate date badge', () => {
    const banner = hero()
    expect(within(banner).getByRole('heading', { name: /^Good (morning|afternoon|evening), Asha/ })).toBeInTheDocument()
    expect(within(banner).getByText(/Ask the company data a question in plain English/)).toBeInTheDocument()
    const today = within(banner).getByRole('list', { name: 'Today' })
    expect(within(today).getAllByRole('listitem')).toHaveLength(2)
    expect(within(today).getByText('NOP sales month Nov 2026 · 21-Oct-2026 to 20-Nov-2026')).toHaveAttribute('data-slot', 'badge')
    expect(within(today).getByText('FY 2026-27')).toHaveAttribute('data-slot', 'badge')
  })

  it('has a live India-time clock inside the banner, changing when the minute changes', () => {
    vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] })
    vi.setSystemTime(new Date('2026-11-06T05:26:30Z'))                      // 10:56:30 AM in India

    const banner = hero()
    const clock = banner.querySelector('[data-slot="hero-clock"]') as HTMLElement
    expect(clock).toHaveTextContent('Friday, 06 November 2026 · 10:56 AM IST')

    act(() => { vi.advanceTimersByTime(30000) })                             // the next minute starts
    expect(clock).toHaveTextContent('Friday, 06 November 2026 · 10:57 AM IST')
    act(() => { vi.advanceTimersByTime(60000) })                             // and the one after
    expect(clock).toHaveTextContent('Friday, 06 November 2026 · 10:58 AM IST')
  })

  it('has no Assistant / Knowledge graph buttons: its only links are the example questions', () => {
    const banner = hero()
    expect(within(banner).queryByRole('link', { name: 'Assistant' })).not.toBeInTheDocument()
    expect(within(banner).queryByRole('link', { name: 'Knowledge graph' })).not.toBeInTheDocument()
    expect(within(banner).getAllByRole('link').map((link) => link.textContent)).toEqual(EXAMPLES)
  })

  it('the quick start opens the Ask page with the question in its box', () => {
    const banner = hero()
    expect(within(banner).getByText('Try a question')).toBeInTheDocument()
    expect(within(banner).getByRole('link', { name: 'Top 5 customers?' })).toHaveAttribute('href', '/new?q=Top%205%20customers%3F')
    fireEvent.click(within(banner).getByRole('link', { name: 'Open orders?' }))
    expect(window.location.pathname + window.location.search).toBe('/new?q=Open%20orders%3F')
  })

  it('shows a skeleton while loading, nothing for the month without a calendar, no quick start without examples', () => {
    let banner = hero({ loading: true, calendar: null })
    expect(within(banner).getByRole('list', { name: 'Today' }).querySelector('[data-slot="skeleton"]')).not.toBeNull()
    cleanup()

    banner = hero({ calendar: null, examples: [] })
    expect(within(banner).queryByRole('list', { name: 'Today' })).not.toBeInTheDocument()
    expect(within(banner).queryByText('Try a question')).not.toBeInTheDocument()
    expect(banner.querySelector('[data-slot="hero-clock"]')).toHaveTextContent(/IST$/)      // the clock is always there
  })

  it('moves only when motion is fine: less motion asked for, no movement class at all', () => {
    motion(false)
    let banner = hero()
    expect(banner).toHaveAttribute('data-motion', 'off')
    expect(banner).not.toHaveClass('mi-hero-motion')
    expect(document.querySelector('.mi-hero-motion')).toBeNull()
    cleanup()

    motion(true)
    banner = hero()
    expect(banner).toHaveAttribute('data-motion', 'on')
    expect(banner).toHaveClass('mi-hero-motion')
    expect(banner.querySelector('.mi-hero-wave')).toHaveTextContent('👋')
    expect(banner.querySelectorAll('.mi-hero-orb')).toHaveLength(3)
  })
})

describe('Banner colours (light and dark)', () => {
  it('is a blue to deep navy banner with a thin border in dark mode', () => {
    const banner = hero()
    expect(banner.className).toContain('bg-[linear-gradient(118deg,#0B5FB3_0%')
    expect(banner.className).toContain('#081626_100%')
    expect(banner).toHaveClass('text-white', 'dark:border', 'dark:border-white/10')
  })

  it('has no red left: no old brand variables, no fixed text colours', () => {
    expect(heroSource).not.toMatch(/var\(--(red2?|charcoal)\)/)
    expect(heroSource).not.toMatch(/\bbg-white(?![/\w-])/)
    expect(heroSource).not.toMatch(/\btext-\[#/)
  })
})
