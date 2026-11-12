// Apache ECharts with only the chart types and parts the answer charts use (echarts/core keeps the
// lazy chart file small). The AI chart adds a few more (echartsAi.ts). Tests swap this file for a fake
// (src/test/fakeEcharts.ts): jsdom has no canvas.
import { BarChart, FunnelChart, HeatmapChart, LineChart, PieChart, RadarChart, ScatterChart, TreemapChart } from 'echarts/charts'
import { GridComponent, LegendComponent, RadarComponent, TooltipComponent, VisualMapContinuousComponent } from 'echarts/components'
import { init as initChart, use } from 'echarts/core'
import type { EChartsCoreOption, EChartsType } from 'echarts/core'
import { LabelLayout } from 'echarts/features'
import { CanvasRenderer } from 'echarts/renderers'

// LabelLayout: the treemap's labelLayout (no label in a box too small for it). echarts/core says it adds it
// itself, but the bundler drops that line, so it is added here
use([
  BarChart, LineChart, PieChart, TreemapChart, HeatmapChart, ScatterChart, FunnelChart, RadarChart,
  GridComponent, TooltipComponent, LegendComponent, VisualMapContinuousComponent, RadarComponent, CanvasRenderer,
  LabelLayout,
])

export type { EChartsCoreOption, EChartsType }

/** A chart drawn on a canvas in this box (getDataURL gives its PNG). */
export function init(dom: HTMLElement): EChartsType {
  return initChart(dom, null, { renderer: 'canvas' })
}
