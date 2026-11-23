// pickChart: which chart (or none) the answer rows get, from the texts the table shows.
import { describe, expect, it } from 'vitest'
import {
  type ChartKind, chartAskedFromText, chartKindFromText, chartWish, isCatchAll, isChartKind, labelKind, namesChartKind,
  parseNumber, pickChart, shortIndian, splitSeries, uprightWish,
  unusualChartFromText,
} from './pickChart'
import type { Cell, ChartColumns, Header } from '../types'
import {
  CATEGORY_SALE_TYPE, DAILY_MONTHLY, DAILY_MONTHLY_COLUMNS, MONTHLY, OWN_VALUE_COLUMNS, SALE_TYPES, SALES_RETURNS,
  SALES_RETURNS_COLUMNS, TOP5, TWO_YEARS, TWO_YEARS_COLUMNS, table,
} from './testRows'

describe('parseNumber', () => {
  it('reads the numbers as the table shows them', () => {
    expect(parseNumber('13,356,235.00')).toBe(13356235)
    expect(parseNumber('1,234.50')).toBe(1234.5)
    expect(parseNumber('-250.50')).toBe(-250.5)
    expect(parseNumber('12.5%')).toBe(12.5)
    expect(parseNumber('(300)')).toBe(-300)
    expect(parseNumber('42')).toBe(42)
  })

  it('gives null for no value or text', () => {
    expect(parseNumber('-')).toBeNull()
    expect(parseNumber('')).toBeNull()
    expect(parseNumber('Jan 2026')).toBeNull()
    expect(parseNumber('21-Dec-2025')).toBeNull()
  })
})

describe('pickChart', () => {
  it('draws monthly sales as a line in the row order, without the date helper columns', () => {
    const pick = pickChart(MONTHLY.headers, MONTHLY.rows)
    expect(pick?.kind).toBe('line')
    expect(pick?.x).toBe('month')
    expect(pick?.ys).toEqual(['net_sales_inr'])
    expect(pick?.data).toHaveLength(15)
    expect(pick?.data[0]).toEqual({ label: 'Jan 2026', values: [13356235], texts: ['13,356,235.00'] })
    expect(pick?.data[1].values).toEqual([9032845])
    expect(pick?.data[14]).toMatchObject({ label: 'Mar 2027', values: [3503352034.65] })
  })

  it('draws the top 5 customers as bars, by name (not code), money before counts', () => {
    const pick = pickChart(TOP5.headers, TOP5.rows)
    expect(pick?.kind).toBe('bar')
    expect(pick?.x).toBe('customer_name')
    expect(pick?.ys).toEqual(['invoice_value_inr']) // the count would need its own axis
    expect(pick?.horizontal).toBe(true) // long names
    expect(pick?.note).toBe('')
    expect(pick?.data[4].values).toEqual([850000])
  })

  it('draws Domestic / Export / Service as a donut', () => {
    const pick = pickChart(SALE_TYPES.headers, SALE_TYPES.rows)
    expect(pick?.kind).toBe('pie')
    expect(pick?.x).toBe('sale_type')
    expect(pick?.ys).toEqual(['net_sales_inr'])
    expect(pick?.data.map((p) => p.label)).toEqual(['Domestic', 'Export', 'Service'])
  })

  it('draws no chart for one row, no rows or no amount', () => {
    const one = table([['total_sales_inr', true], ['data_from', false]], [['3,503,352,034.65', '21-Dec-2025']])
    expect(pickChart(one.headers, one.rows)).toBeNull()
    expect(pickChart(SALE_TYPES.headers, [])).toBeNull()
    const names = table([['customer_name', false], ['city', false]], [['A', 'Pune'], ['B', 'Chennai']])
    expect(pickChart(names.headers, names.rows)).toBeNull()
  })

  it('draws no chart when the only numbers are ids, codes and years', () => {
    const ids = table(
      [['customer_id', true], ['customer_name', false], ['year', true], ['order_no', true], ['gst_code', true]],
      [['101', 'Asha Tools', '2026', '5001', '998'], ['102', 'Bharat Gears', '2025', '5002', '997']],
    )
    expect(pickChart(ids.headers, ids.rows)).toBeNull()
    // a number column holding years is a year whatever its name
    const yrs = table([['customer_name', false], ['first_bought', true]], [['A', '2025'], ['B', '2026']])
    expect(pickChart(yrs.headers, yrs.rows)).toBeNull()
  })

  it('keeps "-" as no value', () => {
    const t = table(
      [['product_name', false], ['stock_value_inr', true]],
      [['Bearing 6204', '45,000.00'], ['Shaft 20mm', '-'], ['Gear 40T', '12,500.00']],
    )
    const pick = pickChart(t.headers, t.rows)
    expect(pick?.kind).toBe('bar')
    expect(pick?.data.map((p) => p.values[0])).toEqual([45000, null, 12500])
    expect(pick?.data[1].texts).toEqual(['-'])
  })

  it('keeps negative credit notes, and parts with a minus are bars, not a donut', () => {
    const t = table(
      [['document_type', false], ['amount_inr', true]],
      [['INVOICE', '1,000,000.00'], ['CREDIT_NOTE', '-250,500.50'], ['DEBIT_NOTE', '40,000.00']],
    )
    const pick = pickChart(t.headers, t.rows)
    expect(pick?.kind).toBe('bar')
    expect(pick?.data[1].values).toEqual([-250500.5])
  })

  it('draws only the top 25 of many names, with a note', () => {
    const rows = Array.from({ length: 30 }, (_, i) => [`Customer ${i + 1}`, `${(30 - i) * 1000}.00`])
    const t = table([['customer_name', false], ['sales_inr', true]], rows)
    const pick = pickChart(t.headers, t.rows)
    expect(pick?.kind).toBe('bar')
    expect(pick?.data).toHaveLength(25)
    expect(pick?.note).toBe('top 25 of 30')
    expect(pick?.horizontal).toBe(true) // many bars
  })

  it('draws no line of more than 60 points', () => {
    const rows = Array.from({ length: 61 }, (_, i) => [`${String(i % 28 + 1).padStart(2, '0')}-Jan-${2000 + i}`, '10.00'])
    const t = table([['invoice_date', false], ['sales_inr', true]], rows)
    expect(pickChart(t.headers, t.rows)).toBeNull()
    const short = table([['invoice_date', false], ['sales_inr', true]], rows.slice(0, 60))
    expect(pickChart(short.headers, short.rows)?.kind).toBe('line')
  })

  it('sees financial years, quarters and dates as time', () => {
    const fy = table([['financial_year', false], ['net_sales_inr', true]], [['FY 2025-26', '10.00'], ['FY 2026-27', '20.00']])
    expect(pickChart(fy.headers, fy.rows)?.kind).toBe('line')
    const codes = table([['financial_year', false], ['net_sales_inr', true]], [['2526', '10.00'], ['2627', '20.00']])
    expect(pickChart(codes.headers, codes.rows)?.kind).toBe('line')
    const quarters = table([['quarter', false], ['sales_inr', true]], [['Q1 FY 2026-27', '1.00'], ['Q2 FY 2026-27', '2.00']])
    expect(pickChart(quarters.headers, quarters.rows)?.kind).toBe('line')
    const years = table([['year', true], ['sales_inr', true]], [['2025', '1.00'], ['2026', '2.00']])
    expect(pickChart(years.headers, years.rows)).toMatchObject({ kind: 'line', x: 'year' })
  })

  it('draws up to 3 series of the same kind on one axis', () => {
    const t = table(
      [['month', false], ['invoice_count', true], ['domestic_inr', true], ['export_inr', true],
        ['service_inr', true], ['other_inr', true], ['sales_jpy', true]],
      [['Jan 2026', '4', '1.00', '2.00', '3.00', '4.00', '5.00'], ['Feb 2026', '5', '2.00', '3.00', '4.00', '5.00', '6.00']],
    )
    const pick = pickChart(t.headers, t.rows)
    expect(pick?.kind).toBe('line')
    expect(pick?.ys).toEqual(['domestic_inr', 'export_inr', 'service_inr'])
  })

  it('pivots a label that repeats: month x customer is one line per customer', () => {
    const t = table(
      [['month', false], ['customer_name', false], ['sales_inr', true]],
      [['Jan 2026', 'A', '1.00'], ['Jan 2026', 'B', '2.00'], ['Feb 2026', 'A', '3.00'], ['Feb 2026', 'B', '4.00']],
    )
    const pick = pickChart(t.headers, t.rows)
    expect(pick).toMatchObject({ kind: 'line', x: 'month', group: 'customer_name', amount: 'sales_inr', ys: ['A', 'B'] })
    expect(pick?.data.map((p) => p.values)).toEqual([[1, 2], [3, 4]])
  })

  it('draws no chart when the same pair of labels comes twice (no pivot can hold it)', () => {
    const t = table(
      [['month', false], ['customer_name', false], ['sales_inr', true]],
      [['Jan 2026', 'A', '1.00'], ['Jan 2026', 'A', '2.00'], ['Feb 2026', 'B', '3.00']],
    )
    expect(pickChart(t.headers, t.rows)).toBeNull()
  })
})

describe('the pivot (2 labels + an amount)', () => {
  it('makes product_category x sale_type a matrix: rows = the first label, series = the second', () => {
    // Not classified shown; stacked bars asked (unasked, 97% in one group would sort the bars biggest first)
    const pick = pickChart(CATEGORY_SALE_TYPE.headers, CATEGORY_SALE_TYPE.rows, 'stacked', false)
    expect(pick).toMatchObject({ kind: 'stacked', x: 'product_category', group: 'sale_type', amount: 'net_sales_inr' })
    expect(pick?.ys).toEqual(['Domestic', 'Export', 'Service'])
    expect(pick?.data.map((p) => p.label)).toEqual(['Coolant pumps', 'Coolant Units', 'GCI', 'Hydraulic motors',
      'Not classified', 'Procon Pumps', 'Trochoid pumps', 'YTH-PARTS'])
    // a missing pair stays empty
    expect(pick?.data[0]).toEqual({ label: 'Coolant pumps', values: [20321380, 1783650, null], texts: ['20,321,380.00', '1,783,650.00', '-'] })
    expect(pick?.data[4].values).toEqual([3314096846.5, 667910761.5, 871750])
    expect(pick?.horizontal).toBe(true) // long category names
    expect(pick?.options).toEqual(['stacked', 'line', 'area', 'stackedArea', 'grouped', 'treemap', 'heatmap', 'radar'])
  })

  it('draws the pivot as a treemap, a heatmap, grouped bars or a radar when asked', () => {
    for (const kind of ['treemap', 'heatmap', 'grouped', 'radar', 'stackedArea'] as const) {
      const pick = pickChart(CATEGORY_SALE_TYPE.headers, CATEGORY_SALE_TYPE.rows, kind, false)
      expect(pick?.kind).toBe(kind)
      expect(pick?.fallback).toBe('')
      expect(pick?.ys).toHaveLength(3)
    }
    // "bar chart" of a pivot = its stacked bars
    expect(pickChart(CATEGORY_SALE_TYPE.headers, CATEGORY_SALE_TYPE.rows, 'bar')?.kind).toBe('stacked')
  })

  it('a pivot cannot be a donut, a funnel, a waterfall or a scatter: stacked bars, with a note why', () => {
    const notes = {
      pie: 'A donut needs up to 12 positive parts of one amount - showing stacked bars.',
      funnel: 'A funnel needs one positive amount per step (up to 12 steps) - showing stacked bars.',
      waterfall: 'A waterfall needs one amount per step (up to 25 steps) - showing stacked bars.',
      scatter: 'A scatter chart needs two amount columns of different kinds - showing stacked bars.',
    }
    for (const [kind, note] of Object.entries(notes)) {
      const pick = pickChart(CATEGORY_SALE_TYPE.headers, CATEGORY_SALE_TYPE.rows, kind as keyof typeof notes)
      expect(pick?.kind).toBe('stacked')
      expect(pick?.fallback).toBe(note)
    }
  })

  it('puts the time along the axis whatever the column order (customer x month)', () => {
    const t = table(
      [['customer_name', false], ['month', false], ['sales_inr', true]],
      [['A', 'Jan 2026', '1.00'], ['A', 'Feb 2026', '3.00'], ['B', 'Jan 2026', '2.00'], ['B', 'Feb 2026', '4.00']],
    )
    const pick = pickChart(t.headers, t.rows)
    expect(pick).toMatchObject({ kind: 'line', x: 'month', group: 'customer_name', ys: ['A', 'B'] })
    expect(pick?.data.map((p) => p.label)).toEqual(['Jan 2026', 'Feb 2026'])
  })

  it('keeps the label with fewer values as the series, and only the 10 biggest series', () => {
    // 12 customers x 2 sale types: sale_type makes the series (the customers would be too many)
    const rows = Array.from({ length: 12 }, (_, i) => [[`Customer ${i + 1}`, 'Domestic', `${(i + 1) * 100}.00`],
      [`Customer ${i + 1}`, 'Export', `${i + 1}.00`]]).flat()
    const wide = table([['customer_name', false], ['sale_type', false], ['net_sales_inr', true]], rows)
    expect(pickChart(wide.headers, wide.rows)).toMatchObject({ x: 'customer_name', group: 'sale_type', ys: ['Domestic', 'Export'] })

    // 2 months x 12 customers: the month stays on the axis, the 10 biggest customers are drawn
    const many = Array.from({ length: 12 }, (_, i) => [['Jan 2026', `Customer ${i + 1}`, `${i + 1}.00`],
      ['Feb 2026', `Customer ${i + 1}`, `${i + 1}.00`]]).flat()
    const t = table([['month', false], ['customer_name', false], ['sales_inr', true]], many)
    const pick = pickChart(t.headers, t.rows)
    expect(pick?.ys).toHaveLength(10)
    expect(pick?.ys).not.toContain('Customer 1')
    expect(pick?.seriesNote).toBe('top 10 of 12 customer_name values')
  })

  it('draws only the top 25 categories of a big pivot', () => {
    const rows = Array.from({ length: 30 }, (_, i) => [[`Item ${i + 1}`, 'Domestic', `${(30 - i) * 10}.00`],
      [`Item ${i + 1}`, 'Export', '1.00']]).flat()
    const t = table([['product_name', false], ['sale_type', false], ['net_sales_inr', true]], rows)
    const pick = pickChart(t.headers, t.rows)
    expect(pick?.kind).toBe('stacked')
    expect(pick?.data).toHaveLength(25)
    expect(pick?.note).toBe('top 25 of 30')
  })

  it('an average is not stacked: grouped bars', () => {
    const t = table(
      [['region', false], ['sale_type', false], ['avg_price_inr', true]],
      [['North', 'Domestic', '10.00'], ['North', 'Export', '12.00'], ['South', 'Domestic', '9.00'], ['South', 'Export', '11.00']],
    )
    const pick = pickChart(t.headers, t.rows, 'stacked')
    expect(pick?.kind).toBe('grouped')
    expect(pick?.fallback).toBe('Stacked bars need two labels or several amounts that add up - showing grouped bars.')
  })
})

describe('the other kinds', () => {
  it('draws one amount as a treemap, a funnel, a radar or a waterfall', () => {
    for (const kind of ['treemap', 'funnel', 'radar', 'waterfall', 'area', 'hbar'] as const) {
      const pick = pickChart(SALE_TYPES.headers, SALE_TYPES.rows, kind)
      expect(pick?.kind).toBe(kind)
      expect(pick?.fallback).toBe('')
    }
    expect(pickChart(SALE_TYPES.headers, SALE_TYPES.rows, 'hbar')?.horizontal).toBe(true)
    expect(pickChart(SALE_TYPES.headers, SALE_TYPES.rows)?.options)
      .toEqual(['pie', 'line', 'area', 'bar', 'hbar', 'treemap', 'funnel', 'radar', 'waterfall'])
  })

  it('a horizontal bar of long names is the bar (one button)', () => {
    const pick = pickChart(TOP5.headers, TOP5.rows, 'hbar')
    expect(pick?.kind).toBe('bar')
    expect(pick?.horizontal).toBe(true)
    expect(pick?.options).not.toContain('hbar')
  })

  it('draws two amounts of different kinds as a scatter (not for a ranking)', () => {
    const t = table(
      [['product_name', false], ['qty_sold', true], ['net_sales_inr', true]],
      [['Pump A', '10', '5,000.00'], ['Pump B', '40', '9,000.00'], ['Pump C', '25', '12,500.00'],
        ['Pump D', '5', '1,000.00'], ['Pump E', '60', '30,000.00']],
    )
    const pick = pickChart(t.headers, t.rows)
    expect(pick).toMatchObject({ kind: 'scatter', x: 'product_name', ys: ['net_sales_inr', 'qty_sold'] })
    expect(pick?.data[1]).toEqual({ label: 'Pump B', values: [9000, 40], texts: ['9,000.00', '40'] })
    // the top 5 customers by value (a ranking) stay bars, but can be a scatter
    expect(pickChart(TOP5.headers, TOP5.rows)?.kind).toBe('bar')
    expect(pickChart(TOP5.headers, TOP5.rows, 'scatter')?.ys).toEqual(['invoice_value_inr', 'invoice_count'])
  })

  it('falls back with a note when the asked kind does not fit', () => {
    // one amount: no heatmap, no stacked bars, no scatter
    expect(pickChart(SALE_TYPES.headers, SALE_TYPES.rows, 'heatmap')?.fallback)
      .toBe('A heatmap needs two labels (or several amounts) - showing a donut.')
    expect(pickChart(TOP5.headers, TOP5.rows, 'stacked')?.fallback)
      .toBe('Stacked bars need two labels or several amounts that add up - showing bars.')
    // a funnel of 15 months
    const funnel = pickChart(MONTHLY.headers, MONTHLY.rows, 'funnel')
    expect(funnel?.kind).toBe('line')
    expect(funnel?.fallback).toBe('A funnel needs one positive amount per step (up to 12 steps) - showing a line.')
    // a waterfall whose running total goes below zero
    const below = table([['document_type', false], ['amount_inr', true]], [['INVOICE', '100.00'], ['CREDIT_NOTE', '-250.00']])
    expect(pickChart(below.headers, below.rows, 'waterfall')?.fallback)
      .toBe('A waterfall needs a running total that stays above zero - showing bars.')
    // a radar needs 3 or more spokes
    const two = table([['sale_type', false], ['net_sales_inr', true]], [['Domestic', '10.00'], ['Export', '5.00']])
    expect(pickChart(two.headers, two.rows, 'radar')?.kind).toBe('pie')
  })

  it('draws a waterfall with credit notes when the total stays above zero', () => {
    const t = table(
      [['document_type', false], ['amount_inr', true]],
      [['INVOICE', '1,000,000.00'], ['CREDIT_NOTE', '-250,500.50'], ['DEBIT_NOTE', '40,000.00']],
    )
    const pick = pickChart(t.headers, t.rows, 'waterfall')
    expect(pick?.kind).toBe('waterfall')
    expect(pick?.options).toContain('waterfall')
    expect(pick?.options).not.toContain('pie') // a minus is not a part of a whole
    expect(pick?.options).not.toContain('treemap')
  })

  it('several amounts of one kind: grouped bars, stacked bars and a heatmap fit', () => {
    const t = table(
      [['region', false], ['domestic_inr', true], ['export_inr', true]],
      [['North', '10.00', '2.00'], ['South', '8.00', '3.00'], ['West', '5.00', '1.00']],
    )
    const pick = pickChart(t.headers, t.rows)
    expect(pick?.kind).toBe('grouped')
    expect(pick?.options).toEqual(['grouped', 'line', 'area', 'stackedArea', 'stacked', 'treemap', 'heatmap', 'radar'])
    expect(pickChart(t.headers, t.rows, 'bar')?.kind).toBe('grouped')
  })
})

describe('shortIndian', () => {
  it('writes crores, lakhs and thousands', () => {
    expect(shortIndian(13356235)).toBe('1.3 Cr')
    expect(shortIndian(3503352034.65)).toBe('350 Cr')
    expect(shortIndian(3500000)).toBe('35 L')
    expect(shortIndian(12000)).toBe('12 K')
    expect(shortIndian(-250500.5)).toBe('-2.5 L')
    expect(shortIndian(950)).toBe('950')
    expect(shortIndian(0)).toBe('0')
  })
})

describe('the chart the user asks for', () => {
  it('knows when any chart was asked for (the note when the rows fit none)', () => {
    for (const text of ['for that above answer create one line chart', 'sales linechart', 'show it as a graph',
      'plot the sales', 'sale types as a pie', 'a donut of credit notes', 'net sales per state as bars',
      'visualise the sales', 'Net sales as a bar chart']) {
      expect(chartAskedFromText(text), text).toBe(true)
    }
    for (const text of ['how many invoice lines in Aug 2026?', 'top customers in Oct 2026', 'sales by area', '']) {
      expect(chartAskedFromText(text), text).toBe(false)
    }
  })

  it('reads the chart kind from the question', () => {
    expect(chartKindFromText('above questions give me that bar chart now')).toBe('bar')
    expect(chartKindFromText('Show a bar chart of sales amount for each month.')).toBe('bar')
    expect(chartKindFromText('net sales per state as bars')).toBe('bar')
    expect(chartKindFromText('monthly sales as a line graph')).toBe('line')
    expect(chartKindFromText('show the trend chart of invoices')).toBe('line')
    expect(chartKindFromText('sale types as a pie')).toBe('pie')
    expect(chartKindFromText('a donut of credit notes by type')).toBe('pie')
    expect(chartKindFromText('how many invoice lines in Aug 2026?')).toBeNull()   // "lines" is not a chart
    expect(chartKindFromText('give me sales amount of each month')).toBeNull()
    expect(chartKindFromText('')).toBeNull()
  })

  it('reads every new kind from the question', () => {
    const words: [string, string][] = [
      ['show this as a treemap', 'treemap'], ['product category and sale type as a tree map', 'treemap'],
      ['a heatmap of sales by region and month', 'heatmap'], ['heat-map please', 'heatmap'],
      ['stacked bar chart of sales by category and sale type', 'stacked'], ['make it stacked', 'stacked'],
      ['grouped bar chart by sale type', 'grouped'], ['clustered columns', 'grouped'], ['side by side bars', 'grouped'],
      ['an area chart of monthly sales', 'area'], ['stacked area chart by sale type', 'stackedArea'],
      ['scatter plot of quantity against value', 'scatter'], ['scatter of qty and value', 'scatter'],
      ['sales funnel of orders', 'funnel'], ['radar chart of categories', 'radar'], ['a spider chart', 'radar'],
      ['waterfall of invoices and credit notes', 'waterfall'], ['horizontal bar chart of customers', 'hbar'],
      ['multi-line chart by customer', 'line'], ['show the bar graph', 'bar'], ['as a doughnut', 'pie'],
    ]
    for (const [text, kind] of words) expect(chartKindFromText(text), text).toBe(kind)
  })

  it('does not read a chart from everyday words', () => {
    for (const text of ['how many invoice lines in Aug 2026?', 'net sales by area', 'sales grouped by region',
      'top customers in each zone', 'average line value of invoices']) {
      expect(chartKindFromText(text), text).toBeNull()
    }
  })

  it('names the charts the app cannot draw itself (the AI button)', () => {
    const words: [string, string][] = [
      ['show it as a sankey', 'sankey diagram'], ['sunburst of category and sale type', 'sunburst chart'],
      ['box plot of invoice values', 'box plot'], ['show this month as a gauge', 'gauge'],
      ['this month vs target', 'chart with a target line'], ['nightingale rose of sale types', 'rose (polar) chart'],
      ['bar chart with a target line', 'chart with a target line'], ['bubble by region', 'bubble chart'],
      ['sales as bars and a line', 'bar and line combo chart'], ['a histogram of invoice values', 'histogram'],
    ]
    for (const [text, name] of words) expect(unusualChartFromText(text), text).toBe(name)
    expect(chartKindFromText('bar chart with a target line')).toBe('bar') // the bars are drawn too
    for (const text of ['top 5 customers as a bar chart', 'show it as a treemap', 'how many invoice lines?', '',
      'sales of pressure gauges', 'which customers sales rose in Aug?', 'average line value of invoices', 'bubble wrap stock']) {
      expect(unusualChartFromText(text), text).toBeNull()
    }
  })

  it('draws months as bars when bars are asked for - upright and in month order', () => {
    const pick = pickChart(MONTHLY.headers, MONTHLY.rows, 'bar')
    expect(pick?.kind).toBe('bar')
    expect(pick?.horizontal).toBe(false)
    expect(pick?.data.map((p) => p.label)).toEqual(MONTHLY.rows.map((row) => row[1].text))
    expect(pick?.note).toBe('')
  })

  it('draws the top customers as a line or a donut when asked, and lists the kinds for the buttons', () => {
    expect(pickChart(TOP5.headers, TOP5.rows, 'line')?.kind).toBe('line')
    const donut = pickChart(TOP5.headers, TOP5.rows, 'pie')
    expect(donut?.kind).toBe('pie')
    expect(donut?.ys).toHaveLength(1)
    expect(pickChart(TOP5.headers, TOP5.rows)?.options)
      .toEqual(['bar', 'line', 'area', 'pie', 'treemap', 'scatter', 'funnel', 'radar', 'waterfall'])
  })

  it('keeps the best kind when the asked one does not fit the rows', () => {
    // 15 months are too many parts for a donut: still the line, a note why, and no Donut button
    const pick = pickChart(MONTHLY.headers, MONTHLY.rows, 'pie')
    expect(pick?.kind).toBe('line')
    expect(pick?.fallback).toBe('A donut needs up to 12 positive parts of one amount - showing a line.')
    expect(pick?.options).toEqual(['line', 'area', 'bar', 'hbar', 'treemap', 'waterfall'])
    // negative values (credit notes) are not parts of a whole either
    const withNegative = table([['customer_name', false], ['net_sales_inr', true]],
      [['Aurora', '1,000.00'], ['Meridian', '-250.00'], ['Lotus', '500.00']])
    expect(pickChart(withNegative.headers, withNegative.rows, 'pie')?.kind).toBe('bar')
  })

  it('without a wish the choice is the same as before', () => {
    expect(pickChart(MONTHLY.headers, MONTHLY.rows)?.kind).toBe('line')
    expect(pickChart(TOP5.headers, TOP5.rows)?.kind).toBe('bar')
    expect(pickChart(SALE_TYPES.headers, SALE_TYPES.rows)?.kind).toBe('pie')
  })
})

describe('catch-all groups (Not classified, Unknown, Others ...)', () => {
  it('knows a catch-all name, and not a real name that only contains one', () => {
    for (const name of ['Not classified', 'NOT CLASSIFIED', 'not_classified', 'Not given', 'Not specified', 'Unknown',
      'Unassigned', 'Unclassified', 'Others', 'Other', 'N/A', 'n / a', '-', '', '  ', '(blank)', 'Blank', '(Unknown)', 'None']) {
      expect(isCatchAll(name), name).toBe(true)
    }
    for (const name of ['Unknown Hydraulics Ltd', 'Other Machines Pvt Ltd', 'Not classified pumps', 'Others Ltd', 'Coolant pumps',
      'Domestic', 'Unknowns', 'N/A Pumps', 'NA', 'Nonstop Gears', 'Mother Dairy', 'GCI']) {
      expect(isCatchAll(name), name).toBe(false)
    }
  })

  it('hides Not classified of the real rows at first (97% of the total) - the chart only', () => {
    const before = JSON.stringify(CATEGORY_SALE_TYPE.rows)
    const pick = pickChart(CATEGORY_SALE_TYPE.headers, CATEGORY_SALE_TYPE.rows)
    expect(pick?.catchAll).toMatchObject({ label: 'Not classified', name: 'Not classified', total: 3982879358, hidden: true })
    expect(pick?.catchAll?.share).toBeCloseTo(96.82, 1)
    expect(pick?.data.map((p) => p.label)).toEqual(['Coolant pumps', 'Coolant Units', 'GCI', 'Hydraulic motors',
      'Procon Pumps', 'Trochoid pumps', 'YTH-PARTS'])
    expect(pick?.ys).toEqual(['Domestic', 'Export']) // Service was only Not classified's
    expect(pick?.data[0]).toEqual({ label: 'Coolant pumps', values: [20321380, 1783650], texts: ['20,321,380.00', '1,783,650.00'] })
    expect(pick?.kind).toBe('stacked')
    expect(JSON.stringify(CATEGORY_SALE_TYPE.rows)).toBe(before) // the rows (the table) are not changed

    // the button: shown again, and hidden again
    const shown = pickChart(CATEGORY_SALE_TYPE.headers, CATEGORY_SALE_TYPE.rows, null, false)
    expect(shown?.catchAll?.hidden).toBe(false)
    expect(shown?.data).toHaveLength(8)
    expect(shown?.ys).toEqual(['Domestic', 'Export', 'Service'])
  })

  it('a small catch-all stays at first, but can be hidden; no catch-all, no button', () => {
    const t = table([['region', false], ['net_sales_inr', true]],
      [['North', '40.00'], ['South', '35.00'], ['Others', '25.00']])
    const pick = pickChart(t.headers, t.rows)
    expect(pick?.catchAll).toMatchObject({ label: 'Others', share: 25, hidden: false })
    expect(pick?.data).toHaveLength(3)
    const hidden = pickChart(t.headers, t.rows, null, true)
    expect(hidden?.catchAll?.hidden).toBe(true)
    expect(hidden?.data.map((p) => p.label)).toEqual(['North', 'South'])
    // a blank name is a catch-all too
    const blank = table([['region', false], ['net_sales_inr', true]], [['North', '1.00'], ['South', '2.00'], ['', '90.00']])
    expect(pickChart(blank.headers, blank.rows)?.catchAll).toMatchObject({ label: '', name: '(blank)', hidden: true })

    expect(pickChart(TOP5.headers, TOP5.rows)?.catchAll).toBeNull()
    expect(pickChart(MONTHLY.headers, MONTHLY.rows)?.catchAll).toBeNull() // a time has no catch-all
    const two = table([['region', false], ['net_sales_inr', true]], [['North', '1.00'], ['Unknown', '99.00']])
    expect(pickChart(two.headers, two.rows)?.catchAll).toBeNull() // one group would be left
  })

  it('still draws only the top 25, without the hidden group', () => {
    const rows = [['Not classified', '1,000,000.00'], ...Array.from({ length: 30 }, (_, i) => [`Customer ${i + 1}`, `${(30 - i) * 10}.00`])]
    const t = table([['customer_name', false], ['sales_inr', true]], rows)
    const pick = pickChart(t.headers, t.rows)
    expect(pick?.catchAll?.hidden).toBe(true)
    expect(pick?.data).toHaveLength(25)
    expect(pick?.data[0].label).toBe('Customer 1')
    expect(pick?.note).toBe('top 25 of 31')
  })

  it('a waterfall keeps every step (its total needs them)', () => {
    const t = table([['document_type', false], ['amount_inr', true]],
      [['INVOICE', '10.00'], ['CREDIT_NOTE', '-2.00'], ['Unknown', '500.00']])
    const pick = pickChart(t.headers, t.rows, 'waterfall')
    expect(pick?.kind).toBe('waterfall')
    expect(pick?.catchAll).toBeNull()
    expect(pick?.data).toHaveLength(3)
  })
})

describe('very uneven groups (one holds more than 80%)', () => {
  const UNEVEN = table([['sale_type', false], ['net_sales_inr', true]],
    [['Service', '20.00'], ['Domestic', '900.00'], ['Export', '80.00']])

  it('draws bars, biggest first, instead of a donut when no kind was asked', () => {
    const pick = pickChart(UNEVEN.headers, UNEVEN.rows)
    expect(pick?.kind).toBe('bar')
    expect(pick?.data.map((p) => p.label)).toEqual(['Domestic', 'Export', 'Service'])
    expect(pick?.options[0]).toBe('bar')
    expect(pick?.options).toContain('pie') // the donut is still one click away
    // an even split stays a donut
    expect(pickChart(SALE_TYPES.headers, SALE_TYPES.rows)?.kind).toBe('pie')
  })

  it('a kind the user asked for always wins', () => {
    const treemap = pickChart(UNEVEN.headers, UNEVEN.rows, 'treemap')
    expect(treemap?.kind).toBe('treemap')
    expect(treemap?.data.map((p) => p.label)).toEqual(['Service', 'Domestic', 'Export']) // in the rows' order
    expect(pickChart(UNEVEN.headers, UNEVEN.rows, 'pie')?.kind).toBe('pie')
    // the real rows asked as a treemap: still a treemap, Not classified hidden so the rest can be read
    const real = pickChart(CATEGORY_SALE_TYPE.headers, CATEGORY_SALE_TYPE.rows, 'treemap')
    expect(real).toMatchObject({ kind: 'treemap', catchAll: { hidden: true } })
  })
})
// 17-Nov: "can you create plot bar chat last 6 months sales" drew a line - the typo "chat" hid the bar wish.
// Now the AI names the kind (the answer's chart_kind); the words stay as the fallback.
const SIX_MONTHS = table([['month', false], ['net_sales_inr', true]], [
  ['Jun 2026', '205,330,410.00'], ['Jul 2026', '240,118,900.75'], ['Aug 2026', '260,700,001.00'],
  ['Sep 2026', '255,980,450.00'], ['Oct 2026', '290,442,120.30'], ['Nov 2026', '310,005,600.00'],
])
const TYPO_QUESTION = 'can you create plot bar chat last 6 months sales'

describe('the chart kind the AI names (chart_kind)', () => {
  it('knows the kinds the app draws, and nothing else', () => {
    for (const kind of ['bar', 'hbar', 'line', 'area', 'stackedArea', 'stacked', 'grouped', 'pie', 'scatter',
      'heatmap', 'treemap', 'waterfall', 'funnel', 'radar']) {
      expect(isChartKind(kind), kind).toBe(true)
    }
    for (const value of ['', 'Bar', 'sankey', 'gauge', 'donut', 'constructor', 'toString', null, undefined, 3]) {
      expect(isChartKind(value), String(value)).toBe(false)
    }
  })

  it('uses chart_kind first, else the words, else none', () => {
    expect(chartWish('bar', TYPO_QUESTION)).toBe('bar')
    expect(chartWish('bar', 'monthly sales as a line chart')).toBe('bar')        // chart_kind wins over the words
    expect(chartWish('sankey', 'monthly sales as a line chart')).toBe('line')    // an unknown kind: the words
    expect(chartWish('', 'monthly sales as a line chart')).toBe('line')          // none named: the words
    expect(chartWish(undefined, 'monthly sales as a pie')).toBe('pie')           // an older server: the words
    expect(chartWish(undefined, 'give me sales amount of each month')).toBeNull() // no wish at all
    // 19-Nov: 'none' = the AI said no chart helps (the card shows the table first) - not a kind, not a chart wish
    expect(chartWish('none', 'give me sales amount of each month')).toBeNull()
    expect(namesChartKind('none')).toBe(false)
    expect(uprightWish('none', 'sales of each month')).toBe(false)
  })

  it('draws the 17-Nov question as bars, upright and in month order', () => {
    const pick = pickChart(SIX_MONTHS.headers, SIX_MONTHS.rows, chartWish('bar', TYPO_QUESTION))
    expect(pick?.kind).toBe('bar')
    expect(pick?.horizontal).toBe(false)
    expect(pick?.data.map((p) => p.label)).toEqual(SIX_MONTHS.rows.map((row) => row[0].text))
    // without a wish the months are a line, as before
    expect(pickChart(SIX_MONTHS.headers, SIX_MONTHS.rows, chartWish('', 'last 6 months sales'))?.kind).toBe('line')
  })

  it('still swaps a named kind the rows cannot show for one that fits', () => {
    // 15 months are too many parts for a donut: the line, with the note why
    const pick = pickChart(MONTHLY.headers, MONTHLY.rows, chartWish('pie', 'monthly sales'))
    expect(pick?.kind).toBe('line')
    expect(pick?.fallback).toBe('A donut needs up to 12 positive parts of one amount - showing a line.')
  })
})

describe('chart words with typos', () => {
  it('reads a kind word followed by a typo of chart / graph', () => {
    const words: [string, string][] = [
      [TYPO_QUESTION, 'bar'], ['bar chrt of sales', 'bar'], ['sales as a bar cahrt', 'bar'], ['bar graf', 'bar'],
      ['column grph by customer', 'bar'], ['plot a bar of last 6 months', 'bar'], ['plot bar of sales', 'bar'],
      ['draw bars for each month', 'bar'], ['draw a bar of sales', 'bar'], ['show the months as columns', 'bar'],
      ['line chat of monthly sales', 'line'], ['trend grph', 'line'], ['an area chat of monthly sales', 'area'],
    ]
    for (const [text, kind] of words) expect(chartKindFromText(text), text).toBe(kind)
    expect(chartAskedFromText(TYPO_QUESTION)).toBe(true)
  })

  it('never reads "chat" alone as a chart', () => {
    for (const text of ['start a new chat', 'in this chat, top customers', 'chat history of Oct', 'new chat: sales by area',
      'sales in the chat above', 'plot of land sales', 'barcode stock', 'show customer name as a column']) {
      expect(chartKindFromText(text), text).toBeNull()
    }
    for (const text of ['start a new chat', 'what did I ask in this chat?', 'chat']) {
      expect(chartAskedFromText(text), text).toBe(false)
    }
  })
})

// 17-Nov: "show me colum grph of top 5 custmers by sales" drew sideways bars: long names turn bars sideways, but a
// column chart means bars standing upright. The AI names it "column"; the words are the fallback.
describe('a column chart (bars standing upright)', () => {
  it('is read from the AI first, else from the words, typos too', () => {
    expect(uprightWish('column', 'top 5 customers')).toBe(true)
    expect(uprightWish('', 'show me colum grph of top 5 custmers by sales')).toBe(true)
    expect(uprightWish(undefined, 'top products as a column chart')).toBe(true)
    expect(uprightWish('bar', 'vertical bars of sales by customer')).toBe(true)   // the AI said bar: the words add upright
    expect(uprightWish('hbar', 'column chart of sales')).toBe(false)             // another kind the AI named wins
    expect(uprightWish('', 'top 5 customers bar chart')).toBe(false)
    expect(uprightWish('', 'show the column names of the invoice table')).toBe(false)
  })

  it('is drawn as bars, and counts as a chart wish', () => {
    expect(chartWish('column', '')).toBe('bar')
    expect(namesChartKind('column')).toBe(true)
    expect(namesChartKind('gizmo')).toBe(false)
  })

  it('keeps bars of long names upright, with the sideways bars one button away', () => {
    const upright = pickChart(TOP5.headers, TOP5.rows, 'bar', null, true)
    expect(upright?.kind).toBe('bar')
    expect(upright?.horizontal).toBe(false)
    expect(upright?.options).toContain('hbar')
    // without the column wish: sideways, as before
    expect(pickChart(TOP5.headers, TOP5.rows, 'bar')?.horizontal).toBe(true)
  })
})

// 19-Nov: "Which products have the most stock right now?" drew the stock VALUE (lakhs) with the long, alike
// descriptions as the bar names. The AI now names the columns ("CHART: bar | value: stock_qty | label:
// product_code" -> card.chart_columns); pickChart draws exactly those when the rows have them, else as before.
const STOCK = table(
  [['report_date', false], ['product_code', false], ['description', false], ['item_group', false],
    ['stock_qty', true], ['stock_value_inr', true]],
  [
    ['31-Oct-2026', 'CIH-2040', 'Cast iron housing for coolant pump 2040 series', 'Castings', '1,250', '4,812,500.00'],
    ['31-Oct-2026', 'CIH-2060', 'Cast iron housing for coolant pump 2060 series', 'Castings', '980', '5,096,000.00'],
    ['31-Oct-2026', 'CIH-3080', 'Cast iron housing for coolant pump 3080 series', 'Castings', '760', '6,080,000.00'],
    ['31-Oct-2026', 'TRP-110', 'Trochoid pump 110 with motor flange', 'Pumps', '540', '8,100,000.00'],
    ['31-Oct-2026', 'TRP-220', 'Trochoid pump 220 with motor flange', 'Pumps', '310', '7,750,000.00'],
  ],
)

describe('the columns the AI names (chart_columns)', () => {
  it('draws the named value with the named labels: stock_qty by product_code', () => {
    const pick = pickChart(STOCK.headers, STOCK.rows, 'bar', null, false, { value: 'stock_qty', label: 'product_code' })
    expect(pick).toMatchObject({ kind: 'bar', x: 'product_code', ys: ['stock_qty'], amount: 'stock_qty', group: '' })
    expect(pick?.data.map((p) => p.label)).toEqual(['CIH-2040', 'CIH-2060', 'CIH-3080', 'TRP-110', 'TRP-220'])
    expect(pick?.data.map((p) => p.values)).toEqual([[1250], [980], [760], [540], [310]])
    expect(pick?.horizontal).toBe(false) // short codes: the bars stand upright
  })

  it('without names it is the old choice (the value in rupees by the long descriptions)', () => {
    const pick = pickChart(STOCK.headers, STOCK.rows, 'bar')
    expect(pick).toMatchObject({ x: 'description', ys: ['stock_value_inr'] })
  })

  it('matches the names in any case, with backticks or a table prefix', () => {
    const pick = pickChart(STOCK.headers, STOCK.rows, null, null, false, { value: 'STOCK_QTY', label: '`p.Product_Code`' })
    expect(pick).toMatchObject({ x: 'product_code', ys: ['stock_qty'] })
  })

  it('falls back to the old rules when a name is not in the rows or does not fit', () => {
    const old = pickChart(STOCK.headers, STOCK.rows, 'bar')
    for (const columns of [
      { value: 'stock_quantity', label: 'product_code' }, // a column the rows do not have
      { value: 'stock_qty', label: 'product_name' },
      { value: 'stock_qty' }, { label: 'product_code' }, {}, // a part missing
      { value: 'description', label: 'product_code' }, // the value is no number
      { value: 'stock_qty', label: 'stock_qty' }, // the same column twice
      { value: 'stock_qty', label: 'item_group' }, // a label repeated on several rows (no series)
    ]) {
      expect(pickChart(STOCK.headers, STOCK.rows, 'bar', null, false, columns)).toEqual(old)
    }
    expect(pickChart(STOCK.headers, STOCK.rows, 'bar', null, false, null)).toEqual(old)
  })

  it('ignores a series that is not in the rows, and draws the value and the label', () => {
    const pick = pickChart(STOCK.headers, STOCK.rows, null, null, false,
      { value: 'stock_qty', label: 'product_code', series: 'warehouse' })
    expect(pick).toMatchObject({ x: 'product_code', ys: ['stock_qty'], group: '' })
  })

  it('splits by the named series, the label along the axis as named', () => {
    // the rules would put product_category along the axis; the AI names sale_type there, the categories as the series
    const pick = pickChart(CATEGORY_SALE_TYPE.headers, CATEGORY_SALE_TYPE.rows, 'grouped', false, false,
      { value: 'net_sales_inr', label: 'sale_type', series: 'product_category' })
    expect(pick).toMatchObject({ kind: 'grouped', x: 'sale_type', group: 'product_category', amount: 'net_sales_inr' })
    expect(pick?.data.map((p) => p.label)).toEqual(['Domestic', 'Export', 'Service'])
    expect(pick?.ys).toHaveLength(8)
  })

  it('still draws when the rules alone find no chart (the value is a count-like name)', () => {
    const rows = table([['product_code', false], ['order_no', true]], [['A-1', '5'], ['A-2', '7'], ['A-3', '2']])
    expect(pickChart(rows.headers, rows.rows)).toBeNull() // order_no reads as a number of a document
    expect(pickChart(rows.headers, rows.rows, null, null, false, { value: 'order_no', label: 'product_code' }))
      .toMatchObject({ x: 'product_code', ys: ['order_no'] })
  })
})

describe('splitSeries: series that do not belong on one chart', () => {
  const labels = (headers: Header[], rows: Cell[][], columns: ChartColumns, want: ChartKind | null = null) =>
    pickChart(headers, rows, want, null, false, columns)!.data.map((p) => p.label)

  it('labelKind: dates, months, years, quarters, periods, numbers, text', () => {
    expect(['2026-10-21', '21-Oct-2026', '31/10/2026'].map(labelKind)).toEqual(['date', 'date', 'date'])
    expect(['May 2026', 'Oct', 'Sep-26', '2026-01'].map(labelKind)).toEqual(['month', 'month', 'month', 'month'])
    expect(['2026', 'FY 2025-26', '2025-26'].map(labelKind)).toEqual(['year', 'year', 'year'])
    expect(['Q1', 'Q2 FY 2026-27', 'Week 12', '42', 'Coolant pumps'].map(labelKind))
      .toEqual(['quarter', 'quarter', 'period', 'number', 'text'])
  })

  it('daily + monthly rows (dates vs months, no label in common, 10x apart): 2 charts, each with only its own labels', () => {
    const { headers, rows } = DAILY_MONTHLY
    // one chart before: 17 points, dates and months on one axis
    expect(pickChart(headers, rows, 'line', null, false, DAILY_MONTHLY_COLUMNS)!.data).toHaveLength(17)
    const parts = splitSeries(headers, rows, 'line', false, DAILY_MONTHLY_COLUMNS)!
    expect(parts.map((p) => [p.name, p.rows.length, p.kind])).toEqual([['daily', 11, 'line'], ['monthly', 6, 'line']])
    expect(parts[0].columns).toEqual({ value: 'net_sales_inr', label: 'period_label' })
    const [daily, monthly] = parts.map((p) => labels(headers, p.rows, p.columns, p.kind))
    expect(daily).toEqual(['2026-10-21', '2026-10-22', '2026-10-23', '2026-10-24', '2026-10-25', '2026-10-26',
      '2026-10-27', '2026-10-28', '2026-10-29', '2026-10-30', '2026-10-31'])
    expect(monthly).toEqual(['May 2026', 'Jun 2026', 'Jul 2026', 'Aug 2026', 'Sep 2026', 'Oct 2026'])
    expect(pickChart(headers, parts[1].rows, 'line', null, false, parts[1].columns)).toMatchObject({ kind: 'line', ys: ['net_sales_inr'] })
  })

  it("the same rows without the AI's columns: the label kinds (dates vs months) still split them", () => {
    const parts = splitSeries(DAILY_MONTHLY.headers, DAILY_MONTHLY.rows)!
    expect(parts.map((p) => [p.name, p.rows.length])).toEqual([['daily', 11], ['monthly', 6]])
  })

  it('this year vs last year per month (the same labels and size): one chart, as before', () => {
    expect(splitSeries(TWO_YEARS.headers, TWO_YEARS.rows, 'line', false, TWO_YEARS_COLUMNS)).toBeNull()
    expect(splitSeries(TWO_YEARS.headers, TWO_YEARS.rows, null, false, TWO_YEARS_COLUMNS)).toBeNull()
    expect(pickChart(TWO_YEARS.headers, TWO_YEARS.rows, 'line', null, false, TWO_YEARS_COLUMNS))
      .toMatchObject({ kind: 'line', ys: ['FY 2025-26', 'FY 2026-27'], group: 'fy' })
  })

  it('the same labels but values over 10x apart: a chart each (own y-scale) - not for a stacked view', () => {
    const { headers, rows } = SALES_RETURNS
    const parts = splitSeries(headers, rows, null, false, SALES_RETURNS_COLUMNS)!
    expect(parts.map((p) => [p.name, p.rows.length])).toEqual([['Sales', 4], ['Returns', 4]])
    expect(parts.map((p) => labels(headers, p.rows, p.columns))).toEqual([['Apr', 'May', 'Jun', 'Jul'], ['Apr', 'May', 'Jun', 'Jul']])
    // a stacked chart adds them up: they stay together
    expect(splitSeries(headers, rows, 'stacked', false, SALES_RETURNS_COLUMNS)).toBeNull()
    // grouped bars asked: each chart of one series is drawn as bars
    expect(splitSeries(headers, rows, 'grouped', false, SALES_RETURNS_COLUMNS)!.map((p) => p.kind)).toEqual(['bar', 'bar'])
  })

  it('keeps the series that belong together on one chart (two years together, the daily one apart)', () => {
    const daily = table([['fy', false], ['month_name', false], ['net_sales_inr', true]],
      DAILY_MONTHLY.rows.slice(0, 11).map(([, day]) => ['daily', day.text, '42,000,000.00']))
    const rows = [...TWO_YEARS.rows, ...daily.rows]
    const parts = splitSeries(TWO_YEARS.headers, rows, 'line', false, TWO_YEARS_COLUMNS)!
    expect(parts.map((p) => [p.name, p.rows.length, p.columns.series])).toEqual([
      ['FY 2025-26 and FY 2026-27', 8, 'fy'], ['daily', 11, undefined]])
    expect(pickChart(TWO_YEARS.headers, parts[0].rows, 'line', null, false, parts[0].columns))
      .toMatchObject({ kind: 'line', ys: ['FY 2025-26', 'FY 2026-27'] })
  })

  it('no series, too many series, a series of 1 row, or text labels only: no split (one chart, as before)', () => {
    expect(splitSeries(MONTHLY.headers, MONTHLY.rows)).toBeNull()
    expect(splitSeries(TOP5.headers, TOP5.rows)).toBeNull()
    expect(splitSeries(SALE_TYPES.headers, SALE_TYPES.rows)).toBeNull()
    expect(splitSeries(CATEGORY_SALE_TYPE.headers, CATEGORY_SALE_TYPE.rows)).toBeNull() // Service has 1 row
    // 5 series of dates vs months: more than MAX_SPLIT stays one chart
    const five = table([['series', false], ['label', false], ['v', true]],
      ['a', 'b', 'c', 'd', 'e'].flatMap((s, i) => (i % 2 ? ['May 2026', 'Jun 2026'] : ['2026-10-21', '2026-10-22'])
        .map((label, j) => [s, label, String(100 * (i + 1) + j)])))
    expect(splitSeries(five.headers, five.rows, null, false, { value: 'v', label: 'label', series: 'series' })).toBeNull()
    // one label, customers in different regions (no label in common, but the same kind of label): one chart
    const regions = table([['customer_name', false], ['region', false], ['sales_inr', true]], [
      ['Shree Auto', 'North', '100.00'], ['Tata AutoComp', 'North', '90.00'],
      ['Lucas TVS', 'South', '80.00'], ['Mahindra CIE', 'South', '5.00']])
    expect(splitSeries(regions.headers, regions.rows)).toBeNull()
  })
})

describe('splitSeries: each series with its own value column', () => {
  const { headers, rows } = OWN_VALUE_COLUMNS
  const MONTHS = ['May 2026', 'Jun 2026', 'Jul 2026', 'Aug 2026', 'Sep 2026', 'Oct 2026']
  const DAYS = ['2026-10-21', '2026-10-22', '2026-10-23', '2026-10-24', '2026-10-26', '2026-10-27', '2026-10-28',
    '2026-10-29', '2026-10-30', '2026-10-31']
  const drawn = (part: { rows: Cell[][]; columns: ChartColumns; kind: ChartKind | null }) =>
    pickChart(headers, part.rows, part.kind, null, false, part.columns)!

  it('the real answer (last 6 months + last month day-wise) is no one chart: 2 charts, one per series', () => {
    expect(pickChart(headers, rows)).toBeNull() // before: "This answer can't be drawn as a chart."
    const parts = splitSeries(headers, rows, 'line')!
    expect(parts.map((p) => [p.name, p.rows.length, p.kind])).toEqual([['last_6_months', 6, 'line'], ['last_month', 10, 'line']])
    // the value column each series fills; the label: 'label' for the months, period_start for the days ('label'
    // repeats 'Nov 2026' there)
    expect(parts.map((p) => p.columns)).toEqual([
      { value: 'net_sales_inr', label: 'label' }, { value: 'daily_sales_inr', label: 'period_start' }])
    const [months, days] = parts.map(drawn)
    expect(months).toMatchObject({ kind: 'line', x: 'label', ys: ['net_sales_inr'], time: true })
    expect(days).toMatchObject({ kind: 'line', x: 'period_start', ys: ['daily_sales_inr'], time: true })
    expect(months.data.map((p) => p.label)).toEqual(MONTHS)
    expect(days.data.map((p) => p.label)).toEqual(DAYS)
    expect(months.data.map((p) => p.values)).toEqual([[459457491.7], [514347284.15], [434659336.5], [466556045.75],
      [472683542.23], [517494492.75]])
    expect(days.data[0].values).toEqual([11592826]) // only its own column: no null line
    expect([...months.data, ...days.data].every((p) => p.values.length === 1 && p.values[0] !== null)).toBe(true)
  })

  it("the same with or without the AI's columns, and with dates as the server writes them (21-Oct-2026)", () => {
    const want = (columns: ChartColumns | null) => splitSeries(headers, rows, null, false, columns)!.map((p) => [p.name, p.columns])
    const expected = [['last_6_months', { value: 'net_sales_inr', label: 'label' }],
      ['last_month', { value: 'daily_sales_inr', label: 'period_start' }]]
    expect(want(null)).toEqual(expected)
    expect(want({ value: 'net_sales_inr', label: 'label', series: 'chart_type' })).toEqual(expected)
    expect(want({ value: 'daily_sales_inr', label: 'period_start' })).toEqual([
      ['last_6_months', { value: 'net_sales_inr', label: 'period_start' }],
      ['last_month', { value: 'daily_sales_inr', label: 'period_start' }]])
    const iso = /^(\d{4})-(\d{2})-(\d{2})$/
    const names = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    const written = rows.map((row) => row.map((cell) => {
      const m = iso.exec(cell.text)
      return m ? { ...cell, text: `${m[3]}-${names[Number(m[2])]}-${m[1]}` } : cell
    }))
    const parts = splitSeries(headers, written, 'line')!
    expect(parts.map((p) => p.columns.label)).toEqual(['label', 'period_start'])
    expect(drawn(parts[1]).data.map((p) => p.label)).toEqual(['21-Oct-2026', '22-Oct-2026', '23-Oct-2026', '24-Oct-2026',
      '26-Oct-2026', '27-Oct-2026', '28-Oct-2026', '29-Oct-2026', '30-Oct-2026', '31-Oct-2026'])
  })

  it('a start column is the label before an end column, whatever their order', () => {
    const order = [0, 3, 2, 1, 4, 5] // chart_type, period_end, period_start, label, ...
    const moved = { headers: order.map((i) => headers[i]), rows: rows.map((row) => order.map((i) => row[i])) }
    expect(splitSeries(moved.headers, moved.rows)!.map((p) => p.columns.label)).toEqual(['label', 'period_start'])
  })

  it('two amounts filled on the same rows (invoices and credit notes per month): a normal 2-line chart, no split', () => {
    const both = table([['month', false], ['invoice_value_inr', true], ['credit_note_value_inr', true]], [
      ['May 2026', '45,000,000.00', '1,200,000.00'], ['Jun 2026', '51,000,000.00', '900,000.00'],
      ['Jul 2026', '43,000,000.00', '1,500,000.00'], ['Aug 2026', '46,500,000.00', '1,100,000.00']])
    expect(splitSeries(both.headers, both.rows, 'line')).toBeNull()
    expect(pickChart(both.headers, both.rows, 'line')).toMatchObject({
      kind: 'line', x: 'month', ys: ['invoice_value_inr', 'credit_note_value_inr'] })
    // the same with a series column (two plants) whose rows fill both amounts: not split by value column
    const plants = table([['plant', false], ['month', false], ['invoice_value_inr', true], ['credit_note_value_inr', true]],
      ['Plant A', 'Plant B'].flatMap((plant) => both.rows.map(([month, inv, cn]) => [plant, month.text, inv.text, cn.text])))
    expect(splitSeries(plants.headers, plants.rows, 'line')).toBeNull()
    // one series fills both, the other only one: not "each series has its own value column"
    const mixed = table([['kind', false], ['month', false], ['a_inr', true], ['b_inr', true]], [
      ['x', 'May 2026', '10.00', '5.00'], ['x', 'Jun 2026', '12.00', '6.00'],
      ['y', 'May 2026', '-', '7.00'], ['y', 'Jun 2026', '-', '8.00']])
    expect(splitSeries(mixed.headers, mixed.rows)).toBeNull()
  })
})
