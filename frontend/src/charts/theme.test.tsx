// The charts in the light and the dark theme (12-Nov): the hook that watches <html data-theme>, the colours each
// theme gives (text, grid, tooltip, the line between slices), the answer chart drawn again when the theme changes,
// and the PNG (white in light, the dark card in dark). ECharts is a fake here: the options are checked.
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GraphNode } from '../types'
import { charts, lastChart } from '../test/fakeEcharts'
import AiChart, { safeOption } from './AiChart'
import AnswerChart from './AnswerChart'
import { buildOption, pngPaper, readColours, themeName } from './chartOption'
import { buildGraphOption } from './graphOption'
import { pickChart } from './pickChart'
import { MONTHLY, SALE_TYPES, TOP5 } from './testRows'
import useThemeName from './useThemeName'

vi.mock('./echarts', () => import('../test/fakeEcharts'))
vi.mock('./echartsAi', () => ({}))

const setTheme = (name: 'light' | 'dark' | null) => {
  if (name) document.documentElement.setAttribute('data-theme', name)
  else document.documentElement.removeAttribute('data-theme')
}

afterEach(() => {
  setTheme(null)
  charts.length = 0
})

type Option = Record<string, any>
const optionOf = (t: typeof MONTHLY, theme: 'light' | 'dark') =>
  buildOption(pickChart(t.headers, t.rows, null)!, readColours(theme), false, 0, false).option as Option

describe('useThemeName', () => {
  it('is light without the attribute and follows data-theme as it changes', async () => {
    const { result, unmount } = renderHook(() => useThemeName())
    expect(result.current).toBe('light')
    act(() => setTheme('dark'))
    await waitFor(() => expect(result.current).toBe('dark'))
    act(() => setTheme('light'))
    await waitFor(() => expect(result.current).toBe('light'))
    act(() => setTheme('dark'))
    await waitFor(() => expect(result.current).toBe('dark'))
    act(() => setTheme(null))
    await waitFor(() => expect(result.current).toBe('light'))
    unmount()
  })

  it('themeName and readColours read the attribute', () => {
    expect(themeName()).toBe('light')
    expect(readColours().dark).toBe(false)
    setTheme('dark')
    expect(themeName()).toBe('dark')
    expect(readColours().dark).toBe(true)
    expect(readColours('light').dark).toBe(false) // a theme asked for by name
  })
})

describe('the colours of each theme', () => {
  it('the palette starts with the brand blue in both, with lighter steps on dark', () => {
    const light = readColours('light')
    const dark = readColours('dark')
    expect(light.series[0]).toBe('#0B5FB3')
    expect(dark.series[0]).toBe('#4C9AFF')
    expect(dark.series).toHaveLength(light.series.length)
    light.series.forEach((colour, i) => expect(dark.series[i], `series ${i + 1}`).not.toBe(colour))
    expect(new Set(dark.series).size).toBe(dark.series.length)
  })

  it('takes the first colour from the app\'s --brand variable', () => {
    document.documentElement.style.setProperty('--brand', '#123456')
    try {
      expect(readColours('light').series[0]).toBe('#123456')
    } finally {
      document.documentElement.style.removeProperty('--brand')
    }
  })

  it('dark gives other axis, grid, tooltip and label colours than light', () => {
    const light = optionOf(TOP5, 'light')
    const dark = optionOf(TOP5, 'dark')
    expect(dark.xAxis.axisLabel.color).not.toBe(light.xAxis.axisLabel.color)
    expect(dark.xAxis.splitLine.lineStyle.color).not.toBe(light.xAxis.splitLine.lineStyle.color)
    expect(dark.tooltip.backgroundColor).not.toBe(light.tooltip.backgroundColor)
    expect(dark.tooltip.textStyle.color).not.toBe(light.tooltip.textStyle.color)
    expect(dark.series[0].label.color).not.toBe(light.series[0].label.color)
    expect(light.tooltip.backgroundColor).toBe('#fff')
    expect(dark.tooltip.backgroundColor).toBe(readColours('dark').surface)
    expect(dark.tooltip.textStyle.color).toBe(readColours('dark').ink)
  })

  it('the line\'s dots and the donut\'s slices are edged in the card\'s colour, not white, on dark', () => {
    const surface = readColours('dark').surface
    expect(surface).not.toBe('#fff')
    expect(optionOf(MONTHLY, 'dark').series[0].itemStyle.borderColor).toBe(surface)
    const pie = optionOf(SALE_TYPES, 'dark').series[0]
    expect(pie.itemStyle.borderColor).toBe(surface)
    expect(pie.label.color).toBe(readColours('dark').ink)
    expect(pie.itemStyle.shadowColor).not.toBe(optionOf(SALE_TYPES, 'light').series[0].itemStyle.shadowColor)
    expect(optionOf(SALE_TYPES, 'dark').legend.textStyle.color).toBe(readColours('dark').ink)
  })

  it('the PNG is white in light and the dark card with light text in dark', () => {
    expect(pngPaper()).toEqual({ background: '#fff', ink: '#212529', muted: '#6C757D' })
    expect(pngPaper(readColours('light')).background).toBe('#fff')
    const dark = readColours('dark')
    expect(pngPaper(dark)).toEqual({ background: dark.surface, ink: dark.ink, muted: dark.muted })
  })
})

describe('the Knowledge graph option in each theme', () => {
  const node = (type: GraphNode['type'], key: string, amount: number): GraphNode =>
    ({ id: `${type}:${key}`, type, type_name: type, key, label: key, sub: '', amount, amount_text: String(amount) })
  const data = { nodes: [node('customer', 'a', 100), node('product', 'b', 50)], edges: [] }
  const build = (theme: 'light' | 'dark') =>
    buildGraphOption(data, readColours(theme), { center: 'customer:a' }) as Option

  it('labels, legend, tooltip and rings follow the theme; the node type colours stay', () => {
    const light = build('light')
    const dark = build('dark')
    const ink = readColours('dark').ink
    expect(dark.series[0].label.color).toBe(ink)
    expect(dark.series[0].label.color).not.toBe(light.series[0].label.color)
    expect(dark.legend[0].textStyle.color).not.toBe(light.legend[0].textStyle.color)
    expect(dark.tooltip.backgroundColor).toBe(readColours('dark').surface)
    expect(light.tooltip.backgroundColor).toBe('#fff')
    expect(dark.series[0].select.itemStyle.borderColor).toBe(ink)             // the selected ring: light on dark
    expect(light.series[0].data[0].itemStyle.borderColor).toBe('#fff')         // the middle node's ring
    expect(dark.series[0].data[0].itemStyle.borderColor).toBe(ink)
    expect(dark.series[0].lineStyle.opacity).toBeGreaterThan(light.series[0].lineStyle.opacity)
    expect(dark.series[0].categories).toEqual(light.series[0].categories)
  })
})

describe('AnswerChart and AiChart with the theme', () => {
  it('draws the chart again in the dark colours when the theme changes, and saves a dark PNG', async () => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    render(<AnswerChart headers={TOP5.headers} rows={TOP5.rows} />)
    const chart = lastChart()
    const before = chart.option!
    expect(before.color[0]).toBe('#0B5FB3')
    expect(before.tooltip.backgroundColor).toBe('#fff')

    act(() => setTheme('dark'))
    await waitFor(() => expect(lastChart().option!.color[0]).toBe('#4C9AFF'))
    expect(lastChart()).toBe(chart)                                             // the same chart, a new option
    const dark = readColours('dark')
    expect(chart.option!.tooltip.backgroundColor).toBe(dark.surface)
    expect(chart.option!.xAxis.axisLabel.color).toBe(dark.muted)
    expect(chart.option!.series[0].data).toEqual(before.series[0].data)

    fireEvent.click(screen.getByRole('button', { name: 'Download PNG' }))
    expect(chart.getDataURL).toHaveBeenCalledWith({ type: 'png', pixelRatio: 2, backgroundColor: dark.surface })
  })

  it('the AI chart gets the theme\'s text colours where the AI set none', async () => {
    const raw = { series: [{ type: 'bar', data: [1, 2] }, { type: 'pie', data: [], label: { color: '#123' } }],
      xAxis: { type: 'category', axisLabel: { rotate: 30 } }, yAxis: [{ type: 'value' }], legend: {} }
    const dark = readColours('dark')
    const option = safeOption(raw, dark.series, dark) as Option
    expect(option.textStyle.color).toBe(dark.ink)
    expect(option.xAxis.axisLabel).toEqual({ color: dark.muted, rotate: 30 })  // the AI's own settings stay
    expect(option.yAxis[0].splitLine.lineStyle.color).toBe(dark.line)
    expect(option.legend.textStyle.color).toBe(dark.ink)
    expect(option.tooltip).toMatchObject({ renderMode: 'richText', confine: true, backgroundColor: dark.surface })
    expect(option.series[0].label).toBeUndefined()                             // a bar's labels: left to ECharts
    expect(option.series[1].label.color).toBe('#123')                          // the AI's own colour wins

    render(<AiChart option={raw} kind="bar chart" tokens={null} recorded={false} />)
    expect(lastChart().option!.textStyle.color).toBe(readColours('light').ink)
    act(() => setTheme('dark'))
    await waitFor(() => expect(lastChart().option!.textStyle.color).toBe(dark.ink))
    expect(lastChart().option!.color).toEqual(dark.series)
  })
})
