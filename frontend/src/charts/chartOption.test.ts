// chartOption: the names written for people, the short money in the tooltip, and the "3D" look of the
// answer charts (line fade + last value, rounded shiny bars with few labels, the donut's shadow and lift, the
// grow-in animation that reduced motion switches off). ECharts is not drawn here: the option is checked.
import { describe, expect, it } from 'vitest'
import { buildOption, fade, friendlyName, isMoney, readColours, shortValue, tipValue } from './chartOption'
import { pickChart } from './pickChart'
import { CATEGORY_SALE_TYPE, MONTHLY, SALE_TYPES, TOP5, table } from './testRows'

type Option = Record<string, any>
const colours = readColours()
const optionOf = (t: ReturnType<typeof table>, kind: Parameters<typeof pickChart>[2] = null, narrow = false, animate = false) =>
  buildOption(pickChart(t.headers, t.rows, kind)!, colours, narrow, 0, animate).option as Option

describe('friendlyName', () => {
  it('writes column names for people', () => {
    expect(friendlyName('sales_inr')).toBe('Sales (INR)')
    expect(friendlyName('net_sales_inr')).toBe('Net sales (INR)')
    expect(friendlyName('top_customer_sales_inr')).toBe('Top customer sales (INR)')
    expect(friendlyName('qty')).toBe('Quantity')
    expect(friendlyName('quantity')).toBe('Quantity')
    expect(friendlyName('qty_sold')).toBe('Quantity sold')
    expect(friendlyName('margin_pct')).toBe('Margin (%)')
    expect(friendlyName('growth_percent')).toBe('Growth (%)')
    expect(friendlyName('invoice_value_usd')).toBe('Invoice value (USD)')
    expect(friendlyName('customer_name')).toBe('Customer name')
    expect(friendlyName('NET_SALES_INR')).toBe('Net sales (INR)')
    expect(friendlyName('gst_amount')).toBe('GST amount')
  })

  it('leaves a name already written for people, and odd names, alone', () => {
    expect(friendlyName('Net Sales')).toBe('Net Sales')
    expect(friendlyName('Domestic')).toBe('Domestic')
    expect(friendlyName('inr')).toBe('Inr') // a unit alone is the whole name
    expect(friendlyName('constructor_inr')).toBe('Constructor (INR)')
    expect(friendlyName('')).toBe('')
  })
})

describe('the tooltip values', () => {
  it('money: short and in full; 0 is "0"; no value is "-"', () => {
    expect(tipValue(63648019)).toBe('6.36 Cr (63,648,019.00)')
    expect(tipValue(63648019, '63,648,019.00')).toBe('6.36 Cr (63,648,019.00)')
    expect(tipValue(0, '0.00')).toBe('0')
    expect(tipValue(null, '-')).toBe('-')
    expect(tipValue(950.5, '950.50')).toBe('950.50') // small: the short form would say the same
    expect(tipValue(-2462000, '-2,462,000.00')).toBe('-24.6 L (-2,462,000.00)')
  })

  it('not money (a count, a quantity, a %): as the table shows it', () => {
    expect(tipValue(12500, '12,500', false)).toBe('12,500')
    expect(isMoney('net_sales_inr')).toBe(true)
    expect(isMoney('invoice_value_inr')).toBe(true)
    expect(isMoney('invoice_count')).toBe(false)
    expect(isMoney('total_qty')).toBe(false)
    expect(isMoney('margin_pct')).toBe(false)
  })

  it('shortValue: 2 places under 10, 1 under 100', () => {
    expect(shortValue(63648019)).toBe('6.36 Cr')
    expect(shortValue(3503352034.65)).toBe('350 Cr')
    expect(shortValue(2462000)).toBe('24.6 L')
    expect(shortValue(12000)).toBe('12 K')
    expect(shortValue(40)).toBe('40')
    expect(shortValue(0)).toBe('0')
  })

  it('the line tooltip: the friendly name and the money short + in full', () => {
    const tip = optionOf(MONTHLY).tooltip.formatter([{ dataIndex: 0 }])
    expect(tip).toContain('Net sales (INR)')
    expect(tip).not.toContain('net_sales_inr')
    expect(tip).toContain('1.34 Cr (13,356,235.00)')
  })

  it('a pivot keeps its series (the values of the rows) as they are; a count is not money', () => {
    const stacked = optionOf(CATEGORY_SALE_TYPE)
    expect(stacked.series.map((s: { name: string }) => s.name)).toEqual(['Domestic', 'Export'])
    const t = table([['customer_name', false], ['order_count', true]], [['A', '12,500'], ['B', '0']])
    const tip = optionOf(t, 'bar').tooltip.formatter([{ dataIndex: 0 }])
    expect(tip).toContain('Order count')
    expect(tip).toContain('>12,500<')
    expect(optionOf(t, 'bar').tooltip.formatter([{ dataIndex: 1 }])).toContain('>0<')
  })

  it('legends and series use the friendly names (several amounts)', () => {
    const t = table([['month', false], ['net_sales_inr', true], ['gross_sales_inr', true]],
      [['Jan 2026', '10.00', '12.00'], ['Feb 2026', '11.00', '13.00']])
    const option = optionOf(t)
    expect(option.series.map((s: { name: string }) => s.name)).toEqual(['Net sales (INR)', 'Gross sales (INR)'])
    expect(option.legend).toBeTruthy()
  })

  it('scatter axes and the donut tooltip use the friendly names', () => {
    const t = table([['product_name', false], ['qty_sold', true], ['net_sales_inr', true]],
      [['Pump A', '10', '5,000.00'], ['Pump B', '40', '9,000.00'], ['Pump C', '25', '12,500.00']])
    const scatter = optionOf(t, 'scatter')
    expect([scatter.xAxis.name, scatter.yAxis.name]).toEqual(['Net sales (INR)', 'Quantity sold'])
    const pie = optionOf(SALE_TYPES)
    expect(pie.tooltip.formatter({ dataIndex: 0 })).toContain('Net sales (INR)')
    expect(pie.tooltip.formatter({ dataIndex: 0 })).toContain('245 Cr (2,450,000,000.00)')
  })
})

describe('the line', () => {
  it('is smooth, with a fade under it, a glow, bigger dots with a white border and its last value at the end', () => {
    const [line] = optionOf(MONTHLY).series
    expect(line.smooth).toBeTruthy()
    expect(line.areaStyle.color.type).toBe('linear')
    expect(line.areaStyle.color.colorStops.map((c: { color: string }) => c.color))
      .toEqual([fade('#0B5FB3', 0.25), fade('#0B5FB3', 0)])                     // the brand blue
    expect(line.lineStyle.shadowBlur).toBeGreaterThan(0)
    expect(line.symbolSize).toBeGreaterThanOrEqual(7)
    expect(line.itemStyle).toMatchObject({ borderColor: '#fff', borderWidth: 2 })
    expect(line.endLabel.show).toBe(true)
    expect(line.endLabel.formatter({ value: 35033520 })).toBe('3.5 Cr')
    expect(line.endLabel.formatter({ value: 63648019 })).toBe('6.36 Cr')
    expect(line.data[0]).toBe(13356235) // the data stays plain numbers
  })

  it('several lines: lighter fades; the last values for up to 3 lines (1 on a phone)', () => {
    const t = table([['month', false], ['net_sales_inr', true], ['gross_sales_inr', true]],
      [['Jan 2026', '10.00', '12.00'], ['Feb 2026', '11.00', '13.00']])
    const two = optionOf(t).series
    expect(two[0].areaStyle.color.colorStops[0].color).toBe(fade('#0B5FB3', 0.12))
    expect(two.every((s: Option) => s.endLabel?.show)).toBe(true)
    expect(optionOf(t, null, true).series[0].endLabel).toBeUndefined()

    // 4 regions by month (a pivot): no last values, they would sit on top of each other
    const four = table([['month', false], ['region', false], ['net_sales_inr', true]],
      ['Jan 2026', 'Feb 2026'].flatMap((m) => ['North', 'South', 'East', 'West'].map((r, i) => [m, r, `${i + 1}.00`])))
    const lines = optionOf(four).series
    expect(lines).toHaveLength(4)
    expect(lines[0].type).toBe('line')
    expect(lines.some((s: Option) => s.endLabel)).toBe(false)
  })
})

describe('the bars', () => {
  it('have rounded outer ends, a light-to-dark gradient, a soft shadow and the value on each bar when few', () => {
    const horizontal = optionOf(TOP5) // long names: left to right
    const [bars] = horizontal.series
    expect(bars.itemStyle.borderRadius).toEqual([0, 6, 6, 0])
    expect(bars.itemStyle.color).toMatchObject({ type: 'linear', x: 0, y: 0, x2: 1, y2: 0 })
    expect(bars.itemStyle.shadowBlur).toBeGreaterThan(0)
    expect(bars.label).toMatchObject({ show: true, position: 'right' })
    expect(bars.label.formatter({ value: 125400000 })).toBe('12.5 Cr')

    const t = table([['sale_type', false], ['amount_inr', true]], [['A', '1,000.00'], ['B', '2,000.00'], ['C', '3,000.00']])
    const [upright] = optionOf(t, 'bar').series
    expect(upright.itemStyle.borderRadius).toEqual([6, 6, 0, 0])
    expect(upright.itemStyle.color).toMatchObject({ type: 'linear', x2: 0, y2: 1 })
    expect(upright.label.position).toBe('top')
  })

  it('have no value labels when there are many bars, and no rounding or labels when stacked', () => {
    const many = table([['customer_name', false], ['sales_inr', true]],
      Array.from({ length: 13 }, (_, i) => [`C${i}`, `${i + 1}.00`]))
    expect(optionOf(many, 'bar').series[0].label).toBeUndefined()
    const stacked = optionOf(CATEGORY_SALE_TYPE).series
    expect(stacked[0].stack).toBe('total')
    expect(stacked[0].itemStyle.borderRadius).toBe(0)
    expect(stacked[0].label).toBeUndefined()
    expect(stacked[0].itemStyle.color.type).toBe('linear')
  })
})

describe('the donut', () => {
  it('has a soft shadow, a thin white line between slices and lifts on hover', () => {
    const [pie] = optionOf(SALE_TYPES).series
    expect(pie.itemStyle).toMatchObject({ borderColor: '#fff' })
    expect(pie.itemStyle.borderWidth).toBeLessThanOrEqual(2)
    expect(pie.itemStyle.shadowBlur).toBeGreaterThan(0)
    expect(pie.emphasis.scale).toBe(true)
    expect(pie.emphasis.itemStyle.shadowBlur).toBeGreaterThan(pie.itemStyle.shadowBlur)
  })
})

describe('the grow-in animation', () => {
  it('runs for lines, bars and the donut (cubicOut), and is off with reduced motion', () => {
    for (const option of [optionOf(MONTHLY, null, false, true), optionOf(TOP5, null, false, true), optionOf(SALE_TYPES, null, false, true)]) {
      expect(option.animation).toBe(true)
      expect(option.animationDuration).toBeGreaterThanOrEqual(600)
      expect(option.animationDuration).toBeLessThanOrEqual(800)
      expect(option.animationEasing).toBe('cubicOut')
    }
    expect(optionOf(MONTHLY, null, false, false).animation).toBe(false)
    expect(optionOf(CATEGORY_SALE_TYPE, 'treemap', false, true).animation).toBe(false) // the other kinds stay still
  })

  it('by default follows prefers-reduced-motion', () => {
    const pick = pickChart(MONTHLY.headers, MONTHLY.rows)!
    const media = (reduce: boolean) => (query: string) => ({ matches: reduce && query.includes('reduce') }) as MediaQueryList
    try {
      window.matchMedia = media(true)
      expect((buildOption(pick, colours, false).option as Option).animation).toBe(false)
      window.matchMedia = media(false)
      expect((buildOption(pick, colours, false).option as Option).animation).toBe(true)
    } finally {
      delete (window as Partial<Window>).matchMedia
    }
    expect((buildOption(pick, colours, false).option as Option).animation).toBe(false) // cannot ask: still
  })
})
