import * as echarts from "echarts/core";
import { CandlestickChart, LineChart, BarChart, HeatmapChart, ScatterChart, RadarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkPointComponent,
  ToolboxComponent,
  MarkLineComponent,
  MarkAreaComponent,
  VisualMapComponent,
  RadarComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  CandlestickChart, LineChart, BarChart, HeatmapChart, ScatterChart, RadarChart,
  GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, MarkPointComponent,
  ToolboxComponent, MarkLineComponent, MarkAreaComponent,
  VisualMapComponent, RadarComponent,
  CanvasRenderer,
]);

export const CHART_GROUP = "quant-charts";

// Canvas text ignores page CSS; register the page font stack as the default
// theme so chart legends/labels render Chinese in Noto Sans SC like the DOM.
const BRAND_FONT = 'Inter, "Noto Sans SC", system-ui, sans-serif';
echarts.registerTheme("alpha-mind", { textStyle: { fontFamily: BRAND_FONT } });

// The ESM namespace is frozen, so expose a patched copy whose init()
// falls back to the brand theme when the caller doesn't pass one.
const patchedEcharts = {
  ...echarts,
  init: ((dom, theme, opts) =>
    echarts.init(dom, theme ?? "alpha-mind", opts)) as typeof echarts.init,
};

let _connected = false;

export function connectCharts() {
  if (!_connected) {
    echarts.connect(CHART_GROUP);
    _connected = true;
  }
}

export { patchedEcharts as echarts };
