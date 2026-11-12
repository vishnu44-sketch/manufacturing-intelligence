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
  [['nop_sales_period_no', true], ['month', false], ['net_sales_inr', true], ['period_start', false],
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
