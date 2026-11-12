// The extra ECharts parts an AI chart may use (a sankey, a gauge, a target line ...): loaded only with the
// AI chart. These are the series types and keys the server lets through (portal/charts.py).
import {
  BoxplotChart, CandlestickChart, EffectScatterChart, GaugeChart, GraphChart, PictorialBarChart, SankeyChart,
  SunburstChart, TreeChart,
} from 'echarts/charts'
import {
  DatasetComponent, MarkAreaComponent, MarkLineComponent, MarkPointComponent, PolarComponent, TitleComponent,
  TransformComponent, VisualMapPiecewiseComponent,
} from 'echarts/components'
import { use } from 'echarts/core'

use([
  SankeyChart, SunburstChart, BoxplotChart, GaugeChart, CandlestickChart, EffectScatterChart, PictorialBarChart,
  GraphChart, TreeChart, TitleComponent, DatasetComponent, TransformComponent, MarkLineComponent, MarkPointComponent,
  MarkAreaComponent, PolarComponent, VisualMapPiecewiseComponent,
])
