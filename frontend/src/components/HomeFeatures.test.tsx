// Home's two feature cards: The Assistant and the Knowledge graph - their titles, texts and points, the buttons (links)
// that open /ask and /graph without a page load, the card itself not being a link, and the moving pictures
// hidden from screen readers.
import { fireEvent, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderAt } from '../test/render'
import HomeFeatures from './HomeFeatures'
import featuresSource from './HomeFeatures.tsx?raw'

function card(title: string): HTMLElement {
  const heading = screen.getByRole('heading', { name: title })
  return heading.closest('[data-feature]') as HTMLElement
}

describe('HomeFeatures', () => {
  it('shows the two cards with their text and points', () => {
    renderAt('/', <HomeFeatures />)
    const section = screen.getByRole('region', { name: 'The Assistant and the Knowledge graph' })
    expect(within(section).getAllByRole('heading').map((h) => h.textContent)).toEqual(['Assistant', 'Knowledge graph'])

    const ask = card('Assistant')
    expect(ask).toHaveAttribute('data-feature', 'ask')
    expect(ask).toHaveTextContent('Ask the company data in plain English.')
    expect(ask).toHaveTextContent('every number comes from the database')
    expect(within(within(ask).getByRole('list', { name: 'Assistant: what you get' })).getAllByRole('listitem')
      .map((li) => li.textContent)).toEqual(['Plain English', 'Charts', 'Excel'])

    const graph = card('Knowledge graph')
    expect(graph).toHaveAttribute('data-feature', 'graph')
    expect(graph).toHaveTextContent('See how customers, products, sales people and states are linked.')
    expect(graph).toHaveTextContent('in 2D or 3D')
    expect(within(within(graph).getByRole('list', { name: 'Knowledge graph: what you get' })).getAllByRole('listitem')
      .map((li) => li.textContent)).toEqual(['Links', 'Search any name', '2D / 3D'])
  })

  it('has one button per card, and only the button is a link', () => {
    renderAt('/', <HomeFeatures />)
    expect(within(card('Assistant')).getAllByRole('link')).toHaveLength(1)
    expect(within(card('Knowledge graph')).getAllByRole('link')).toHaveLength(1)
    expect(card('Assistant').tagName).not.toBe('A')
    expect(screen.getByRole('link', { name: 'Open the Assistant' })).toHaveAttribute('href', '/ask')
    expect(screen.getByRole('link', { name: 'Open Knowledge graph' })).toHaveAttribute('href', '/graph')
  })

  it('"Open the Assistant" opens the Ask page without a page load', () => {
    renderAt('/', <HomeFeatures />)
    fireEvent.click(screen.getByRole('link', { name: 'Open the Assistant' }))
    expect(window.location.pathname).toBe('/ask')
  })

  it('"Open Knowledge graph" opens the graph page without a page load', () => {
    renderAt('/', <HomeFeatures />)
    fireEvent.click(screen.getByRole('link', { name: 'Open Knowledge graph' }))
    expect(window.location.pathname).toBe('/graph')
  })

  it('Assistant is in the blue brand and the Knowledge graph in teal, so the two differ', () => {
    renderAt('/', <HomeFeatures />)
    const ask = screen.getByRole('link', { name: 'Open the Assistant' })
    const graph = screen.getByRole('link', { name: 'Open Knowledge graph' })
    expect(ask).toHaveClass('bg-primary', 'text-primary-foreground!')
    expect(graph).toHaveClass('bg-teal-700', 'dark:bg-teal-600')
    expect(graph).not.toHaveClass('bg-primary')
  })

  it('hides the moving pictures and the icons from screen readers', () => {
    const { container } = renderAt('/', <HomeFeatures />)
    const ask = container.querySelector('.hf-ask')
    const graph = container.querySelector('svg.hf-graph')
    expect(ask).toHaveAttribute('aria-hidden', 'true')
    expect(graph).toHaveAttribute('aria-hidden', 'true')
    expect(ask?.querySelectorAll('.hf-bubble span')).toHaveLength(3)   // the three typing dots
    expect(ask?.querySelectorAll('.hf-bars span')).toHaveLength(4)     // the bars
    expect(graph?.querySelectorAll('line')).toHaveLength(7)
    expect(graph?.querySelectorAll('circle')).toHaveLength(6)
    // every svg in the section is decoration
    container.querySelectorAll('svg').forEach((svg) => expect(svg).toHaveAttribute('aria-hidden', 'true'))
  })
})

const SOURCES: [string, string][] = [['HomeFeatures.tsx', featuresSource]]

describe('Feature card colours (light and dark)', () => {
  it.each(SOURCES)('%s has no bg-white and no fixed #hex text colour', (_name, source) => {
    expect(source).not.toMatch(/\bbg-white(?![/\w-])/)       // bg-white/15 (glass on the blue banner / card) is fine
    expect(source).not.toMatch(/\btext-\[#/)
    expect(source).not.toMatch(/var\(--(red2?|red-bg|charcoal|purple|purple-bg)\)/)   // the old brand variables
    expect(source).not.toContain('danger-soft')              // red is only for errors now: destructive
  })
})
