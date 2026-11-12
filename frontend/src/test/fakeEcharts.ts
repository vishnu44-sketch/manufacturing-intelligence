// A stand-in for src/charts/echarts.ts in the tests (jsdom has no canvas): it keeps every chart made and
// the option it was given, so a test can check what would be drawn. Use it with
//   vi.mock('../charts/echarts', () => import('../test/fakeEcharts'))
import { vi } from 'vitest'

type Option = Record<string, any>

export class FakeChart {
  dom: HTMLElement
  option: Option | null = null
  disposed = false
  resize = vi.fn()
  on = vi.fn() // on('click', handler): a test can call the handler
  dispatchAction = vi.fn()
  getDataURL = vi.fn((_opts?: unknown) => 'data:image/png;base64,iVBORw0KGgo=')
  constructor(dom: HTMLElement) {
    this.dom = dom
  }
  setOption(option: Option) {
    this.option = option
  }
  dispose() {
    this.disposed = true
  }
  /** The series types drawn: ['bar', 'bar'] */
  types(): string[] {
    const series = this.option?.series
    return (Array.isArray(series) ? series : series ? [series] : []).map((s: Option) => s.type)
  }
}

export const charts: FakeChart[] = []

export function init(dom: HTMLElement) {
  const chart = new FakeChart(dom)
  charts.push(chart)
  return chart
}

/** The last chart that is still on the page. */
export function lastChart(): FakeChart {
  const live = charts.filter((c) => !c.disposed)
  return live[live.length - 1]
}
