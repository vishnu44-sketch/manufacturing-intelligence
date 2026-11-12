// AnswerChart: the chart drawn from the rows (ECharts is a fake here - jsdom has no canvas - so the tests check
// the option it gets), the kind asked for (no chart-type menu), the Chart / Table toggle, Download PNG, and
// nothing for rows that get no chart.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { charts, lastChart } from '../test/fakeEcharts'
import AnswerChart, { describe as describeChart } from './AnswerChart'
import { buildOption, chartSubtitle, labelFits, percent, readColours } from './chartOption'
import { pickChart, shortIndian } from './pickChart'
import { CATEGORY_SALE_TYPE, MONTHLY, SALE_TYPES, TOP5, table } from './testRows'

vi.mock('./echarts', () => import('../test/fakeEcharts'))

afterEach(() => { charts.length = 0 })

describe('AnswerChart', () => {
  it('draws monthly sales as a line with a describing label', () => {
    render(<AnswerChart headers={MONTHLY.headers} rows={MONTHLY.rows} title="Net sales by month" />)
    const chart = screen.getByRole('img', { name: /line chart of net_sales_inr by month, 15 points from jan 2026 to mar 2027/i })
    expect(chart).toHaveAccessibleName(/highest Mar 2027 3,503,352,034.65/)
    expect(screen.getByText('Net sales by month')).toBeInTheDocument()
    const option = lastChart().option!
    expect(lastChart().types()).toEqual(['line'])
    expect(option.xAxis.data).toHaveLength(15)
    expect(option.series[0].data[0]).toBe(13356235)
    // Indian short numbers on the axis, the full value in the tooltip
    expect(option.yAxis.axisLabel.formatter(13356235)).toBe('1.3 Cr')
    expect(option.tooltip.formatter([{ dataIndex: 0 }])).toContain('13,356,235.00')
  })

  it('draws the top customers as bars and sale types as a donut', () => {
    const bars = render(<AnswerChart headers={TOP5.headers} rows={TOP5.rows} />)
    expect(screen.getByRole('img', { name: /^bar chart of invoice_value_inr by customer_name, 5 bars/i })).toBeInTheDocument()
    expect(lastChart().types()).toEqual(['bar'])
    expect(lastChart().option!.series[0].data).toHaveLength(5)
    expect(lastChart().option!.yAxis.type).toBe('category') // long names: bars run left to right
    bars.unmount()

    render(<AnswerChart headers={SALE_TYPES.headers} rows={SALE_TYPES.rows} />)
    expect(screen.getByRole('img', { name: 'Donut chart of net_sales_inr by sale_type: Domestic 70%, Export 28%, Service 2%.' }))
      .toBeInTheDocument()
    const pie = lastChart().option!
    expect(pie.series[0].type).toBe('pie')
    expect(pie.legend.formatter('Domestic')).toBe('Domestic · 70%')
  })

  it('the Table button calls onShowTable', () => {
    const onShowTable = vi.fn()
    render(<AnswerChart headers={TOP5.headers} rows={TOP5.rows} onShowTable={onShowTable} />)
    expect(screen.getByRole('button', { name: 'Chart' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Table' }))
    expect(onShowTable).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Download PNG' })).toBeEnabled()
  })

  it('Download PNG saves the chart ECharts drew (getDataURL)', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    render(<AnswerChart headers={TOP5.headers} rows={TOP5.rows} />)
    fireEvent.click(screen.getByRole('button', { name: 'Download PNG' }))
    expect(lastChart().getDataURL).toHaveBeenCalledWith({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' })
    await waitFor(() => expect(click).toHaveBeenCalled())
    expect(screen.getByRole('button', { name: 'Download PNG' })).toBeEnabled()
  })

  it('Download PNG of a chart still growing in waits until it is drawn in full', () => {
    vi.useFakeTimers()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    window.matchMedia = ((query: string) => ({ matches: !query.includes('reduce') })) as unknown as typeof window.matchMedia
    try {
      render(<AnswerChart headers={TOP5.headers} rows={TOP5.rows} />)
      expect(lastChart().option!.animation).toBe(true)
      fireEvent.click(screen.getByRole('button', { name: 'Download PNG' }))
      expect(lastChart().getDataURL).not.toHaveBeenCalled()
      vi.advanceTimersByTime(1000)
      expect(lastChart().getDataURL).toHaveBeenCalledWith({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' })
    } finally {
      delete (window as Partial<Window>).matchMedia
      vi.useRealTimers()
    }
  })

  it('has no toggle without onShowTable, and notes when only the top 25 are drawn', () => {
    const rows = Array.from({ length: 30 }, (_, i) => [`Customer ${i + 1}`, `${(30 - i) * 1000}.00`])
    const many = table([['customer_name', false], ['sales_inr', true]], rows)
    render(<AnswerChart headers={many.headers} rows={many.rows} />)
    expect(screen.queryByRole('button', { name: 'Table' })).toBeNull()
    expect(screen.getByText(/Showing the top 25 of 30 rows/)).toBeInTheDocument()
    expect(lastChart().option!.series[0].data).toHaveLength(25)
  })

  it('renders nothing for rows that get no chart', () => {
    const one = table([['total_sales_inr', true]], [['3,503,352,034.65']])
    const { container } = render(<AnswerChart headers={one.headers} rows={one.rows} onShowTable={() => {}} />)
    expect(container).toBeEmptyDOMElement()
    expect(charts).toHaveLength(0)
  })

  it('describes negative bars too', () => {
    const t = table([['document_type', false], ['amount_inr', true]], [['INVOICE', '1,000.00'], ['CREDIT_NOTE', '-250.50']])
    const pick = pickChart(t.headers, t.rows)
    expect(pick && describeChart(pick)).toBe('Bar chart of amount_inr by document_type, 2 bars, highest INVOICE 1,000.00.')
  })

  it('never draws the helper columns (data_from, period_start ...)', () => {
    render(<AnswerChart headers={MONTHLY.headers} rows={MONTHLY.rows} />)
    const text = JSON.stringify(lastChart().option)
    expect(text).not.toContain('21-Dec-2025')
    expect(text).not.toContain('period_start')
  })
})

describe('AnswerChart chart kind (no chart-type menu)', () => {
  const noKindChoice = () => {
    expect(screen.queryByRole('combobox', { name: 'Chart type' })).not.toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Chart type' })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    for (const name of ['Line', 'Bar', 'Area', 'Donut', 'Treemap']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
  }

  it('renders no "Chart type" menu or buttons, even when the rows fit many kinds or only a few', () => {
    const many = render(<AnswerChart headers={TOP5.headers} rows={TOP5.rows} onShowTable={() => {}} />)
    noKindChoice()
    // the Chart / Table toggle and Download PNG stay
    expect(screen.getByRole('group', { name: 'Show the answer as' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Download PNG' })).toBeInTheDocument()
    many.unmount()
    const t = table([['month', false], ['net_sales_inr', true]], [['Jan 2026', '-5.00'], ['Feb 2026', '3.00']])
    render(<AnswerChart headers={t.headers} rows={t.rows} />)
    noKindChoice()
  })

  it('a line chart asked for draws a line chart only', () => {
    render(<AnswerChart headers={TOP5.headers} rows={TOP5.rows} kind="line" />)
    expect(screen.getByRole('img', { name: /^Line chart/ })).toBeInTheDocument()
    expect(lastChart().types()).toEqual(['line'])
    expect(charts).toHaveLength(1)
    noKindChoice()
  })

  it('a bar chart asked for draws bars (months too, which would be a line by default)', () => {
    render(<AnswerChart headers={MONTHLY.headers} rows={MONTHLY.rows} kind="bar" />)
    expect(screen.getByRole('img', { name: /^Bar chart/ })).toBeInTheDocument()
    expect(lastChart().types()).toEqual(['bar'])
    noKindChoice()
  })

  it('no kind asked: the best kind for the rows', () => {
    const months = render(<AnswerChart headers={MONTHLY.headers} rows={MONTHLY.rows} />)
    expect(lastChart().types()).toEqual(['line'])
    months.unmount()
    const top = render(<AnswerChart headers={TOP5.headers} rows={TOP5.rows} />)
    expect(lastChart().types()).toEqual(['bar'])
    top.unmount()
    render(<AnswerChart headers={SALE_TYPES.headers} rows={SALE_TYPES.rows} />)
    expect(lastChart().types()).toEqual(['pie'])
    noKindChoice()
  })

  it('an asked kind the rows cannot be drawn as: the best kind, with a note why', () => {
    render(<AnswerChart headers={MONTHLY.headers} rows={MONTHLY.rows} kind="pie" />)
    expect(screen.getByRole('status')).toHaveTextContent('A donut needs up to 12 positive parts of one amount - showing a line.')
    expect(screen.getByRole('img', { name: /^Line chart/ })).toBeInTheDocument()
    expect(lastChart().types()).toEqual(['line'])
    noKindChoice()
  })
})

describe('AnswerChart pivot (product category x sale type)', () => {
  it('draws stacked bars by default: one series per sale type, a missing pair empty', () => {
    render(<AnswerChart headers={CATEGORY_SALE_TYPE.headers} rows={CATEGORY_SALE_TYPE.rows} />)
    // Not classified (97% of the total) is hidden at first: the other 7 categories can be compared
    expect(screen.getByRole('img', { name: /^Stacked bar chart of net_sales_inr by product_category and sale_type, 7 bars, highest Trochoid pumps Domestic 21,369,867.50/ }))
      .toBeInTheDocument()
    let option = lastChart().option!
    expect(option.series.map((s: { name: string }) => s.name)).toEqual(['Domestic', 'Export']) // Service was only Not classified's
    expect(option.tooltip.formatter([{ dataIndex: 5 }])).toContain('21,369,867.50')

    // shown again: one group holds 97%, so the bars are sorted biggest first
    fireEvent.click(screen.getByRole('button', { name: 'Show Not classified' }))
    expect(screen.getByRole('img', { name: /^Stacked bar chart of net_sales_inr by product_category and sale_type, 8 bars, highest Not classified Domestic 3,314,096,846.50/ }))
      .toBeInTheDocument()
    option = lastChart().option!
    expect(option.series.map((s: { name: string; stack: string }) => [s.name, s.stack]))
      .toEqual([['Domestic', 'total'], ['Export', 'total'], ['Service', 'total']])
    expect(option.yAxis.data.slice(0, 3)).toEqual(['Not classified', 'Trochoid pumps', 'Coolant pumps'])
    expect(option.series[2].data).toEqual([871750, null, null, null, null, null, null, null])
    expect(option.legend).toBeTruthy()
    expect(option.tooltip.formatter([{ dataIndex: 0 }])).toContain('667,910,761.50')
  })

  it('"Treemap" draws a nested treemap: a box per category, inside it a box per sale type', () => {
    render(<AnswerChart headers={CATEGORY_SALE_TYPE.headers} rows={CATEGORY_SALE_TYPE.rows} kind="treemap" />)
    expect(screen.getByRole('img', { name: /^Treemap of net_sales_inr by product_category and sale_type, 7 boxes/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show it' }))
    expect(screen.getByRole('img', { name: /^Treemap of net_sales_inr by product_category and sale_type, 8 boxes/ })).toBeInTheDocument()
    const [series] = lastChart().option!.series
    expect(series.type).toBe('treemap')
    expect(series.data).toHaveLength(8)
    expect(series.data[4].name).toBe('Not classified')
    expect(series.data[4].children.map((c: { name: string; value: number }) => [c.name, c.value]))
      .toEqual([['Domestic', 3314096846.5], ['Export', 667910761.5], ['Service', 871750]])
    expect(series.data[0].children).toHaveLength(2) // no Service for Coolant pumps
  })

  it('draws a heatmap and a radar when the question asks for one', () => {
    const heatmap = render(<AnswerChart headers={CATEGORY_SALE_TYPE.headers} rows={CATEGORY_SALE_TYPE.rows} kind="heatmap" />)
    let heat = lastChart().option!
    expect(heat.series[0].type).toBe('heatmap')
    expect(heat.series[0].data).toHaveLength(14) // the pairs of the 7 categories shown
    expect(heat.yAxis.data).toHaveLength(7)
    fireEvent.click(screen.getByRole('button', { name: 'Show Not classified' }))
    heat = lastChart().option!
    expect(heat.series[0].data).toHaveLength(17) // the pairs the rows have
    expect(heat.xAxis.data).toEqual(['Domestic', 'Export', 'Service'])
    expect(heat.yAxis.data).toHaveLength(8)
    expect(screen.getByRole('img', { name: /^Heatmap of net_sales_inr by product_category and sale_type, 8 rows by 3 columns/ }))
      .toBeInTheDocument()
    heatmap.unmount()
    render(<AnswerChart headers={CATEGORY_SALE_TYPE.headers} rows={CATEGORY_SALE_TYPE.rows} kind="radar" />)
    expect(lastChart().types()).toEqual(['radar'])
    expect(lastChart().option!.radar.indicator).toHaveLength(7) // Not classified hidden at first
    fireEvent.click(screen.getByRole('button', { name: 'Show Not classified' }))
    expect(lastChart().option!.radar.indicator).toHaveLength(8)
  })
})

describe('buildOption', () => {
  const colours = readColours()

  it('a waterfall: invisible bases, the steps and the total', () => {
    const t = table([['document_type', false], ['amount_inr', true]],
      [['INVOICE', '1,000.00'], ['CREDIT_NOTE', '-250.00'], ['DEBIT_NOTE', '50.00']])
    const pick = pickChart(t.headers, t.rows, 'waterfall')!
    const { option } = buildOption(pick, colours, false) as { option: Record<string, any> }
    expect(option.xAxis.data).toEqual(['INVOICE', 'CREDIT_NOTE', 'DEBIT_NOTE', 'Total'])
    expect(option.series[0].data).toEqual([0, 750, 750, 0])
    expect(option.series[1].data.map((d: { value: number }) => d.value)).toEqual([1000, 250, 50, 800])
    expect(describeChart(pick)).toBe('Waterfall chart of amount_inr by document_type, 3 steps, total 800.00.')
  })

  it('a scatter: one dot per row, both values in the tooltip', () => {
    const t = table([['product_name', false], ['qty_sold', true], ['net_sales_inr', true]],
      [['Pump A', '10', '5,000.00'], ['Pump B', '40', '9,000.00'], ['Pump C', '25', '12,500.00']])
    const pick = pickChart(t.headers, t.rows, 'scatter')!
    const { option } = buildOption(pick, colours, false) as { option: Record<string, any> }
    expect(option.series[0].data[1]).toEqual({ name: 'Pump B', value: [9000, 40], i: 1 })
    const tip = option.tooltip.formatter({ data: option.series[0].data[1] })
    expect(tip).toContain('9,000.00')
    expect(tip).toContain('>40<')
  })

  it('escapes names in the tooltip', () => {
    const t = table([['customer_name', false], ['sales_inr', true]], [['<b>A&B</b>', '1.00'], ['C', '2.00']])
    const { option } = buildOption(pickChart(t.headers, t.rows, 'bar')!, colours, false) as { option: Record<string, any> }
    expect(option.tooltip.formatter([{ dataIndex: 0 }])).toContain('&lt;b&gt;A&amp;B&lt;/b&gt;')
  })

  it('a phone gets smaller bars that run left to right', () => {
    const t = table([['sale_type', false], ['amount_inr', true]],
      Array.from({ length: 8 }, (_, i) => [`T${i}`, `${i + 1}.00`]))
    const pick = pickChart(t.headers, t.rows, 'bar')!
    expect((buildOption(pick, colours, false).option as Record<string, any>).xAxis.type).toBe('category')
    expect((buildOption(pick, colours, true).option as Record<string, any>).yAxis.type).toBe('category')
    expect(shortIndian(800)).toBe('800')
  })
})

describe('AnswerChart with a catch-all group (Not classified)', () => {
  const P = CATEGORY_SALE_TYPE
  const NOTE = 'Not classified (398 Cr, 97% of the total) is hidden so the other categories can be compared -'

  it('hides it at first with a note, says so to screen readers, and "Show it" brings it back', () => {
    render(<AnswerChart headers={P.headers} rows={P.rows} kind="treemap" />)
    expect(screen.getByText(NOTE, { exact: false })).toBeInTheDocument()
    const chart = screen.getByRole('img', { name: /^Treemap of net_sales_inr by product_category and sale_type, 7 boxes/ })
    expect(chart).toHaveAccessibleName(/ Not classified \(398 Cr, 97% of the total\) is hidden\.$/)
    expect(JSON.stringify(lastChart().option!.series[0].data)).not.toContain('Not classified')

    fireEvent.click(screen.getByRole('button', { name: 'Show it' }))
    expect(screen.queryByText(NOTE, { exact: false })).not.toBeInTheDocument()
    expect(screen.getByRole('img', { name: /8 boxes/ })).not.toHaveAccessibleName(/is hidden/)
    expect(lastChart().option!.series[0].data[4].name).toBe('Not classified')
    // the toolbar button turns it off again
    fireEvent.click(screen.getByRole('button', { name: 'Hide Not classified' }))
    expect(screen.getByRole('img', { name: /7 boxes/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show Not classified' })).toBeInTheDocument()
  })

  it('the PNG names the hidden group under the title', () => {
    const pick = pickChart(P.headers, P.rows)!
    expect(chartSubtitle(pick)).toBe('Not classified (398 Cr, 97% of the total) is hidden.')
    expect(chartSubtitle(pickChart(P.headers, P.rows, null, false)!)).toBe('')
    expect(describeChart(pick)).toMatch(
      /^Stacked bar chart of .*, 7 bars, highest Trochoid pumps Domestic 21,369,867.50\. Not classified \(398 Cr, 97% of the total\) is hidden\.$/)
  })

  it('has the Hide / Show button only when a catch-all group exists', () => {
    const top = render(<AnswerChart headers={TOP5.headers} rows={TOP5.rows} />)
    expect(screen.queryByRole('button', { name: /^(Hide|Show) / })).not.toBeInTheDocument()
    top.unmount()
    // a small "Others" (25%): drawn at first, the button can hide it
    const t = table([['region', false], ['net_sales_inr', true]], [['North', '40.00'], ['South', '35.00'], ['Others', '25.00']])
    render(<AnswerChart headers={t.headers} rows={t.rows} />)
    expect(screen.queryByText(/is hidden/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Hide Others' }))
    expect(screen.getByText('Others (25, 25% of the total) is hidden so the other categories can be compared -', { exact: false }))
      .toBeInTheDocument()
    expect(lastChart().option!.series[0].data).toEqual([{ name: 'North', value: 40 }, { name: 'South', value: 35 }])
  })
})

describe('buildOption: labels that stay readable', () => {
  const colours = readColours()
  const P = CATEGORY_SALE_TYPE

  it('the treemap drills down on a click, with a breadcrumb back to "All"', () => {
    const built = buildOption(pickChart(P.headers, P.rows, 'treemap')!, colours, false, 900)
    const [series] = (built.option as Record<string, any>).series
    expect(series).toMatchObject({ name: 'All', nodeClick: false, leafDepth: 2, breadcrumb: { show: true } })
    const chart = { dispatchAction: vi.fn() } as any
    built.onClick!({ data: series.data[5].children[0] }, chart) // Trochoid pumps · Domestic
    expect(chart.dispatchAction).toHaveBeenCalledWith({ type: 'treemapRootToNode', seriesIndex: 0, targetNodeId: 'c5' })
    built.onClick!({ data: series.data[2] }, chart) // the GCI band
    expect(chart.dispatchAction).toHaveBeenLastCalledWith({ type: 'treemapRootToNode', seriesIndex: 0, targetNodeId: 'c2' })
    built.onClick!({ selfType: 'breadcrumb' }, chart) // the breadcrumb does its own
    expect(chart.dispatchAction).toHaveBeenCalledTimes(2)
    // one amount (not nested): no drill-down
    const flat = buildOption(pickChart(SALE_TYPES.headers, SALE_TYPES.rows, 'treemap')!, colours, false)
    expect((flat.option as Record<string, any>).series[0].breadcrumb.show).toBe(false)
    expect(flat.onClick).toBeUndefined()
  })

  it('the click on the drawn treemap goes through EChart', () => {
    render(<AnswerChart headers={P.headers} rows={P.rows} kind="treemap" />)
    const fake = lastChart()
    const [, handler] = fake.on.mock.calls.find(([name]) => name === 'click')!
    handler({ data: fake.option!.series[0].data[0] })
    expect(fake.dispatchAction).toHaveBeenCalledWith({ type: 'treemapRootToNode', seriesIndex: 0, targetNodeId: 'c0' })
  })

  it('treemap boxes: name / amount / % of the shown total, and no label in a box too small for it', () => {
    const { option } = buildOption(pickChart(P.headers, P.rows, 'treemap')!, colours, false, 900) as { option: Record<string, any> }
    const [series] = option.series
    // Trochoid pumps Domestic is 16% of the 7 categories shown (13.1 Cr)
    expect(series.label.formatter({ name: 'Domestic', value: 21369867.5 })).toBe('Domestic\n2.1 Cr\n16%')
    expect(series.levels[1].upperLabel.formatter({ name: 'Trochoid pumps', value: 24431712.5 })).toBe('Trochoid pumps   2.4 Cr · 19%')
    const layout = series.labelLayout
    expect(layout({ dataIndex: 3, rect: { width: 200, height: 120 }, text: 'Domestic\n2.1 Cr\n16%' })).toEqual({})
    expect(layout({ dataIndex: 3, rect: { width: 30, height: 120 }, text: 'Export\n24.6 L\n1.9%' })).toEqual({ fontSize: 0 })
    expect(layout({ dataIndex: 3, rect: { width: 200, height: 20 }, text: 'Export\n24.6 L\n1.9%' })).toEqual({ fontSize: 0 })
    expect(layout({ rect: { width: 28, height: 22 }, text: 'All' })).toEqual({}) // the breadcrumb is left alone
    // the tooltip: the full name, the amount as the table shows it, the %
    const tip = series.data[5].children[0].tip
    expect(tip).toContain('Trochoid pumps · Domestic')
    expect(tip).toContain('21,369,867.50')
    expect(tip).toContain('16% of the shown total')
    expect(series.data[5].tip).toContain('24,431,712.50') // the category's total
    expect(series.data[5].tip).toContain('19% of the shown total')
  })

  it('labelFits: one line high at least, as wide as the lines that fit (a long name may end in "…")', () => {
    expect(labelFits({ width: 120, height: 60 }, 'Domestic\n2.1 Cr\n16%')).toBe(true)
    expect(labelFits({ width: 120, height: 20 }, 'Domestic\n2.1 Cr\n16%')).toBe(false) // not one line high
    expect(labelFits({ width: 40, height: 200 }, 'Export\n2.1 Cr\n16%')).toBe(false) // only "Ex" would fit
    expect(labelFits({ width: 60, height: 30 }, 'Hydraulic motors\n1.8 Cr\n14%')).toBe(true) // "Hydrau…"
    expect(percent(96.82)).toBe('97%')
    expect(percent(4.567)).toBe('4.6%')
    expect(percent(0.02)).toBe('<0.1%')
  })

  it('a donut shows the name and % beside its slices, a heatmap tilts names that do not fit', () => {
    const { option } = buildOption(pickChart(SALE_TYPES.headers, SALE_TYPES.rows)!, colours, false) as { option: Record<string, any> }
    expect(option.series[0].label.show).toBe(true)
    expect(option.series[0].label.formatter({ dataIndex: 0 })).toBe('Domestic\n70%')
    expect(option.series[0].minShowLabelAngle).toBeGreaterThan(0) // small slices: the legend
    expect(option.legend.formatter('Service')).toBe('Service · 2.1%')

    const wide = table([['region', false], ['customer_name', false], ['net_sales_inr', true]],
      ['North', 'South'].flatMap((r) => Array.from({ length: 8 }, (_, i) => [r, `Customer number ${i + 1}`, `${i + 1}.00`])))
    const pick = pickChart(wide.headers, wide.rows, 'heatmap')!
    const phone = buildOption(pick, colours, true, 360).option as Record<string, any>
    expect(phone.xAxis.axisLabel.rotate).toBe(45)
    expect(phone.xAxis.axisLabel.formatter('Customer number 1')).toBe('Customer nu…')
    const real = buildOption(pickChart(P.headers, P.rows, 'heatmap')!, colours, false, 900).option as Record<string, any>
    expect(real.xAxis.axisLabel.rotate).toBe(0) // Domestic / Export fit side by side
  })
})
