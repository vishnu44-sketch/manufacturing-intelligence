// The machine drawing in the Home welcome banner: it is inside the banner, only for the eye (aria-hidden), has its
// gears, the pump with its impeller, the pipes with the liquid and the pressure gauge; the gears turn in times that
// match their teeth (so they look meshed) and the movement classes are there only when motion is fine.
import { cleanup, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { renderAt } from '../test/render'
import type { HomeCalendar } from '../types'
import { gearPath, meshTurn } from './HeroFactory'
import HomeHero from './HomeHero'

const CAL: HomeCalendar = { today: '06-Nov-2026', month: 'Nov 2026', month_from: '21-Oct-2026', month_to: '20-Nov-2026',
  fy: '2627', fy_label: 'FY 2026-27' }

/** The banner with the browser saying motion is fine (true) or asking for less (false); returns the drawing. */
function scene(motion: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce') ? !motion : false }))
  renderAt('/', <HomeHero name="Asha" calendar={CAL} loading={false} examples={['Top 5 customers?']} />)
  const banner = screen.getByRole('region', { name: 'Welcome' })
  return { banner, drawing: banner.querySelector('[data-slot="hero-factory"]') as HTMLElement }
}

describe('HeroFactory', () => {
  it('sits inside the banner, hidden from screen readers, and the banner is a container (it hides where narrow)', () => {
    const { banner, drawing } = scene(true)
    expect(banner).toContainElement(drawing)
    expect(drawing).toHaveAttribute('aria-hidden', 'true')
    expect(drawing).toHaveClass('mi-factory')
    expect(banner).toHaveClass('@container')
    expect(drawing.querySelector('svg')).toHaveAttribute('focusable', 'false')
    expect(drawing.querySelectorAll('a, button')).toHaveLength(0)
  })

  it('has three gears, the pump with its impeller, the liquid in and out, and the gauge with its needle', () => {
    const { drawing } = scene(true)
    const gears = [...drawing.querySelectorAll('[data-part="gear"]')]
    expect(gears.map((gear) => gear.getAttribute('data-teeth'))).toEqual(['15', '10', '8'])
    for (const part of ['pump', 'impeller', 'flow-in', 'flow-out', 'gauge', 'gauge-needle', 'status-light']) {
      expect(drawing.querySelector(`[data-part="${part}"]`)).not.toBeNull()
    }
    expect(drawing.querySelector('[data-part="gauge"] [data-part="gauge-needle"]')).not.toBeNull()
    expect(drawing.querySelector('[data-part="pump"] [data-part="impeller"]')).not.toBeNull()
  })

  it('turns the gears in times that go with their teeth: 12 s, 8 s, 6.4 s, the small ones the other way', () => {
    const { drawing } = scene(true)
    const gears = [...drawing.querySelectorAll<HTMLElement>('[data-part="gear"]')]
    expect(gears.map((gear) => gear.getAttribute('data-seconds'))).toEqual(['12', '8', '6.4'])
    expect(gears.map((gear) => gear.style.getPropertyValue('--mi-dir'))).toEqual(['normal', 'reverse', 'reverse'])
    expect(gears[0].style.getPropertyValue('--mi-turn')).toBe('12s')
    const impeller = drawing.querySelector<HTMLElement>('[data-part="impeller"]')!
    expect(impeller.style.getPropertyValue('--mi-turn')).toBe('4s')
  })

  it('has movement classes only when motion is fine; with less motion the drawing is there but still', () => {
    let { drawing } = scene(true)
    expect(drawing.querySelectorAll('.mi-factory-turn')).toHaveLength(4)           // three gears and the impeller
    expect(drawing.querySelectorAll('.mi-factory-flow')).toHaveLength(2)
    expect(drawing.querySelector('[data-part="gauge-needle"]')).toHaveClass('mi-factory-needle', 'mi-factory-sway')
    expect(drawing.querySelector('.mi-factory-bubble')).not.toBeNull()
    expect(drawing.querySelector('.mi-factory-light')).not.toBeNull()
    cleanup()

    ;({ drawing } = scene(false))
    expect(drawing).not.toBeNull()
    expect(drawing.querySelectorAll('[data-part="gear"]')).toHaveLength(3)
    expect(drawing.querySelectorAll('.mi-factory-turn, .mi-factory-flow, .mi-factory-sway, .mi-factory-bubble, .mi-factory-light'))
      .toHaveLength(0)
    expect(drawing.querySelector('[data-part="gauge-needle"]')).toHaveClass('mi-factory-needle')  // still, a little right
  })

  it('draws a gear with one tooth per step and turns a second gear so its teeth sit in the gaps', () => {
    expect(gearPath(10, 20, 4).match(/A/g)).toHaveLength(20)                 // a tip and a gap arc per tooth
    expect(gearPath(10, 20, 4).endsWith('Z')).toBe(true)
    // straight to the right of a gear with a tooth pointing right: the other gear needs a gap facing it
    expect(meshTurn(10, 0, 10, 0)).toBe(18)                                 // half a tooth (36 / 2)
    expect(meshTurn(15, 0, 10, 0)).toBe(18)
    expect(meshTurn(15, 0, 10, -32)).toBeGreaterThanOrEqual(0)
    expect(meshTurn(15, 0, 10, -32)).toBeLessThan(36)
  })
})
