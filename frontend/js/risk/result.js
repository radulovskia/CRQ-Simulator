const SIMULATION_RESULT_KEY = "crqSimulationResult";

const statusBox = document.getElementById("status");
const emptyState = document.getElementById("empty-state");
const resultsSection = document.getElementById("results");
const sharedStats = document.getElementById("shared-stats");
const frequencyStats = document.getElementById("frequency-stats");
const magnitudeStats = document.getElementById("magnitude-stats");
const aggregateStats = document.getElementById("aggregate-stats");
const frequencyDetails = document.getElementById("frequency-details");
const magnitudeDetails = document.getElementById("magnitude-details");
const exportPdfButton = document.getElementById("export-pdf-button");

let lastSimulationData = null;
const screenCharts = [];

const PDF_MARGIN = 14;
const PDF_ROW_HEIGHT = 3.8;
const PDF_SECTION_GAP = 3;
const PDF_COLUMN_GAP = 5;
const PDF_BLOCK_GAP = 5;
const PDF_CHART_HEADER_HEIGHT = 9.5;
// Off-screen PDF charts are laid out at 4 CSS px per mm and rasterized at 4x,
// which gives ~400 DPI images with chart text at a legible ~7-8 pt.
const PDF_PX_PER_MM = 4;
const PDF_PIXEL_RATIO = 4;

const numberFormatter = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 2,
});

const percentFormatter = new Intl.NumberFormat(undefined, {
  style: "percent",
  maximumFractionDigits: 1,
});

const compactFormatter = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 2,
});

const densityFormatter = new Intl.NumberFormat(undefined, {
  maximumSignificantDigits: 4,
});

const FONT_FAMILY = 'Inter, system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif';

const SCREEN_THEME = {
  name: "screen",
  text: "#cbd5e1",
  muted: "#94a3b8",
  strong: "#f1f5f9",
  axisLine: "#475569",
  splitLine: "rgba(148, 163, 184, 0.12)",
  tooltipBackground: "rgba(11, 18, 32, 0.96)",
  tooltipBorder: "#334155",
  saveBackground: "#0b1220",
  fontSize: 12,
  smallFontSize: 11,
  symbolSize: 5,
  colors: {
    frequency: "#38bdf8",
    magnitude: "#4ade80",
    aggregate: "#fbbf24",
    exceedance: "#f59e0b",
    p5: "#a78bfa",
    mean: "#e2e8f0",
    p95: "#f87171",
    var95: "#f87171",
    var99: "#fb923c",
    tvar95: "#f472b6",
    tvar99: "#c084fc",
    bound: "#64748b",
    lossScale: ["#22d3ee", "#a3e635", "#facc15", "#f97316", "#ef4444"],
  },
};

const PRINT_THEME = {
  name: "print",
  text: "#334155",
  muted: "#64748b",
  strong: "#0f172a",
  axisLine: "#94a3b8",
  splitLine: "#e2e8f0",
  tooltipBackground: "#ffffff",
  tooltipBorder: "#cbd5e1",
  saveBackground: "#ffffff",
  fontSize: 11,
  smallFontSize: 10,
  symbolSize: 3.5,
  colors: {
    frequency: "#0284c7",
    magnitude: "#16a34a",
    aggregate: "#d97706",
    exceedance: "#d97706",
    p5: "#7c3aed",
    mean: "#0f172a",
    p95: "#dc2626",
    var95: "#dc2626",
    var99: "#ea580c",
    tvar95: "#db2777",
    tvar99: "#9333ea",
    bound: "#94a3b8",
    lossScale: ["#0891b2", "#65a30d", "#ca8a04", "#ea580c", "#dc2626"],
  },
};

function setStatus(message, type = "success") {
  statusBox.hidden = false;
  statusBox.textContent = message;
  statusBox.className = `status ${type}`;
}

function clearStatus() {
  statusBox.hidden = true;
  statusBox.textContent = "";
  statusBox.className = "status";
}

function renderStat(label, value) {
  const card = document.createElement("article");
  card.className = "stat-card";
  card.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
  return card;
}

function renderDetail(label, value) {
  const item = document.createElement("div");
  item.innerHTML = `<dt>${label}</dt><dd>${value}</dd>`;
  return item;
}

function formatStatValue(label, value) {
  if (label === "Seed") {
    return String(value);
  }
  return numberFormatter.format(value);
}

function formatCompact(value) {
  return compactFormatter.format(value);
}

function formatMoneyCompact(value) {
  return value < 0 ? `-$${compactFormatter.format(-value)}` : `$${compactFormatter.format(value)}`;
}

function formatMoney(value) {
  return value < 0 ? `-$${numberFormatter.format(-value)}` : `$${numberFormatter.format(value)}`;
}

// ---------------------------------------------------------------------------
// Beta PERT math
// ---------------------------------------------------------------------------

const LANCZOS_COEFFICIENTS = [
  676.5203681218851, -1259.1392167224028, 771.32342877765313, -176.61502916214059,
  12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7,
];

function logGamma(value) {
  if (value < 0.5) {
    return Math.log(Math.PI / Math.sin(Math.PI * value)) - logGamma(1 - value);
  }
  const x = value - 1;
  let sum = 0.99999999999980993;
  LANCZOS_COEFFICIENTS.forEach((coefficient, index) => {
    sum += coefficient / (x + index + 1);
  });
  const t = x + LANCZOS_COEFFICIENTS.length - 0.5;
  return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(sum);
}

function betaPdf(unit, alpha, beta) {
  const logPdf =
    (alpha - 1) * Math.log(unit) +
    (beta - 1) * Math.log(1 - unit) -
    (logGamma(alpha) + logGamma(beta) - logGamma(alpha + beta));
  return Math.exp(logPdf);
}

function pertMean(distribution) {
  const { minimum, mode, maximum, lambda_param: lambda } = distribution;
  return (minimum + lambda * mode + maximum) / (lambda + 2);
}

function buildPertCurve(distribution, pointCount = 241) {
  const { minimum, maximum, alpha, beta } = distribution;
  const span = maximum - minimum;
  const epsilon = 1e-6;
  const points = [];

  for (let index = 0; index < pointCount; index += 1) {
    const unit = Math.min(Math.max(index / (pointCount - 1), epsilon), 1 - epsilon);
    const value = minimum + span * (index / (pointCount - 1));
    points.push({ value, density: betaPdf(unit, alpha, beta) / span });
  }

  const peak = Math.max(...points.map((point) => point.density), Number.MIN_VALUE);
  let cumulative = 0;
  points.forEach((point, index) => {
    if (index > 0) {
      const previous = points[index - 1];
      cumulative += ((previous.density + point.density) / 2) * (point.value - previous.value);
    }
    point.cumulative = cumulative;
    point.relative = point.density / peak;
  });
  points.forEach((point) => {
    point.cumulative = cumulative > 0 ? point.cumulative / cumulative : 0;
  });

  return points;
}

// ---------------------------------------------------------------------------
// ECharts option builders
// ---------------------------------------------------------------------------

function withAlpha(hex, alpha) {
  const value = Number.parseInt(hex.slice(1), 16);
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

function verticalGradient(color, topAlpha, bottomAlpha) {
  return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: withAlpha(color, topAlpha) },
    { offset: 1, color: withAlpha(color, bottomAlpha) },
  ]);
}

function tooltipHtml(theme, title, rows) {
  const heading = `<div style="margin-bottom:6px;color:${theme.muted};font-size:11px;font-weight:700;letter-spacing:0.05em;text-transform:uppercase">${title}</div>`;
  const body = rows
    .map(
      ([label, value]) =>
        `<div style="display:flex;justify-content:space-between;gap:18px;line-height:1.6"><span style="color:${theme.muted}">${label}</span><span style="color:${theme.strong};font-weight:600">${value}</span></div>`,
    )
    .join("");
  return heading + body;
}

function baseOption(theme, interactive, { trigger = "item", saveName = "chart" } = {}) {
  const option = {
    animation: interactive,
    animationDuration: 500,
    backgroundColor: "transparent",
    textStyle: { fontFamily: FONT_FAMILY, color: theme.text, fontSize: theme.fontSize },
    tooltip: {
      show: interactive,
      trigger,
      confine: true,
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      borderWidth: 1,
      padding: [10, 12],
      textStyle: { color: theme.strong, fontSize: 12, fontFamily: FONT_FAMILY },
      extraCssText: "border-radius:10px;box-shadow:0 12px 30px rgba(2,6,23,0.45);",
      axisPointer: {
        type: "line",
        lineStyle: { color: theme.muted, type: "dashed", width: 1 },
      },
    },
  };

  if (interactive) {
    option.toolbox = {
      right: 0,
      top: 0,
      itemSize: 14,
      itemGap: 10,
      iconStyle: { borderColor: theme.muted },
      emphasis: { iconStyle: { borderColor: theme.strong } },
      feature: {
        saveAsImage: {
          title: "Save image",
          name: saveName,
          pixelRatio: 3,
          backgroundColor: theme.saveBackground,
        },
      },
    };
  }

  return option;
}

const LEGEND_ITEM_WIDTH = 14;
const LEGEND_ITEM_GAP = 14;
const LEGEND_ROW_HEIGHT = 22;
let textMeasureContext = null;

function measureText(text, fontSize) {
  textMeasureContext ??= document.createElement("canvas").getContext("2d");
  textMeasureContext.font = `${fontSize}px ${FONT_FAMILY}`;
  return textMeasureContext.measureText(text).width;
}

function legendRowCount(theme, names, availableWidth) {
  let rows = 1;
  let rowWidth = 0;
  names.forEach((name) => {
    const itemWidth = LEGEND_ITEM_WIDTH + 5 + measureText(name, theme.smallFontSize) + 4;
    const nextWidth = rowWidth === 0 ? itemWidth : rowWidth + LEGEND_ITEM_GAP + itemWidth;
    if (nextWidth > availableWidth && rowWidth > 0) {
      rows += 1;
      rowWidth = itemWidth;
    } else {
      rowWidth = nextWidth;
    }
  });
  return rows;
}

function legendOption(theme, names, interactive) {
  return {
    type: "plain",
    data: names,
    ...(interactive ? { bottom: 0 } : { top: 0 }),
    left: 0,
    right: 0,
    icon: "roundRect",
    itemWidth: LEGEND_ITEM_WIDTH,
    itemHeight: 3,
    itemGap: LEGEND_ITEM_GAP,
    textStyle: { color: theme.text, fontSize: theme.smallFontSize },
    inactiveColor: theme.axisLine,
  };
}

function gridOption(theme, interactive, legendNames, widthPx) {
  const rows = widthPx ? legendRowCount(theme, legendNames, widthPx) : 1;
  if (interactive) {
    return { left: 66, right: 20, top: 36, bottom: 56 + rows * LEGEND_ROW_HEIGHT };
  }
  return { left: 66, right: 20, top: 18 + rows * LEGEND_ROW_HEIGHT, bottom: 48 };
}

function valueAxis(theme, { name, formatter, min, max, nameGap = 28, scale = false, interval }) {
  return {
    type: "value",
    name,
    nameLocation: "middle",
    nameGap,
    nameTextStyle: { color: theme.text, fontSize: theme.smallFontSize, fontWeight: 600 },
    min,
    max,
    scale,
    interval,
    axisLine: { show: true, lineStyle: { color: theme.axisLine } },
    axisTick: { show: true, lineStyle: { color: theme.axisLine } },
    axisLabel: {
      color: theme.muted,
      fontSize: theme.smallFontSize,
      formatter,
      hideOverlap: true,
    },
    splitLine: { lineStyle: { color: theme.splitLine } },
  };
}

function markerSeries(theme, markers) {
  return markers.map((marker) => ({
    name: marker.name,
    type: "line",
    data: [],
    color: marker.color,
    symbol: "none",
    lineStyle: { color: marker.color, type: "dashed" },
    tooltip: { show: true },
    markLine: {
      silent: false,
      symbol: ["none", "none"],
      animation: false,
      label: { show: false },
      lineStyle: { color: marker.color, type: [5, 4], width: 1.6, opacity: 0.95 },
      emphasis: { label: { show: false }, lineStyle: { width: 2.6 } },
      data: [{ xAxis: marker.value, name: marker.label, markerValue: marker.formatted }],
    },
  }));
}

function buildMarkers(definitions, format, legendFormat = format) {
  return definitions.map(({ label, value, color }) => ({
    label,
    value,
    color,
    formatted: format(value),
    name: `${label}  ${legendFormat(value)}`,
  }));
}

function legendValueFormat(interactive, money) {
  if (interactive) {
    return money ? formatMoney : (value) => numberFormatter.format(value);
  }
  return money ? formatMoneyCompact : formatCompact;
}

function markLineTooltip(theme, params) {
  return tooltipHtml(theme, "Marker", [[params.name, params.data.markerValue ?? params.value]]);
}

function histogramOption(theme, interactive, widthPx, config) {
  const { histogram, color, xName, money, markerDefinitions, saveName, binLabel } = config;
  const { bin_edges: edges, counts } = histogram;
  const total = counts.reduce((sum, count) => sum + count, 0) || 1;
  const axisFormat = money ? formatMoneyCompact : formatCompact;
  const valueFormat = money ? formatMoney : (value) => numberFormatter.format(value);

  let cumulative = 0;
  const bins = counts.map((count, index) => {
    cumulative += count;
    return [edges[index], edges[index + 1], count, count / total, cumulative / total];
  });

  const markers = buildMarkers(markerDefinitions, valueFormat, legendValueFormat(interactive, money));
  const barFill = verticalGradient(color, 0.95, 0.55);

  const legendNames = markers.map((marker) => marker.name);

  return {
    ...baseOption(theme, interactive, { trigger: "item", saveName }),
    legend: legendOption(theme, legendNames, interactive),
    grid: gridOption(theme, interactive, legendNames, widthPx),
    xAxis: valueAxis(theme, { name: xName, formatter: axisFormat, scale: true }),
    yAxis: valueAxis(theme, { name: "Simulations", formatter: formatCompact, nameGap: 46 }),
    series: [
      {
        name: binLabel,
        type: "custom",
        data: bins,
        encode: { x: [0, 1], y: 2 },
        itemStyle: { color: barFill },
        emphasis: { itemStyle: { color: withAlpha(color, 1), shadowBlur: 8, shadowColor: withAlpha(color, 0.5) } },
        renderItem(params, api) {
          const topLeft = api.coord([api.value(0), api.value(2)]);
          const bottomRight = api.coord([api.value(1), 0]);
          const width = bottomRight[0] - topLeft[0];
          const gap = width > 6 ? 1 : 0;
          const shape = echarts.graphic.clipRectByRect(
            { x: topLeft[0] + gap / 2, y: topLeft[1], width: Math.max(width - gap, 0.5), height: bottomRight[1] - topLeft[1] },
            {
              x: params.coordSys.x,
              y: params.coordSys.y,
              width: params.coordSys.width,
              height: params.coordSys.height,
            },
          );
          return shape && { type: "rect", shape, style: api.style() };
        },
        tooltip: {
          formatter(params) {
            const [start, end, count, share, cumulativeShare] = params.data;
            return tooltipHtml(theme, binLabel, [
              ["Range", `${valueFormat(start)} – ${valueFormat(end)}`],
              ["Simulations", numberFormatter.format(count)],
              ["Share", percentFormatter.format(share)],
              ["Cumulative", percentFormatter.format(cumulativeShare)],
            ]);
          },
        },
      },
      ...markerSeries(theme, markers).map((series) => ({
        ...series,
        tooltip: { formatter: (params) => markLineTooltip(theme, params) },
      })),
    ],
  };
}

function frequencyHistogramOption(data, theme, interactive, widthPx) {
  const { frequency } = data;
  return histogramOption(theme, interactive, widthPx, {
    histogram: frequency.histogram,
    color: theme.colors.frequency,
    xName: "Events per year",
    money: false,
    binLabel: "Frequency bin",
    saveName: "frequency-histogram",
    markerDefinitions: [
      { label: "P5", value: frequency.p5, color: theme.colors.p5 },
      { label: "Mean", value: frequency.mean, color: theme.colors.mean },
      { label: "P95", value: frequency.p95, color: theme.colors.p95 },
    ],
  });
}

function magnitudeHistogramOption(data, theme, interactive, widthPx) {
  const { magnitude } = data;
  return histogramOption(theme, interactive, widthPx, {
    histogram: magnitude.histogram,
    color: theme.colors.magnitude,
    xName: "Loss per event ($)",
    money: true,
    binLabel: "Magnitude bin",
    saveName: "magnitude-histogram",
    markerDefinitions: [
      { label: "P5", value: magnitude.p5, color: theme.colors.p5 },
      { label: "Mean", value: magnitude.mean, color: theme.colors.mean },
      { label: "P95", value: magnitude.p95, color: theme.colors.p95 },
    ],
  });
}

function aggregateHistogramOption(data, theme, interactive, widthPx) {
  const loss = data.aggregate_loss;
  return histogramOption(theme, interactive, widthPx, {
    histogram: loss.histogram,
    color: theme.colors.aggregate,
    xName: "Annual loss ($)",
    money: true,
    binLabel: "Annual loss bin",
    saveName: "aggregate-loss-histogram",
    markerDefinitions: [
      { label: "Mean", value: loss.mean, color: theme.colors.mean },
      { label: "VaR 95", value: loss.var_95, color: theme.colors.var95 },
      { label: "VaR 99", value: loss.var_99, color: theme.colors.var99 },
      { label: "TVaR 95", value: loss.tvar_95, color: theme.colors.tvar95 },
      { label: "TVaR 99", value: loss.tvar_99, color: theme.colors.tvar99 },
    ],
  });
}

function exceedanceOption(data, theme, interactive, widthPx) {
  const loss = data.aggregate_loss;
  const points = loss.exceedance_curve.points;
  const color = theme.colors.exceedance;
  const markers = buildMarkers(
    [
      { label: "Mean", value: loss.mean, color: theme.colors.mean },
      { label: "VaR 95", value: loss.var_95, color: theme.colors.var95 },
      { label: "VaR 99", value: loss.var_99, color: theme.colors.var99 },
    ],
    formatMoney,
    legendValueFormat(interactive, true),
  );

  const legendNames = markers.map((marker) => marker.name);

  return {
    ...baseOption(theme, interactive, { trigger: "axis", saveName: "loss-exceedance-curve" }),
    legend: legendOption(theme, legendNames, interactive),
    grid: gridOption(theme, interactive, legendNames, widthPx),
    tooltip: {
      ...baseOption(theme, interactive).tooltip,
      trigger: "axis",
      formatter(params) {
        const point = params.find((item) => item.seriesName === "Exceedance probability");
        if (!point) {
          return "";
        }
        const [lossValue, probability] = point.data;
        const rows = [
          ["Annual loss", formatMoney(lossValue)],
          ["P(loss > amount)", percentFormatter.format(probability)],
        ];
        if (probability > 0) {
          rows.push(["Return period", `≈ 1 in ${numberFormatter.format(1 / probability)} years`]);
        }
        return tooltipHtml(theme, "Loss exceedance", rows);
      },
    },
    xAxis: valueAxis(theme, { name: "Annual loss ($)", formatter: formatMoneyCompact, scale: true }),
    yAxis: valueAxis(theme, {
      name: "Exceedance probability",
      formatter: (value) => percentFormatter.format(value),
      min: 0,
      max: 1,
      interval: 0.2,
      nameGap: 46,
    }),
    series: [
      {
        name: "Exceedance probability",
        type: "line",
        data: points.map((point) => [point.loss, point.exceedance_probability]),
        showSymbol: false,
        symbolSize: 7,
        color,
        lineStyle: { width: 2.5, color },
        areaStyle: { color: verticalGradient(color, 0.35, 0.02) },
        emphasis: { focus: "none", lineStyle: { width: 2.5 } },
      },
      ...markerSeries(theme, markers),
    ],
  };
}

function pertOption(distribution, theme, interactive, widthPx, { color, xName, money, saveName }) {
  const curve = buildPertCurve(distribution);
  const valueFormat = money ? formatMoney : (value) => numberFormatter.format(value);
  const markers = buildMarkers(
    [
      { label: "Min", value: distribution.minimum, color: theme.colors.bound },
      { label: "Mode", value: distribution.mode, color },
      { label: "Mean", value: pertMean(distribution), color: theme.colors.mean },
      { label: "Max", value: distribution.maximum, color: theme.colors.bound },
    ],
    valueFormat,
    legendValueFormat(interactive, money),
  );

  const legendNames = markers.map((marker) => marker.name);

  return {
    ...baseOption(theme, interactive, { trigger: "axis", saveName }),
    legend: legendOption(theme, legendNames, interactive),
    grid: gridOption(theme, interactive, legendNames, widthPx),
    tooltip: {
      ...baseOption(theme, interactive).tooltip,
      trigger: "axis",
      formatter(params) {
        const point = params.find((item) => item.seriesName === "PERT density");
        if (!point) {
          return "";
        }
        const [value, relative, density, cumulative] = point.data;
        return tooltipHtml(theme, "PERT input", [
          ["Value", valueFormat(value)],
          ["Density (vs. peak)", percentFormatter.format(relative)],
          ["Density", densityFormatter.format(density)],
          ["P(X ≤ value)", percentFormatter.format(cumulative)],
          ["P(X > value)", percentFormatter.format(1 - cumulative)],
        ]);
      },
    },
    xAxis: valueAxis(theme, { name: xName, formatter: money ? formatMoneyCompact : formatCompact, scale: true }),
    yAxis: valueAxis(theme, {
      name: "Density (vs. peak)",
      formatter: (value) => percentFormatter.format(value),
      min: 0,
      max: 1,
      interval: 0.25,
      nameGap: 46,
    }),
    series: [
      {
        name: "PERT density",
        type: "line",
        data: curve.map((point) => [point.value, point.relative, point.density, point.cumulative]),
        encode: { x: 0, y: 1 },
        showSymbol: false,
        smooth: false,
        color,
        lineStyle: { width: 2.25, color },
        areaStyle: { color: verticalGradient(color, 0.4, 0.04) },
      },
      ...markerSeries(theme, markers),
    ],
  };
}

function frequencyPertOption(data, theme, interactive, widthPx) {
  return pertOption(data.frequency.distribution, theme, interactive, widthPx, {
    color: theme.colors.frequency,
    xName: "Events per year",
    money: false,
    saveName: "frequency-pert",
  });
}

function magnitudePertOption(data, theme, interactive, widthPx) {
  return pertOption(data.magnitude.distribution, theme, interactive, widthPx, {
    color: theme.colors.magnitude,
    xName: "Loss per event ($)",
    money: true,
    saveName: "magnitude-pert",
  });
}

function scatterOption(data, theme, interactive) {
  const points = data.scatter.map((point) => [point.frequency, point.magnitude, point.aggregate_loss]);
  const losses = points.map((point) => point[2]);
  const minLoss = Math.min(...losses);
  const maxLoss = Math.max(...losses);

  return {
    ...baseOption(theme, interactive, { trigger: "item", saveName: "frequency-vs-magnitude" }),
    grid: { left: 66, right: 104, top: interactive ? 32 : 12, bottom: 48 },
    xAxis: valueAxis(theme, { name: "Events per year", formatter: formatCompact, scale: true }),
    yAxis: valueAxis(theme, { name: "Loss per event ($)", formatter: formatMoneyCompact, scale: true, nameGap: 46 }),
    visualMap: {
      type: "continuous",
      dimension: 2,
      min: minLoss,
      max: maxLoss,
      calculable: interactive,
      realtime: true,
      orient: "vertical",
      right: 0,
      top: "middle",
      itemWidth: 12,
      itemHeight: interactive ? 220 : 150,
      text: interactive
        ? ["Annual loss", ""]
        : [`High ${formatMoneyCompact(maxLoss)}`, `Low ${formatMoneyCompact(minLoss)}`],
      textGap: 8,
      textStyle: { color: theme.text, fontSize: theme.smallFontSize },
      formatter: (value) => formatMoneyCompact(value),
      inRange: { color: theme.colors.lossScale },
    },
    series: [
      {
        name: "Simulation draw",
        type: "scatter",
        data: points,
        symbolSize: theme.symbolSize,
        itemStyle: { opacity: 0.8 },
        emphasis: { scale: 2, itemStyle: { opacity: 1, borderColor: theme.strong, borderWidth: 1 } },
        tooltip: {
          formatter(params) {
            const [frequency, magnitude, aggregate] = params.data;
            return tooltipHtml(theme, "Simulation draw", [
              ["Frequency", `${numberFormatter.format(frequency)} / year`],
              ["Magnitude", formatMoney(magnitude)],
              ["Aggregate loss", formatMoney(aggregate)],
            ]);
          },
        },
      },
    ],
  };
}

const CHART_SPECS = {
  frequencyHistogram: {
    elementId: "frequency-chart",
    build: frequencyHistogramOption,
    title: "Frequency histogram",
    caption: "Simulated annual event frequency with P5, mean and P95.",
  },
  magnitudeHistogram: {
    elementId: "magnitude-chart",
    build: magnitudeHistogramOption,
    title: "Magnitude histogram",
    caption: "Simulated loss per event with P5, mean and P95.",
  },
  aggregateHistogram: {
    elementId: "aggregate-loss-chart",
    build: aggregateHistogramOption,
    title: "Aggregate loss histogram",
    caption: "Annual loss (frequency × magnitude) across all simulations, with mean and VaR / TVaR tail-risk markers.",
  },
  exceedance: {
    elementId: "lec-chart",
    build: exceedanceOption,
    title: "Loss exceedance curve",
    caption: "Probability that the annual loss exceeds a given amount; VaR 95 / 99 mark the 5% and 1% thresholds.",
  },
  frequencyPert: {
    elementId: "frequency-pert-chart",
    build: frequencyPertOption,
    title: "Frequency PERT input",
    caption: "Fitted Beta PERT density for events per year.",
  },
  magnitudePert: {
    elementId: "magnitude-pert-chart",
    build: magnitudePertOption,
    title: "Magnitude PERT input",
    caption: "Fitted Beta PERT density for loss per event.",
  },
  scatter: {
    elementId: "scatter-chart",
    build: scatterOption,
    title: "Frequency vs magnitude",
    caption: `Each point is one simulation draw (up to 2,000 shown), colored by its aggregate annual loss.`,
  },
};

function disposeScreenCharts() {
  screenCharts.forEach(({ chart, observer }) => {
    observer.disconnect();
    chart.dispose();
  });
  screenCharts.length = 0;
}

function renderScreenCharts(data) {
  disposeScreenCharts();

  Object.values(CHART_SPECS).forEach((spec) => {
    const element = document.getElementById(spec.elementId);
    if (!element) {
      return;
    }
    const chart = echarts.init(element, null, { renderer: "svg" });
    const option = spec.build(data, SCREEN_THEME, true, element.clientWidth);
    chart.setOption(option);
    const legendNames = option.legend?.data ?? [];
    const observer = new ResizeObserver(() => {
      if (legendNames.length) {
        chart.setOption({ grid: gridOption(SCREEN_THEME, true, legendNames, element.clientWidth) });
      }
      chart.resize();
    });
    observer.observe(element);
    screenCharts.push({ chart, observer });
  });
}

// ---------------------------------------------------------------------------
// Result page
// ---------------------------------------------------------------------------

function renderVariableStats(container, variable) {
  const stats = [
    ["Mean", variable.mean],
    ["Median", variable.median],
    ["Std dev", variable.std],
    ["P5", variable.p5],
    ["P50", variable.p50],
    ["P95", variable.p95],
    ["P99", variable.p99],
    ["Sim min", variable.min],
    ["Sim max", variable.max],
  ];

  container.replaceChildren(
    ...stats.map(([label, value]) =>
      renderStat(label, formatStatValue(label, value)),
    ),
  );
}

function renderAggregateStats(container, aggregateLoss) {
  const stats = [
    ["Mean loss", aggregateLoss.mean],
    ["Median loss", aggregateLoss.median],
    ["Std dev", aggregateLoss.std],
    ["P5", aggregateLoss.p5],
    ["P50", aggregateLoss.p50],
    ["P95 / VaR 95", aggregateLoss.var_95],
    ["P99 / VaR 99", aggregateLoss.var_99],
    ["TVaR 95", aggregateLoss.tvar_95],
    ["TVaR 99", aggregateLoss.tvar_99],
    ["Sim min", aggregateLoss.min],
    ["Sim max", aggregateLoss.max],
  ];

  container.replaceChildren(
    ...stats.map(([label, value]) => renderStat(label, numberFormatter.format(value))),
  );
}

function renderVariableDetails(container, distribution) {
  container.replaceChildren(
    renderDetail("Type", distribution.type),
    renderDetail("Minimum", numberFormatter.format(distribution.minimum)),
    renderDetail("Mode", numberFormatter.format(distribution.mode)),
    renderDetail("Maximum", numberFormatter.format(distribution.maximum)),
    renderDetail("Alpha", numberFormatter.format(distribution.alpha)),
    renderDetail("Beta", numberFormatter.format(distribution.beta)),
    renderDetail("Confidence level (lambda)", numberFormatter.format(distribution.lambda_param)),
  );
}

function renderResults(data) {
  sharedStats.replaceChildren(
    renderStat("Seed", String(data.seed)),
    renderStat("Iterations", numberFormatter.format(data.iterations)),
  );

  renderVariableStats(frequencyStats, data.frequency);
  renderVariableStats(magnitudeStats, data.magnitude);
  renderAggregateStats(aggregateStats, data.aggregate_loss);
  renderVariableDetails(frequencyDetails, data.frequency.distribution);
  renderVariableDetails(magnitudeDetails, data.magnitude.distribution);

  lastSimulationData = data;
  exportPdfButton.disabled = false;
  resultsSection.hidden = false;
  emptyState.hidden = true;

  if (window.echarts) {
    renderScreenCharts(data);
  } else {
    setStatus("Chart library failed to load. Check your network connection.", "error");
  }
}

// ---------------------------------------------------------------------------
// PDF export
// ---------------------------------------------------------------------------

function pdfPageWidth(doc) {
  return doc.internal.pageSize.getWidth();
}

function pdfPageHeight(doc) {
  return doc.internal.pageSize.getHeight();
}

function pdfUsableWidth(doc) {
  return pdfPageWidth(doc) - PDF_MARGIN * 2;
}

function pdfAddTextLine(doc, x, y, text, options = {}) {
  const {
    fontSize = 9,
    bold = false,
    color = [30, 41, 59],
  } = options;
  doc.setFont("helvetica", bold ? "bold" : "normal");
  doc.setFontSize(fontSize);
  doc.setTextColor(...color);
  doc.text(text, x, y);
  return y + fontSize * 0.38 + 1.5;
}

function pdfAddSectionHeading(doc, y, text) {
  const nextY = pdfAddTextLine(doc, PDF_MARGIN, y, text, {
    fontSize: 11,
    bold: true,
    color: [15, 23, 42],
  });
  doc.setDrawColor(226, 232, 240);
  doc.setLineWidth(0.3);
  doc.line(PDF_MARGIN, nextY - 2.2, PDF_MARGIN + pdfUsableWidth(doc), nextY - 2.2);
  return nextY + 1;
}

function pdfAddColumnBlock(doc, x, y, width, title, rows) {
  let cursorY = pdfAddTextLine(doc, x, y, title, { fontSize: 10, bold: true, color: [2, 132, 199] });
  const labelWidth = width * 0.52;

  rows.forEach(([label, value], index) => {
    if (index % 2 === 0) {
      doc.setFillColor(248, 250, 252);
      doc.rect(x - 1, cursorY - 2.8, width + 1, PDF_ROW_HEIGHT, "F");
    }

    doc.setFont("helvetica", "bold");
    doc.setFontSize(8);
    doc.setTextColor(71, 85, 105);
    doc.text(label, x, cursorY);

    doc.setFont("helvetica", "normal");
    doc.setFontSize(8);
    doc.setTextColor(30, 41, 59);
    const valueText = doc.splitTextToSize(String(value), width - labelWidth - 1);
    doc.text(valueText, x + labelWidth, cursorY);
    cursorY += PDF_ROW_HEIGHT * Math.max(valueText.length, 1);
  });

  return cursorY;
}

function pdfAddSummaryPage(doc, data) {
  const generatedAt = new Date().toLocaleString();
  let y = PDF_MARGIN;

  doc.setFillColor(2, 132, 199);
  doc.rect(PDF_MARGIN, y - 4, 1.4, 14, "F");
  const textX = PDF_MARGIN + 4;

  y = pdfAddTextLine(doc, textX, y + 1, "CRQ Monte Carlo Simulation Report", {
    fontSize: 15,
    bold: true,
    color: [15, 23, 42],
  });
  y = pdfAddTextLine(doc, textX, y, `Generated: ${generatedAt}`, { fontSize: 9, color: [71, 85, 105] });
  y = pdfAddTextLine(
    doc,
    textX,
    y,
    `Seed: ${data.seed}  |  Iterations: ${numberFormatter.format(data.iterations)}`,
    { fontSize: 9, color: [71, 85, 105] },
  );
  y += PDF_SECTION_GAP + 2;

  const usableWidth = pdfUsableWidth(doc);
  const columnWidth = (usableWidth - 8) / 2;
  const leftX = PDF_MARGIN;
  const rightX = PDF_MARGIN + columnWidth + 8;

  y = pdfAddSectionHeading(doc, y, "Input parameters");

  const inputBottom = Math.max(
    pdfAddColumnBlock(doc, leftX, y, columnWidth, "Frequency", buildDistributionRowsShort(data.frequency.distribution)),
    pdfAddColumnBlock(doc, rightX, y, columnWidth, "Magnitude", buildDistributionRowsShort(data.magnitude.distribution)),
  );
  y = inputBottom + PDF_SECTION_GAP + 2;

  y = pdfAddSectionHeading(doc, y, "Simulation results");

  const statsColumnWidth = (usableWidth - 12) / 3;
  const statsColumns = [
    { x: PDF_MARGIN, title: "Frequency", stats: data.frequency },
    { x: PDF_MARGIN + statsColumnWidth + 6, title: "Magnitude", stats: data.magnitude },
    { x: PDF_MARGIN + (statsColumnWidth + 6) * 2, title: "Aggregate loss", stats: data.aggregate_loss },
  ];

  const statRowsFor = (stats, isAggregate = false) => {
    if (isAggregate) {
      return buildStatsRows([
        ["Mean", stats.mean],
        ["Median", stats.median],
        ["Std dev", stats.std],
        ["P5", stats.p5],
        ["P50", stats.p50],
        ["P95 / VaR 95", stats.var_95],
        ["P99 / VaR 99", stats.var_99],
        ["TVaR 95", stats.tvar_95],
        ["TVaR 99", stats.tvar_99],
        ["Sim min", stats.min],
        ["Sim max", stats.max],
      ]);
    }
    return buildStatsRows([
      ["Mean", stats.mean],
      ["Median", stats.median],
      ["Std dev", stats.std],
      ["P5", stats.p5],
      ["P50", stats.p50],
      ["P95", stats.p95],
      ["P99", stats.p99],
      ["Sim min", stats.min],
      ["Sim max", stats.max],
    ]);
  };

  return Math.max(
    ...statsColumns.map((column, index) =>
      pdfAddColumnBlock(
        doc,
        column.x,
        y,
        statsColumnWidth,
        column.title,
        statRowsFor(column.stats, index === 2),
      ),
    ),
  );
}

function renderChartImage(spec, data, widthMm, heightMm) {
  const container = document.createElement("div");
  Object.assign(container.style, {
    position: "fixed",
    left: "-10000px",
    top: "0",
    width: `${Math.round(widthMm * PDF_PX_PER_MM)}px`,
    height: `${Math.round(heightMm * PDF_PX_PER_MM)}px`,
  });
  document.body.appendChild(container);

  const chart = echarts.init(container, null, { renderer: "canvas", devicePixelRatio: PDF_PIXEL_RATIO });
  try {
    chart.setOption(spec.build(data, PRINT_THEME, false, container.clientWidth));
    return chart.getDataURL({ type: "png", pixelRatio: PDF_PIXEL_RATIO, backgroundColor: "#ffffff" });
  } finally {
    chart.dispose();
    container.remove();
  }
}

function pdfAddChartBlock(doc, data, spec, x, y, width, height) {
  doc.setFont("helvetica", "bold");
  doc.setFontSize(9.5);
  doc.setTextColor(15, 23, 42);
  doc.text(spec.title, x, y + 3.5);

  doc.setFont("helvetica", "normal");
  doc.setFontSize(7.5);
  doc.setTextColor(100, 116, 139);
  doc.text(doc.splitTextToSize(spec.caption, width)[0], x, y + 7.5);

  const imageY = y + PDF_CHART_HEADER_HEIGHT;
  doc.setDrawColor(226, 232, 240);
  doc.setLineWidth(0.25);
  doc.roundedRect(x, imageY, width, height, 1.5, 1.5, "S");

  const inset = 1.5;
  const image = renderChartImage(spec, data, width - inset * 2, height - inset * 2);
  doc.addImage(image, "PNG", x + inset, imageY + inset, width - inset * 2, height - inset * 2, undefined, "FAST");
  return imageY + height;
}

function pdfAddChartPage(doc, data, heading, rows) {
  doc.addPage();
  let y = pdfAddSectionHeading(doc, PDF_MARGIN, heading) + 1;
  const usableWidth = pdfUsableWidth(doc);

  rows.forEach(({ specs, height }) => {
    const width = (usableWidth - PDF_COLUMN_GAP * (specs.length - 1)) / specs.length;
    const bottoms = specs.map((spec, index) =>
      pdfAddChartBlock(doc, data, spec, PDF_MARGIN + index * (width + PDF_COLUMN_GAP), y, width, height),
    );
    y = Math.max(...bottoms) + PDF_BLOCK_GAP;
  });
}

function pdfAddFooters(doc, data) {
  const pageCount = doc.getNumberOfPages();
  const footerY = pdfPageHeight(doc) - 7;

  for (let page = 1; page <= pageCount; page += 1) {
    doc.setPage(page);
    doc.setDrawColor(226, 232, 240);
    doc.setLineWidth(0.3);
    doc.line(PDF_MARGIN, footerY - 3.5, pdfPageWidth(doc) - PDF_MARGIN, footerY - 3.5);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(7.5);
    doc.setTextColor(100, 116, 139);
    doc.text(`CRQ Monte Carlo Simulation Report  |  Seed ${data.seed}`, PDF_MARGIN, footerY);
    doc.text(`Page ${page} of ${pageCount}`, pdfPageWidth(doc) - PDF_MARGIN, footerY, { align: "right" });
  }
}

function buildDistributionRowsShort(distribution) {
  return [
    ["minimum", numberFormatter.format(distribution.minimum)],
    ["mode", numberFormatter.format(distribution.mode)],
    ["maximum", numberFormatter.format(distribution.maximum)],
    ["alpha", numberFormatter.format(distribution.alpha)],
    ["beta", numberFormatter.format(distribution.beta)],
    ["confidence (lambda)", numberFormatter.format(distribution.lambda_param)],
  ];
}

function buildStatsRows(stats) {
  return stats.map(([label, value]) => [label, numberFormatter.format(value)]);
}

function buildSimulationPdf(data) {
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4", compress: true });

  pdfAddSummaryPage(doc, data);
  pdfAddChartPage(doc, data, "Loss distribution", [
    { specs: [CHART_SPECS.aggregateHistogram], height: 72 },
    { specs: [CHART_SPECS.exceedance], height: 72 },
    { specs: [CHART_SPECS.frequencyHistogram, CHART_SPECS.magnitudeHistogram], height: 62 },
  ]);
  pdfAddChartPage(doc, data, "Input uncertainty", [
    { specs: [CHART_SPECS.frequencyPert, CHART_SPECS.magnitudePert], height: 62 },
    { specs: [CHART_SPECS.scatter], height: 118 },
  ]);
  pdfAddFooters(doc, data);

  return doc;
}

async function exportSimulationPdf() {
  if (!lastSimulationData) {
    setStatus("Run a simulation before exporting.", "error");
    return;
  }

  if (!window.jspdf?.jsPDF || !window.echarts) {
    setStatus("PDF or chart library failed to load. Check your network connection.", "error");
    return;
  }

  exportPdfButton.disabled = true;
  exportPdfButton.textContent = "Exporting...";

  try {
    await new Promise((resolve) => requestAnimationFrame(resolve));
    const data = lastSimulationData;
    const doc = buildSimulationPdf(data);
    const timestamp = new Date().toISOString().slice(0, 10);
    doc.save(`crq-simulation-${data.seed}-${timestamp}.pdf`);
    setStatus("PDF exported successfully.", "success");
  } catch (error) {
    setStatus(error.message || "PDF export failed.", "error");
  } finally {
    exportPdfButton.disabled = false;
    exportPdfButton.textContent = "Export PDF";
  }
}

exportPdfButton.addEventListener("click", exportSimulationPdf);

function initResultPage() {
  const raw = sessionStorage.getItem(SIMULATION_RESULT_KEY);
  if (!raw) {
    emptyState.hidden = false;
    resultsSection.hidden = true;
    exportPdfButton.disabled = true;
    return;
  }

  try {
    const data = JSON.parse(raw);
    clearStatus();
    renderResults(data);
  } catch (error) {
    emptyState.hidden = false;
    resultsSection.hidden = true;
    exportPdfButton.disabled = true;
    setStatus("Stored simulation results could not be loaded.", "error");
  }
}

document.addEventListener("DOMContentLoaded", initResultPage);
