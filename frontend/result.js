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
const frequencyChart = document.getElementById("frequency-chart");
const magnitudeChart = document.getElementById("magnitude-chart");
const aggregateLossChart = document.getElementById("aggregate-loss-chart");
const lecChart = document.getElementById("lec-chart");
const frequencyPertChart = document.getElementById("frequency-pert-chart");
const magnitudePertChart = document.getElementById("magnitude-pert-chart");
const scatterChart = document.getElementById("scatter-chart");
const chartTooltip = document.getElementById("chart-tooltip");
const exportPdfButton = document.getElementById("export-pdf-button");

let lastSimulationData = null;

const PDF_MARGIN = 14;
const PDF_ROW_HEIGHT = 3.8;
const PDF_SECTION_GAP = 3;
const PDF_CHART_TITLE_HEIGHT = 7;
const PDF_CHART_GAP = 5;
const PDF_STANDARD_CHART_HEIGHT = 98;
const PDF_SCATTER_CHART_HEIGHT = 112;

const numberFormatter = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 2,
});

const percentFormatter = new Intl.NumberFormat(undefined, {
  style: "percent",
  maximumFractionDigits: 1,
});

const CHART_PADDING = { top: 40, right: 24, bottom: 58, left: 72 };
const DEFAULT_CHART_HEIGHT = 280;
const SCATTER_CHART_HEIGHT = 320;

const chartInteractionHandlers = new WeakMap();

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

function formatAxisValue(value) {
  const absolute = Math.abs(value);
  if (absolute >= 1_000_000) {
    return `${numberFormatter.format(value / 1_000_000)}M`;
  }
  if (absolute >= 10_000) {
    return `${numberFormatter.format(value / 1_000)}k`;
  }
  if (absolute >= 1000) {
    return numberFormatter.format(value);
  }
  if (Number.isInteger(value)) {
    return String(value);
  }
  return numberFormatter.format(value);
}

function computeTicks(minValue, maxValue, targetCount = 5) {
  if (minValue === maxValue) {
    return [minValue];
  }

  const span = maxValue - minValue;
  const rawStep = span / Math.max(targetCount - 1, 1);
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  let niceStep = magnitude;

  if (normalized <= 1) {
    niceStep = magnitude;
  } else if (normalized <= 2) {
    niceStep = 2 * magnitude;
  } else if (normalized <= 5) {
    niceStep = 5 * magnitude;
  } else {
    niceStep = 10 * magnitude;
  }

  const ticks = [];
  const start = Math.ceil(minValue / niceStep) * niceStep;
  for (let tick = start; tick <= maxValue + niceStep * 0.001; tick += niceStep) {
    ticks.push(Number(tick.toPrecision(12)));
  }

  if (!ticks.length || ticks[0] > minValue) {
    ticks.unshift(minValue);
  }
  if (ticks[ticks.length - 1] < maxValue) {
    ticks.push(maxValue);
  }

  return ticks;
}

function setupCanvas(canvas, height = DEFAULT_CHART_HEIGHT) {
  const width = canvas.clientWidth || 640;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const context = canvas.getContext("2d");
  context.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { context, width, height };
}

function getPlotArea(width, height) {
  return {
    chartWidth: width - CHART_PADDING.left - CHART_PADDING.right,
    chartHeight: height - CHART_PADDING.top - CHART_PADDING.bottom,
  };
}

function valueToX(value, minValue, maxValue, chartWidth) {
  if (maxValue === minValue) {
    return CHART_PADDING.left + chartWidth / 2;
  }
  const ratio = (value - minValue) / (maxValue - minValue);
  return CHART_PADDING.left + ratio * chartWidth;
}

function valueToY(value, minValue, maxValue, chartHeight) {
  if (maxValue === minValue) {
    return CHART_PADDING.top + chartHeight / 2;
  }
  const ratio = (value - minValue) / (maxValue - minValue);
  return CHART_PADDING.top + chartHeight - ratio * chartHeight;
}

function drawChartBackground(context, width, height) {
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#0b1220";
  context.fillRect(0, 0, width, height);
}

function drawAxes(context, width, height, options) {
  const {
    xMin,
    xMax,
    yMin,
    yMax,
    xLabel,
    yLabel,
    xTicks,
    yTicks,
    formatX = formatAxisValue,
    formatY = formatAxisValue,
  } = options;
  const { chartWidth, chartHeight } = getPlotArea(width, height);

  context.strokeStyle = "#334155";
  context.lineWidth = 1;
  context.fillStyle = "#64748b";
  context.font = "11px Inter, system-ui, sans-serif";

  yTicks.forEach((tick) => {
    const y = valueToY(tick, yMin, yMax, chartHeight);
    context.strokeStyle = "#1e293b";
    context.beginPath();
    context.moveTo(CHART_PADDING.left, y);
    context.lineTo(CHART_PADDING.left + chartWidth, y);
    context.stroke();

    context.fillStyle = "#94a3b8";
    context.textAlign = "right";
    context.textBaseline = "middle";
    context.fillText(formatY(tick), CHART_PADDING.left - 8, y);
  });

  xTicks.forEach((tick) => {
    const x = valueToX(tick, xMin, xMax, chartWidth);
    context.strokeStyle = "#1e293b";
    context.beginPath();
    context.moveTo(x, CHART_PADDING.top);
    context.lineTo(x, CHART_PADDING.top + chartHeight);
    context.stroke();

    context.fillStyle = "#94a3b8";
    context.textAlign = "center";
    context.textBaseline = "top";
    context.fillText(formatX(tick), x, CHART_PADDING.top + chartHeight + 8);
  });

  context.strokeStyle = "#475569";
  context.lineWidth = 1.5;
  context.beginPath();
  context.moveTo(CHART_PADDING.left, CHART_PADDING.top);
  context.lineTo(CHART_PADDING.left, CHART_PADDING.top + chartHeight);
  context.lineTo(CHART_PADDING.left + chartWidth, CHART_PADDING.top + chartHeight);
  context.stroke();

  context.fillStyle = "#cbd5e1";
  context.font = "12px Inter, system-ui, sans-serif";
  context.textAlign = "center";
  context.textBaseline = "top";
  context.fillText(xLabel, CHART_PADDING.left + chartWidth / 2, height - 22);

  context.save();
  context.translate(18, CHART_PADDING.top + chartHeight / 2);
  context.rotate(-Math.PI / 2);
  context.textAlign = "center";
  context.textBaseline = "top";
  context.fillText(yLabel, 0, 0);
  context.restore();
}

function drawLegend(context, items, width) {
  const boxWidth = 118;
  const boxHeight = 14 + items.length * 16;
  const x = width - CHART_PADDING.right - boxWidth;
  const y = CHART_PADDING.top;

  context.fillStyle = "rgba(11, 18, 32, 0.88)";
  context.strokeStyle = "#334155";
  context.lineWidth = 1;
  context.fillRect(x, y, boxWidth, boxHeight);
  context.strokeRect(x, y, boxWidth, boxHeight);

  items.forEach((item, index) => {
    const rowY = y + 10 + index * 16;
    context.strokeStyle = item.color;
    context.lineWidth = 2;
    context.setLineDash(item.dashed ? [4, 4] : []);
    context.beginPath();
    context.moveTo(x + 10, rowY);
    context.lineTo(x + 28, rowY);
    context.stroke();
    context.setLineDash([]);

    context.fillStyle = "#e2e8f0";
    context.font = "11px Inter, system-ui, sans-serif";
    context.textAlign = "left";
    context.textBaseline = "middle";
    context.fillText(item.label, x + 34, rowY);
  });
}

function showTooltip(clientX, clientY, title, lines) {
  chartTooltip.innerHTML = `<strong>${title}</strong>${lines.map((line) => `<div>${line}</div>`).join("")}`;
  chartTooltip.hidden = false;

  const margin = 12;
  const rect = chartTooltip.getBoundingClientRect();
  let left = clientX + margin;
  let top = clientY + margin;

  if (left + rect.width > window.innerWidth - margin) {
    left = clientX - rect.width - margin;
  }
  if (top + rect.height > window.innerHeight - margin) {
    top = clientY - rect.height - margin;
  }

  chartTooltip.style.left = `${Math.max(margin, left)}px`;
  chartTooltip.style.top = `${Math.max(margin, top)}px`;
}

function hideTooltip() {
  chartTooltip.hidden = true;
}

function attachChartInteraction(canvas, onMove, onLeave) {
  const previous = chartInteractionHandlers.get(canvas);
  if (previous) {
    canvas.removeEventListener("mousemove", previous.onMove);
    canvas.removeEventListener("mouseleave", previous.onLeave);
  }

  const handlers = { onMove, onLeave };
  chartInteractionHandlers.set(canvas, handlers);
  canvas.addEventListener("mousemove", onMove);
  canvas.addEventListener("mouseleave", onLeave);
}

function getCanvasPoint(canvas, event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
    clientX: event.clientX,
    clientY: event.clientY,
  };
}

function renderHistogram(canvas, histogram, options = {}) {
  const {
    barColor = "#38bdf8",
    markers = [],
    xLabel = "Value",
    yLabel = "Count",
    tooltipTitle = "Bin",
  } = options;
  const { bin_edges: binEdges, counts } = histogram;

  if (!binEdges.length || !counts.length) {
    canvas.hidden = true;
    return;
  }

  canvas.hidden = false;

  const { context, width, height } = setupCanvas(canvas);
  drawChartBackground(context, width, height);

  const { chartWidth, chartHeight } = getPlotArea(width, height);
  const minValue = binEdges[0];
  const maxValue = binEdges[binEdges.length - 1];
  const maxCount = Math.max(...counts, 1);
  const barGap = 1;
  const barWidth = chartWidth / counts.length;
  const xTicks = computeTicks(minValue, maxValue, 6);
  const yTicks = computeTicks(0, maxCount, 5);
  const hitAreas = [];

  drawAxes(context, width, height, {
    xMin: minValue,
    xMax: maxValue,
    yMin: 0,
    yMax: maxCount,
    xLabel,
    yLabel,
    xTicks,
    yTicks,
    formatY: (value) => String(Math.round(value)),
  });

  counts.forEach((count, index) => {
    const barHeight = (count / maxCount) * chartHeight;
    const x = CHART_PADDING.left + index * barWidth + barGap / 2;
    const y = CHART_PADDING.top + chartHeight - barHeight;
    const drawWidth = Math.max(barWidth - barGap, 1);

    context.fillStyle = barColor;
    context.fillRect(x, y, drawWidth, barHeight);

    hitAreas.push({
      x,
      y: CHART_PADDING.top,
      width: drawWidth,
      height: chartHeight,
      count,
      rangeStart: binEdges[index],
      rangeEnd: binEdges[index + 1],
    });
  });

  markers.forEach((marker) => {
    const x = valueToX(marker.value, minValue, maxValue, chartWidth);
    context.strokeStyle = marker.color;
    context.lineWidth = 2;
    context.setLineDash([5, 4]);
    context.beginPath();
    context.moveTo(x, CHART_PADDING.top);
    context.lineTo(x, CHART_PADDING.top + chartHeight);
    context.stroke();
    context.setLineDash([]);

    context.fillStyle = marker.color;
    context.font = "10px Inter, system-ui, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "bottom";
    context.fillText(marker.label, x, CHART_PADDING.top - 6);
  });

  if (markers.length) {
    drawLegend(
      context,
      markers.map((marker) => ({
        label: `${marker.label}: ${formatAxisValue(marker.value)}`,
        color: marker.color,
        dashed: true,
      })),
      width,
    );
  }

  attachChartInteraction(
    canvas,
    (event) => {
      const point = getCanvasPoint(canvas, event);
      const hit = hitAreas.find(
        (area) =>
          point.x >= area.x &&
          point.x <= area.x + area.width &&
          point.y >= area.y &&
          point.y <= area.y + area.height,
      );

      if (!hit) {
        hideTooltip();
        return;
      }

      showTooltip(point.clientX, point.clientY, tooltipTitle, [
        `Range: ${formatAxisValue(hit.rangeStart)} – ${formatAxisValue(hit.rangeEnd)}`,
        `Count: ${hit.count}`,
        `Share: ${percentFormatter.format(hit.count / counts.reduce((sum, value) => sum + value, 0))}`,
      ]);
    },
    hideTooltip,
  );
}

function renderExceedanceCurve(canvas, exceedanceCurve) {
  const points = exceedanceCurve.points;
  if (!points.length) {
    canvas.hidden = true;
    return;
  }

  canvas.hidden = false;

  const minLoss = points[0].loss;
  const maxLoss = points[points.length - 1].loss;
  const xTicks = computeTicks(minLoss, maxLoss, 6);
  const yTicks = [0, 0.2, 0.4, 0.6, 0.8, 1];

  function interpolateAtLoss(loss) {
    if (loss <= points[0].loss) {
      return { loss: points[0].loss, exceedance_probability: points[0].exceedance_probability };
    }
    if (loss >= points[points.length - 1].loss) {
      return {
        loss: points[points.length - 1].loss,
        exceedance_probability: points[points.length - 1].exceedance_probability,
      };
    }

    for (let index = 0; index < points.length - 1; index += 1) {
      const start = points[index];
      const end = points[index + 1];
      if (loss >= start.loss && loss <= end.loss) {
        const ratio = (loss - start.loss) / (end.loss - start.loss);
        return {
          loss,
          exceedance_probability:
            start.exceedance_probability +
            ratio * (end.exceedance_probability - start.exceedance_probability),
        };
      }
    }

    return points[points.length - 1];
  }

  function draw(hoverPoint = null) {
    const { context, width, height } = setupCanvas(canvas);
    drawChartBackground(context, width, height);

    const { chartWidth, chartHeight } = getPlotArea(width, height);

    drawAxes(context, width, height, {
      xMin: minLoss,
      xMax: maxLoss,
      yMin: 0,
      yMax: 1,
      xLabel: "Annual loss ($)",
      yLabel: "Exceedance probability",
      xTicks,
      yTicks,
      formatY: (value) => percentFormatter.format(value),
    });

    context.strokeStyle = "#fbbf24";
    context.lineWidth = 2.5;
    context.beginPath();
    points.forEach((point, index) => {
      const x = valueToX(point.loss, minLoss, maxLoss, chartWidth);
      const y = valueToY(point.exceedance_probability, 0, 1, chartHeight);
      if (index === 0) {
        context.moveTo(x, y);
      } else {
        context.lineTo(x, y);
      }
    });
    context.stroke();

    if (hoverPoint) {
      const hoverX = valueToX(hoverPoint.loss, minLoss, maxLoss, chartWidth);
      const hoverY = valueToY(hoverPoint.exceedance_probability, 0, 1, chartHeight);

      context.strokeStyle = "#64748b";
      context.lineWidth = 1;
      context.setLineDash([4, 4]);
      context.beginPath();
      context.moveTo(hoverX, CHART_PADDING.top);
      context.lineTo(hoverX, CHART_PADDING.top + chartHeight);
      context.moveTo(CHART_PADDING.left, hoverY);
      context.lineTo(CHART_PADDING.left + chartWidth, hoverY);
      context.stroke();
      context.setLineDash([]);

      context.fillStyle = "#fbbf24";
      context.strokeStyle = "#fef3c7";
      context.lineWidth = 2;
      context.beginPath();
      context.arc(hoverX, hoverY, 5, 0, Math.PI * 2);
      context.fill();
      context.stroke();
    }

    return { chartWidth, chartHeight, width, height };
  }

  draw();

  attachChartInteraction(
    canvas,
    (event) => {
      const point = getCanvasPoint(canvas, event);
      const { chartWidth, chartHeight } = getPlotArea(canvas.clientWidth || 640, DEFAULT_CHART_HEIGHT);
      const plotX = point.x - CHART_PADDING.left;
      const plotY = point.y - CHART_PADDING.top;

      if (
        plotX < 0 ||
        plotX > chartWidth ||
        plotY < 0 ||
        plotY > chartHeight
      ) {
        draw();
        hideTooltip();
        return;
      }

      const loss = minLoss + (plotX / chartWidth) * (maxLoss - minLoss);
      const hoverPoint = interpolateAtLoss(loss);
      draw(hoverPoint);

      showTooltip(point.clientX, point.clientY, "Loss exceedance", [
        `Magnitude (annual loss): ${numberFormatter.format(hoverPoint.loss)}`,
        `Exceedance probability: ${percentFormatter.format(hoverPoint.exceedance_probability)}`,
      ]);
    },
    () => {
      draw();
      hideTooltip();
    },
  );
}

function logGamma(value) {
  if (value <= 0) {
    return 0;
  }
  return (value - 0.5) * Math.log(value) - value + 0.5 * Math.log(2 * Math.PI);
}

function logBeta(alpha, beta) {
  return logGamma(alpha) + logGamma(beta) - logGamma(alpha + beta);
}

function betaPdf(x, alpha, beta) {
  if (x <= 0 || x >= 1) {
    return 0;
  }
  const logPdf =
    (alpha - 1) * Math.log(x) + (beta - 1) * Math.log(1 - x) - logBeta(alpha, beta);
  return Math.exp(logPdf);
}

function renderPertDiagram(canvas, distribution, accentColor, xLabel) {
  const { minimum, mode, maximum, alpha, beta } = distribution;
  canvas.hidden = false;

  const { context, width, height } = setupCanvas(canvas);
  drawChartBackground(context, width, height);

  const { chartWidth, chartHeight } = getPlotArea(width, height);
  const span = maximum - minimum;
  const densityPoints = 80;
  const densities = [];

  for (let index = 0; index < densityPoints; index += 1) {
    const unit = index / (densityPoints - 1);
    const value = minimum + span * unit;
    const scaledUnit = (value - minimum) / span;
    densities.push({
      value,
      density: betaPdf(scaledUnit, alpha, beta) / span,
    });
  }

  const maxDensity = Math.max(...densities.map((point) => point.density), 1e-9);
  const xTicks = computeTicks(minimum, maximum, 5);
  const yTicks = computeTicks(0, maxDensity, 4);

  drawAxes(context, width, height, {
    xMin: minimum,
    xMax: maximum,
    yMin: 0,
    yMax: maxDensity,
    xLabel,
    yLabel: "Relative density",
    xTicks,
    yTicks,
    formatY: (value) => value.toExponential(1),
  });

  context.beginPath();
  context.moveTo(
    valueToX(minimum, minimum, maximum, chartWidth),
    valueToY(0, 0, maxDensity, chartHeight),
  );
  densities.forEach((point) => {
    const x = valueToX(point.value, minimum, maximum, chartWidth);
    const y = valueToY(point.density, 0, maxDensity, chartHeight);
    context.lineTo(x, y);
  });
  context.lineTo(
    valueToX(maximum, minimum, maximum, chartWidth),
    valueToY(0, 0, maxDensity, chartHeight),
  );
  context.closePath();
  context.fillStyle = `${accentColor}33`;
  context.fill();
  context.strokeStyle = accentColor;
  context.lineWidth = 2;
  context.stroke();

  const markers = [
    { value: minimum, label: "Min", color: "#94a3b8" },
    { value: mode, label: "Mode", color: accentColor },
    { value: maximum, label: "Max", color: "#94a3b8" },
  ];

  markers.forEach((marker) => {
    const x = valueToX(marker.value, minimum, maximum, chartWidth);
    const baseY = valueToY(0, 0, maxDensity, chartHeight);
    context.strokeStyle = marker.color;
    context.lineWidth = 1.5;
    context.beginPath();
    context.moveTo(x, baseY - 4);
    context.lineTo(x, baseY + 4);
    context.stroke();

    context.fillStyle = marker.color;
    context.font = "10px Inter, system-ui, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "bottom";
    context.fillText(`${marker.label}: ${formatAxisValue(marker.value)}`, x, CHART_PADDING.top - 6);
  });

  attachChartInteraction(
    canvas,
    (event) => {
      const point = getCanvasPoint(canvas, event);
      const plotX = point.x - CHART_PADDING.left;
      if (plotX < 0 || plotX > chartWidth) {
        hideTooltip();
        return;
      }

      const value = minimum + (plotX / chartWidth) * span;
      const scaledUnit = (value - minimum) / span;
      const density = betaPdf(scaledUnit, alpha, beta) / span;

      showTooltip(point.clientX, point.clientY, "PERT input", [
        `Value: ${numberFormatter.format(value)}`,
        `Relative density: ${density.toExponential(2)}`,
        `Min / mode / max: ${formatAxisValue(minimum)} / ${formatAxisValue(mode)} / ${formatAxisValue(maximum)}`,
      ]);
    },
    hideTooltip,
  );
}

function lossToColor(loss, minLoss, maxLoss) {
  const ratio = maxLoss === minLoss ? 0.5 : (loss - minLoss) / (maxLoss - minLoss);
  const red = Math.round(56 + ratio * 192);
  const green = Math.round(189 - ratio * 113);
  const blue = Math.round(248 - ratio * 88);
  return `rgb(${red}, ${green}, ${blue})`;
}

function renderScatterPlot(canvas, scatterPoints) {
  if (!scatterPoints.length) {
    canvas.hidden = true;
    return;
  }

  canvas.hidden = false;

  const { context, width, height } = setupCanvas(canvas, SCATTER_CHART_HEIGHT);
  drawChartBackground(context, width, height);

  const { chartWidth, chartHeight } = getPlotArea(width, height);
  const frequencies = scatterPoints.map((point) => point.frequency);
  const magnitudes = scatterPoints.map((point) => point.magnitude);
  const losses = scatterPoints.map((point) => point.aggregate_loss);
  const minFrequency = Math.min(...frequencies);
  const maxFrequency = Math.max(...frequencies);
  const minMagnitude = Math.min(...magnitudes);
  const maxMagnitude = Math.max(...magnitudes);
  const minLoss = Math.min(...losses);
  const maxLoss = Math.max(...losses);
  const xTicks = computeTicks(minFrequency, maxFrequency, 5);
  const yTicks = computeTicks(minMagnitude, maxMagnitude, 5);
  const plottedPoints = scatterPoints.map((point) => ({
    ...point,
    x: valueToX(point.frequency, minFrequency, maxFrequency, chartWidth),
    y: valueToY(point.magnitude, minMagnitude, maxMagnitude, chartHeight),
    color: lossToColor(point.aggregate_loss, minLoss, maxLoss),
  }));

  drawAxes(context, width, height, {
    xMin: minFrequency,
    xMax: maxFrequency,
    yMin: minMagnitude,
    yMax: maxMagnitude,
    xLabel: "Frequency (events / year)",
    yLabel: "Magnitude ($)",
    xTicks,
    yTicks,
  });

  plottedPoints.forEach((point) => {
    context.fillStyle = point.color;
    context.beginPath();
    context.arc(point.x, point.y, 3, 0, Math.PI * 2);
    context.fill();
  });

  drawLegend(context, [
    { label: `Low loss (${formatAxisValue(minLoss)})`, color: lossToColor(minLoss, minLoss, maxLoss) },
    { label: `High loss (${formatAxisValue(maxLoss)})`, color: lossToColor(maxLoss, minLoss, maxLoss) },
  ], width);

  attachChartInteraction(
    canvas,
    (event) => {
      const point = getCanvasPoint(canvas, event);
      let nearest = null;
      let nearestDistance = Infinity;

      plottedPoints.forEach((candidate) => {
        const distance = Math.hypot(point.x - candidate.x, point.y - candidate.y);
        if (distance < nearestDistance && distance <= 12) {
          nearest = candidate;
          nearestDistance = distance;
        }
      });

      if (!nearest) {
        hideTooltip();
        return;
      }

      showTooltip(point.clientX, point.clientY, "Simulation draw", [
        `Frequency: ${numberFormatter.format(nearest.frequency)}`,
        `Magnitude: ${numberFormatter.format(nearest.magnitude)}`,
        `Aggregate loss: ${numberFormatter.format(nearest.aggregate_loss)}`,
      ]);
    },
    hideTooltip,
  );
}

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

  renderHistogram(frequencyChart, data.frequency.histogram, {
    barColor: "#38bdf8",
    xLabel: "Frequency (events / year)",
    yLabel: "Simulation count",
    tooltipTitle: "Frequency bin",
  });
  renderHistogram(magnitudeChart, data.magnitude.histogram, {
    barColor: "#4ade80",
    xLabel: "Magnitude ($)",
    yLabel: "Simulation count",
    tooltipTitle: "Magnitude bin",
  });
  renderHistogram(aggregateLossChart, data.aggregate_loss.histogram, {
    barColor: "#fbbf24",
    xLabel: "Annual loss ($)",
    yLabel: "Simulation count",
    tooltipTitle: "Loss bin",
    markers: [
      {
        value: data.aggregate_loss.var_95,
        label: "VaR 95",
        color: "#f87171",
      },
      {
        value: data.aggregate_loss.var_99,
        label: "VaR 99",
        color: "#fb923c",
      },
      {
        value: data.aggregate_loss.tvar_95,
        label: "TVaR 95",
        color: "#f472b6",
      },
    ],
  });
  renderExceedanceCurve(lecChart, data.aggregate_loss.exceedance_curve);
  renderPertDiagram(
    frequencyPertChart,
    data.frequency.distribution,
    "#38bdf8",
    "Frequency (events / year)",
  );
  renderPertDiagram(
    magnitudePertChart,
    data.magnitude.distribution,
    "#4ade80",
    "Magnitude ($)",
  );
  renderScatterPlot(scatterChart, data.scatter);

  lastSimulationData = data;
  exportPdfButton.disabled = false;
  resultsSection.hidden = false;
  emptyState.hidden = true;
}

function pdfPageBottom(doc) {
  return doc.internal.pageSize.getHeight() - PDF_MARGIN;
}

function pdfPageWidth(doc) {
  return doc.internal.pageSize.getWidth();
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

function pdfAddColumnBlock(doc, x, y, width, title, rows) {
  let cursorY = pdfAddTextLine(doc, x, y, title, { fontSize: 10, bold: true, color: [15, 23, 42] });
  const labelWidth = width * 0.52;

  rows.forEach(([label, value]) => {
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

  y = pdfAddTextLine(doc, PDF_MARGIN, y, "CRQ Monte Carlo Simulation Report", {
    fontSize: 15,
    bold: true,
    color: [15, 23, 42],
  });
  y = pdfAddTextLine(doc, PDF_MARGIN, y, `Generated: ${generatedAt}`, { fontSize: 9, color: [71, 85, 105] });
  y = pdfAddTextLine(
    doc,
    PDF_MARGIN,
    y,
    `Seed: ${data.seed}  |  Iterations: ${numberFormatter.format(data.iterations)}`,
    { fontSize: 9, color: [71, 85, 105] },
  );
  y += PDF_SECTION_GAP;

  const usableWidth = pdfUsableWidth(doc);
  const columnWidth = (usableWidth - 8) / 2;
  const leftX = PDF_MARGIN;
  const rightX = PDF_MARGIN + columnWidth + 8;

  y = pdfAddTextLine(doc, PDF_MARGIN, y, "Input parameters", {
    fontSize: 11,
    bold: true,
    color: [15, 23, 42],
  });
  y += 1;

  const inputBottom = Math.max(
    pdfAddColumnBlock(doc, leftX, y, columnWidth, "Frequency", buildDistributionRowsShort(data.frequency.distribution)),
    pdfAddColumnBlock(doc, rightX, y, columnWidth, "Magnitude", buildDistributionRowsShort(data.magnitude.distribution)),
  );
  y = inputBottom + PDF_SECTION_GAP;

  y = pdfAddTextLine(doc, PDF_MARGIN, y, "Simulation results", {
    fontSize: 11,
    bold: true,
    color: [15, 23, 42],
  });
  y += 1;

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

  const resultsBottom = Math.max(
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

  return resultsBottom;
}

function pdfStartChartPages(doc) {
  doc.addPage();
  return PDF_MARGIN;
}

function pdfAddChartBlock(doc, y, canvas, title, chartHeight) {
  if (!canvas || canvas.hidden) {
    return y;
  }

  const blockHeight = PDF_CHART_TITLE_HEIGHT + chartHeight + PDF_CHART_GAP;
  if (y + blockHeight > pdfPageBottom(doc)) {
    doc.addPage();
    y = PDF_MARGIN;
  }

  doc.setFont("helvetica", "bold");
  doc.setFontSize(11);
  doc.setTextColor(15, 23, 42);
  doc.text(title, PDF_MARGIN, y + 4);
  y += PDF_CHART_TITLE_HEIGHT;

  const maxWidth = pdfUsableWidth(doc);
  const aspectRatio = canvas.height / canvas.width;
  let drawHeight = chartHeight;
  let drawWidth = drawHeight / aspectRatio;
  if (drawWidth > maxWidth) {
    drawWidth = maxWidth;
    drawHeight = drawWidth * aspectRatio;
  }

  const imageData = canvas.toDataURL("image/png");
  doc.addImage(imageData, "PNG", PDF_MARGIN, y, drawWidth, drawHeight);
  return y + drawHeight + PDF_CHART_GAP;
}

function pdfAddChartPages(doc, canvases) {
  let y = pdfStartChartPages(doc);

  canvases.forEach(({ canvas, title, height }) => {
    y = pdfAddChartBlock(doc, y, canvas, title, height);
  });
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

async function exportSimulationPdf() {
  if (!lastSimulationData) {
    setStatus("Run a simulation before exporting.", "error");
    return;
  }

  if (!window.jspdf?.jsPDF) {
    setStatus("PDF library failed to load. Check your network connection.", "error");
    return;
  }

  exportPdfButton.disabled = true;
  exportPdfButton.textContent = "Exporting...";
  hideTooltip();

  try {
    const data = lastSimulationData;
    const { jsPDF } = window.jspdf;
    const doc = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4" });

    pdfAddSummaryPage(doc, data);
    pdfAddChartPages(doc, [
      { canvas: frequencyChart, title: "Frequency Histogram", height: PDF_STANDARD_CHART_HEIGHT },
      { canvas: magnitudeChart, title: "Magnitude Histogram", height: PDF_STANDARD_CHART_HEIGHT },
      { canvas: aggregateLossChart, title: "Aggregate Loss Histogram", height: PDF_STANDARD_CHART_HEIGHT },
      { canvas: lecChart, title: "Loss Exceedance Curve", height: PDF_STANDARD_CHART_HEIGHT },
      { canvas: frequencyPertChart, title: "Frequency PERT", height: PDF_STANDARD_CHART_HEIGHT },
      { canvas: magnitudePertChart, title: "Magnitude PERT", height: PDF_STANDARD_CHART_HEIGHT },
      { canvas: scatterChart, title: "Frequency vs Magnitude", height: PDF_SCATTER_CHART_HEIGHT },
    ]);

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
    renderResults(data);
  } catch (error) {
    emptyState.hidden = false;
    resultsSection.hidden = true;
    exportPdfButton.disabled = true;
    setStatus("Stored simulation results could not be loaded.", "error");
  }
}

document.addEventListener("DOMContentLoaded", initResultPage);
