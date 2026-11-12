// The ECharts 'graph' series (with its force layout) for the Knowledge graph page: loaded only with the graph
// (charts/GraphChart.tsx), so the answer charts' file stays as small as before. Tests mock this file away.
import { GraphChart } from 'echarts/charts'
import { use } from 'echarts/core'

use([GraphChart])
