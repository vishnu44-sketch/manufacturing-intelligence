// AiChart: the AI's ECharts option is drawn as data - only the allowed keys, a text-only tooltip - with the
// same ECharts box (a fake here) and Download PNG.
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { charts, lastChart } from '../test/fakeEcharts'
import AiChart, { ALLOWED_KEYS, safeOption } from './AiChart'

vi.mock('./echarts', () => import('../test/fakeEcharts'))
vi.mock('./echartsAi', () => ({}))

afterEach(() => { charts.length = 0 })

const SANKEY = {
  series: [{ type: 'sankey', data: [{ name: 'Domestic' }, { name: 'GCI' }], links: [{ source: 'Domestic', target: 'GCI', value: 14952355 }] }],
  tooltip: { trigger: 'item', renderMode: 'html' },
  graphic: [{ type: 'text', style: { text: 'not allowed' } }],
  toolbox: { feature: { saveAsImage: {} } },
}

describe('safeOption', () => {
  it('keeps only the allowed keys and makes the tooltip text only', () => {
    const option = safeOption(SANKEY, ['#C00000']) as Record<string, any>
    expect(option.graphic).toBeUndefined()
    expect(option.toolbox).toBeUndefined()
    expect(option.series).toEqual(SANKEY.series)
    expect(option.tooltip).toEqual({ trigger: 'item', renderMode: 'richText', confine: true })
    expect(option.color).toEqual(['#C00000'])
  })

  it('adds a text-only tooltip when the AI gave none, and keeps its own colours', () => {
    const option = safeOption({ series: [{ type: 'gauge', data: [{ value: 72 }] }], color: ['#111'] }, ['#C00000']) as Record<string, any>
    expect(option.tooltip).toEqual({ trigger: 'item', renderMode: 'richText', confine: true })
    expect(option.color).toEqual(['#111'])
    expect(ALLOWED_KEYS).toContain('visualMap')
  })
})

describe('AiChart', () => {
  it('draws the option, says it was made by the AI with its tokens, and saves a PNG', () => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    render(<AiChart option={SANKEY} kind="sankey diagram" tokens={1234} recorded />)
    expect(screen.getByRole('img', { name: "A sankey diagram made by the AI from the answer's rows." })).toBeInTheDocument()
    expect(lastChart().types()).toEqual(['sankey'])
    expect(lastChart().option!.graphic).toBeUndefined()
    expect(screen.getByText(/1,234 AI tokens \(added to this question's tokens\)/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Download PNG' }))
    expect(lastChart().getDataURL).toHaveBeenCalledWith({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' })
  })
})
