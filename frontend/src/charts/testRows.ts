// Answer rows for the chart tests, as /api/questions/<id>/rows sends them.
import type { Cell, Header } from '../types'

/** A rows table as /api/questions/<id>/rows sends it: [name, num] headers and the display texts. */
export function table(columns: [string, boolean][], texts: string[][]): { headers: Header[]; rows: Cell[][] } {
  return {
    headers: columns.map(([name, num]) => ({ name, num })),
    rows: texts.map((row) => row.map((text, i) => ({ text, num: columns[i][1] }))),
  }
}

// monthly net sales, Jan 2026 to Mar 2027 (first, second and last rows real; the middle ones made up)
const MONTHS: [string, string][] = [
  ['Jan 2026', '13,356,235.00'], ['Feb 2026', '9,032,845.00'], ['Mar 2026', '41,250,118.40'],
  ['Apr 2026', '120,450,300.00'], ['May 2026', '180,005,222.15'], ['Jun 2026', '205,330,410.00'],
  ['Jul 2026', '240,118,900.75'], ['Aug 2026', '260,700,001.00'], ['Sep 2026', '255,980,450.00'],
  ['Oct 2026', '290,442,120.30'], ['Nov 2026', '310,005,600.00'], ['Dec 2026', '330,870,245.10'],
  ['Jan 2027', '345,120,000.00'], ['Feb 2027', '362,450,980.20'], ['Mar 2027', '3,503,352,034.65'],
]
export const MONTHLY = table(
  [['sales_period_no', true], ['month', false], ['net_sales_inr', true], ['period_start', false],
    ['period_end', false], ['data_from', false], ['data_to', false]],
  MONTHS.map(([month, sales], i) => [
    String(i + 1), month, sales, '21-Dec-2025', '20-Jan-2026', '21-Dec-2025', '31-Mar-2027',
  ]),
)

export const TOP5 = table(
  [['customer_code', false], ['customer_name', false], ['invoice_value_inr', true], ['invoice_count', true]],
  [
    ['C1001', 'Hindustan Precision Engineering Pvt Ltd', '125,400,000.00', '42'],
    ['C1002', 'Shree Auto Components', '98,250,500.50', '31'],
    ['C1003', 'Tata AutoComp Systems Ltd', '45,000,000.00', '12'],
    ['C1004', 'Mahindra CIE Automotive', '3,250,000.00', '8'],
    ['C1005', 'Lucas TVS Limited', '850,000.00', '2'],
  ],
)

// a real answer with two labels + an amount (net sales by product category and sale type): a pivot
const CATEGORY_SALES: [string, string, string][] = [
  ['Coolant pumps', 'Domestic', '20,321,380.00'], ['Coolant pumps', 'Export', '1,783,650.00'],
  ['Coolant Units', 'Domestic', '12,169,380.00'], ['Coolant Units', 'Export', '4,826,080.00'],
  ['GCI', 'Domestic', '14,952,355.00'], ['GCI', 'Export', '3,103,190.00'],
  ['Hydraulic motors', 'Domestic', '15,937,975.00'], ['Hydraulic motors', 'Export', '2,455,300.00'],
  ['Not classified', 'Domestic', '3,314,096,846.50'], ['Not classified', 'Export', '667,910,761.50'],
  ['Not classified', 'Service', '871,750.00'],
  ['Procon Pumps', 'Domestic', '8,946,815.00'], ['Procon Pumps', 'Export', '768,475.00'],
  ['Trochoid pumps', 'Domestic', '21,369,867.50'], ['Trochoid pumps', 'Export', '3,061,845.00'],
  ['YTH-PARTS', 'Domestic', '18,012,293.00'], ['YTH-PARTS', 'Export', '3,225,990.00'],
]
export const CATEGORY_SALE_TYPE = table(
  [['product_category', false], ['sale_type', false], ['net_sales_inr', true]], CATEGORY_SALES)

export const SALE_TYPES = table(
  [['sale_type', false], ['net_sales_inr', true], ['data_from', false], ['data_to', false]],
  [
    ['Domestic', '2,450,000,000.00', '21-Dec-2025', '31-Mar-2027'],
    ['Export', '980,500,000.00', '21-Dec-2025', '31-Mar-2027'],
    ['Service', '72,852,034.65', '21-Dec-2025', '31-Mar-2027'],
  ],
)

// 23-Nov: "2 line charts: last 6 months sales and last month day-wise" came back as ONE result: a series column
// (daily / monthly), labels mixing dates and months, daily 1-4 Cr vs monthly 43-52 Cr
const DAYS: [string, string][] = [
  ['2026-10-21', '12,450,300.00'], ['2026-10-22', '18,005,222.15'], ['2026-10-23', '23,330,410.00'],
  ['2026-10-24', '31,118,900.75'], ['2026-10-25', '9,700,001.00'], ['2026-10-26', '25,980,450.00'],
  ['2026-10-27', '40,442,120.30'], ['2026-10-28', '15,005,600.00'], ['2026-10-29', '33,870,245.10'],
  ['2026-10-30', '28,120,000.00'], ['2026-10-31', '36,450,980.20'],
]
const SALES_MONTHS: [string, string][] = [
  ['May 2026', '432,100,000.00'], ['Jun 2026', '455,800,250.00'], ['Jul 2026', '498,300,000.00'],
  ['Aug 2026', '521,450,600.00'], ['Sep 2026', '470,005,000.00'], ['Oct 2026', '512,880,400.00'],
]
export const DAILY_MONTHLY = table(
  [['series', false], ['period_label', false], ['net_sales_inr', true]],
  [...DAYS.map(([day, sales]) => ['daily', day, sales]), ...SALES_MONTHS.map(([month, sales]) => ['monthly', month, sales])],
)
export const DAILY_MONTHLY_COLUMNS = { value: 'net_sales_inr', label: 'period_label', series: 'series' }

// this year vs last year per month: the same labels, the same size - one chart
export const TWO_YEARS = table(
  [['fy', false], ['month_name', false], ['net_sales_inr', true]],
  [['Apr', '41,200,000.00', '45,800,000.00'], ['May', '43,900,000.00', '47,100,000.00'],
    ['Jun', '40,150,000.00', '49,300,000.00'], ['Jul', '44,700,000.00', '51,000,000.00']]
    .flatMap(([month, last, now]) => [['FY 2025-26', month, last], ['FY 2026-27', month, now]]),
)
export const TWO_YEARS_COLUMNS = { value: 'net_sales_inr', label: 'month_name', series: 'fy' }

// sales vs returns per month: the same labels, values ~25x apart
export const SALES_RETURNS = table(
  [['kind', false], ['month_name', false], ['amount_inr', true]],
  [['Apr', '52,000,000.00', '2,100,000.00'], ['May', '49,500,000.00', '1,800,000.00'],
    ['Jun', '55,250,000.00', '2,400,000.00'], ['Jul', '51,000,000.00', '1,950,000.00']]
    .flatMap(([month, sales, returns]) => [['Sales', month, sales], ['Returns', month, returns]]),
)
export const SALES_RETURNS_COLUMNS = { value: 'amount_inr', label: 'month_name', series: 'kind' }

// 23-Nov (real, local model): "Create 2 line charts: one for last 6 months sales and another for last month
// day-wise sales" - one result where each series has its OWN value column (the other one null, '-' in the table):
// last_6_months fills net_sales_inr (labels May..Oct 2026), last_month fills daily_sales_inr (its label repeats
// 'Nov 2026', the day is in period_start). Null cells come as '-' with num false, as the server sends them.
const SIX_MONTHS: [string, string, string, string][] = [
  ['May 2026', '2026-04-21', '2026-05-20', '459,457,491.70'], ['Jun 2026', '2026-05-21', '2026-06-20', '514,347,284.15'],
  ['Jul 2026', '2026-06-21', '2026-07-20', '434,659,336.50'], ['Aug 2026', '2026-07-21', '2026-08-20', '466,556,045.75'],
  ['Sep 2026', '2026-08-21', '2026-09-20', '472,683,542.23'], ['Oct 2026', '2026-09-21', '2026-10-20', '517,494,492.75'],
]
const LAST_MONTH_DAYS: [string, string][] = [
  ['2026-10-21', '11,592,826.00'], ['2026-10-22', '14,555,036.00'], ['2026-10-23', '17,611,305.50'],
  ['2026-10-24', '15,529,002.00'], ['2026-10-26', '41,466,448.00'], ['2026-10-27', '13,662,908.50'],
  ['2026-10-28', '20,957,202.00'], ['2026-10-29', '17,462,856.50'], ['2026-10-30', '20,823,662.50'],
  ['2026-10-31', '15,608,278.00'],
]
const OWN_VALUE_TABLE = table(
  [['chart_type', false], ['label', false], ['period_start', false], ['period_end', false],
    ['net_sales_inr', true], ['daily_sales_inr', true]],
  [...SIX_MONTHS.map(([month, start, end, sales]) => ['last_6_months', month, start, end, sales, '-']),
    ...LAST_MONTH_DAYS.map(([day, sales]) => ['last_month', 'Nov 2026', day, day, '-', sales])],
)
export const OWN_VALUE_COLUMNS = {
  headers: OWN_VALUE_TABLE.headers,
  rows: OWN_VALUE_TABLE.rows.map((row) => row.map((cell) => (cell.text === '-' ? { text: '-', num: false } : cell))),
}
