// The chart colours (03-Nov, Vishnu: no red and no yellow in the charts; 12-Nov: the blue brand first - blue, teal,
// amber, violet ... - in the light and in the dark theme).
import { describe, expect, it } from 'vitest'
import { readColours } from './chartOption'

/** hue in degrees (0-360) of a #rrggbb colour */
function hue(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min
  if (d === 0) return 0
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4
  return (h * 60 + 360) % 360
}
const grey = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
  return Math.max(r, g, b) - Math.min(r, g, b) < 40
}

describe('chart colours', () => {
  it('start with the brand blue, then teal, amber, violet', () => {
    expect(readColours().series.slice(0, 4)).toEqual(['#0B5FB3', '#0D9488', '#D97706', '#7C3AED'])
    expect(readColours('dark').series.slice(0, 4)).toEqual(['#4C9AFF', '#12A594', '#CC7F08', '#9B7BF0'])
  })

  it('have no red and no yellow, in both themes', () => {
    for (const theme of ['light', 'dark'] as const) {
      const { series, low, high, up, down } = readColours(theme)
      for (const colour of [...series, low, high, up, down].filter((c) => !grey(c))) {
        const h = hue(colour)
        expect(h < 15 || h > 345, `${colour} is red`).toBe(false)
        expect(h > 45 && h < 65, `${colour} is yellow`).toBe(false)
      }
    }
  })

  it('each dark colour has the hue of its light one (the same series keeps its colour name)', () => {
    const light = readColours('light').series
    readColours('dark').series.forEach((colour, i) => {
      const apart = Math.abs(hue(colour) - hue(light[i]))
      expect(Math.min(apart, 360 - apart), `${colour} against ${light[i]}`).toBeLessThan(25)
    })
  })

  it('draw the heatmap light blue to dark blue and the waterfall green up, orange down', () => {
    const { low, high, up, down } = readColours()
    expect([low, high]).toEqual(['#E0F2FE', '#1D4ED8'])
    expect([up, down]).toEqual(['#16A34A', '#F97316'])
  })
})
