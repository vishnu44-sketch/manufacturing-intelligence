// A thin React box around one ECharts chart: init when it appears, setOption when the option changes,
// resize with its box, dispose when it goes. onReady gives the chart (for Download PNG: getDataURL); onClick
// gets ECharts' click (the treemap's drill-down).
import { useEffect, useRef } from 'react'
import { type EChartsCoreOption, type EChartsType, init } from './echarts'

export interface EChartProps {
  option: EChartsCoreOption
  height: number
  onReady?: (chart: EChartsType | null) => void
  onWidth?: (width: number) => void // the box's width (a phone draws a smaller chart)
  onClick?: (params: unknown, chart: EChartsType) => void
}

export default function EChart({ option, height, onReady, onWidth, onClick }: EChartProps) {
  const box = useRef<HTMLDivElement>(null)
  const chart = useRef<EChartsType | null>(null)
  const callbacks = useRef({ onReady, onWidth, onClick })
  callbacks.current = { onReady, onWidth, onClick }

  useEffect(() => {
    const dom = box.current
    if (!dom) return
    const made = init(dom)
    chart.current = made
    made.on('click', (params) => callbacks.current.onClick?.(params, made))
    callbacks.current.onReady?.(made)
    callbacks.current.onWidth?.(dom.clientWidth)
    // jsdom (the tests) has no ResizeObserver
    const watch = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
      made.resize()
      callbacks.current.onWidth?.(dom.clientWidth)
    })
    watch?.observe(dom)
    return () => {
      watch?.disconnect()
      made.dispose()
      chart.current = null
      callbacks.current.onReady?.(null)
    }
  }, [])

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true }) // the whole option each time (a new kind)
  }, [option])

  useEffect(() => {
    chart.current?.resize()
  }, [height])

  return <div ref={box} className="echart" style={{ width: '100%', height }} />
}
