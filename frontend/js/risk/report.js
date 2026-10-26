const PDF_MARGIN = 14;
const COLORS = {
  ink: [15, 23, 42],
  slate: [71, 85, 105],
  muted: [100, 116, 139],
  body: [30, 41, 59],
  line: [226, 232, 240],
  zebra: [248, 250, 252],
  header: [241, 245, 249],
  accent: [2, 132, 199],
};

function ratioText(value) {
  if (value == null || Number.isNaN(Number(value))) return "N/A";
  return Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function percent(value) {
  if (value == null || Number.isNaN(Number(value))) return "N/A";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function pdfProse(text) {
  return String(text ?? "");
}

function amount(value) {
  if (value == null || Number.isNaN(Number(value))) return "N/A";
  const sign = Number(value) < 0 ? "-" : "";
  return `${sign}${Math.abs(Number(value)).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function wrap(doc, text, width, size = 9, bold = false) {
  doc.setFont("helvetica", bold ? "bold" : "normal");
  doc.setFontSize(size);
  const safeWidth = Math.max(width, 1);
  return doc.splitTextToSize(String(text ?? ""), safeWidth).flatMap((line) => breakWideLine(doc, line, safeWidth));
}

function breakWideLine(doc, line, width) {
  if (!line || doc.getTextWidth(line) <= width + 0.2) return [line];
  const parts = [];
  let current = "";
  for (const character of line) {
    const next = current + character;
    if (current && doc.getTextWidth(next) > width) {
      parts.push(current);
      current = character;
    } else {
      current = next;
    }
  }
  if (current) parts.push(current);
  return parts;
}

function textStep(doc, size) {
  doc.setFontSize(size);
  return doc.getLineHeight() / doc.internal.scaleFactor;
}

function toleranceText(item) {
  if (item.status === "Draft" || item.in_appetite_test === false) return "Excluded";
  if (item.above_tolerance == null) return "Not defined";
  return item.above_tolerance ? "Yes" : "No";
}

const MIN_SECTION_GAP = 4;

function renderBoardReport(report, preview) {
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4", compress: true });
  const layout = {
    doc,
    y: PDF_MARGIN,
    width: doc.internal.pageSize.getWidth() - PDF_MARGIN * 2,
    bottom: doc.internal.pageSize.getHeight() - 16,
    measuring: false,
    keep: false,
  };
  const blocks = [
    (target) => drawCover(target, report),
    (target) => drawNarrative(target, report),
    (target) => drawAppetite(target, report),
    (target) => drawPortfolio(target, report),
    (target) => drawScenarios(target, report),
    (target) => drawTreatments(target, report),
    (target) => drawDecisions(target, report),
    (target) => drawAssumptions(target, report),
    (target) => drawQuality(target, report),
    (target) => drawDigests(target, report),
  ].map((draw) => ({ draw, height: measureBlock(layout, draw) }));
  const capacity = layout.bottom - PDF_MARGIN;
  const pages = packSections(blocks, capacity);

  pages.forEach((page, pageIndex) => {
    if (pageIndex > 0) newPage(layout);
    page.forEach((block, index) => {
      if (index > 0) layout.y += MIN_SECTION_GAP;
      layout.keep = block.height <= capacity + 0.4;
      block.draw(layout);
      layout.keep = false;
    });
  });
  drawFooters(layout, report);
  showPdf(doc, preview);
}

function showPdf(doc, preview) {
  const url = doc.output("bloburl");
  if (preview && !preview.closed) {
    preview.location.replace(url);
    return true;
  }
  return Boolean(window.open(url, "_blank"));
}

function measureBlock(layout, draw) {
  const { jsPDF } = window.jspdf;
  const probe = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4", compress: true });
  const probeLayout = {
    doc: probe,
    y: PDF_MARGIN,
    width: layout.width,
    bottom: Number.POSITIVE_INFINITY,
    measuring: true,
    keep: true,
  };
  draw(probeLayout);
  return probeLayout.y - PDF_MARGIN;
}

function packSections(blocks, capacity) {
  const pages = [];
  let page = [];
  let used = 0;
  blocks.forEach((block) => {
    const gap = page.length ? MIN_SECTION_GAP : 0;
    if (page.length && used + gap + block.height > capacity + 0.2) {
      pages.push(page);
      page = [];
      used = 0;
    }
    page.push(block);
    used += (page.length > 1 ? MIN_SECTION_GAP : 0) + block.height;
  });
  if (page.length) pages.push(page);
  return pages;
}

function newPage(layout) {
  layout.doc.addPage();
  layout.y = PDF_MARGIN;
}

function ensure(layout, height) {
  if (layout.measuring || layout.keep) return;
  if (layout.y + height > layout.bottom) newPage(layout);
}

function write(doc, x, y, text, { size = 9, bold = false, color = COLORS.body, align } = {}) {
  doc.setFont("helvetica", bold ? "bold" : "normal");
  doc.setFontSize(size);
  doc.setTextColor(...color);
  doc.text(String(text), x, y, align ? { align } : undefined);
  return y + size * 0.38 + 1.5;
}

function section(layout, title) {
  const lines = wrap(layout.doc, title, layout.width, 11, true);
  lines.forEach((line) => {
    layout.y = write(layout.doc, PDF_MARGIN, layout.y, line, { size: 11, bold: true, color: COLORS.ink });
  });
  layout.doc.setDrawColor(...COLORS.line);
  layout.doc.setLineWidth(0.3);
  layout.doc.line(PDF_MARGIN, layout.y - 2.2, PDF_MARGIN + layout.width, layout.y - 2.2);
  layout.y += 2.5;
}

function paragraph(layout, text, { size = 9, color = COLORS.body, gap = 1.6 } = {}) {
  const leading = size * 0.42 + 1.15;
  const lines = wrap(layout.doc, text, layout.width, size);
  lines.forEach((line) => {
    ensure(layout, leading);
    write(layout.doc, PDF_MARGIN, layout.y, line, { size, color });
    layout.y += leading;
  });
  layout.y += gap;
}

function keyValues(layout, rows) {
  const labelWidth = layout.width * 0.46;
  const valueWidth = layout.width - labelWidth - 4;
  const size = 8;
  const step = textStep(layout.doc, size);
  rows.forEach(([label, value], index) => {
    const labelLines = wrap(layout.doc, label, labelWidth - 3, size, true);
    const valueLines = wrap(layout.doc, value, valueWidth, size);
    const lineCount = Math.max(labelLines.length, valueLines.length, 1);
    const rowHeight = lineCount * step + 2.1;
    ensure(layout, rowHeight);
    if (index % 2 === 0) {
      layout.doc.setFillColor(...COLORS.zebra);
      layout.doc.rect(PDF_MARGIN, layout.y - 3.3, layout.width, rowHeight, "F");
    }
    layout.doc.setFont("helvetica", "bold");
    layout.doc.setFontSize(size);
    layout.doc.setTextColor(...COLORS.slate);
    layout.doc.text(labelLines, PDF_MARGIN + 1.6, layout.y);
    layout.doc.setFont("helvetica", "normal");
    layout.doc.setTextColor(...COLORS.body);
    layout.doc.text(valueLines, PDF_MARGIN + labelWidth, layout.y);
    layout.y += rowHeight;
  });
  layout.y += 2;
}

function table(layout, columns, rows) {
  const widths = fitColumns(columns, layout.width);
  const headerSize = 7.5;
  const bodySize = 8;
  const pad = 1.8;
  const headerStep = textStep(layout.doc, headerSize);
  const bodyStep = textStep(layout.doc, bodySize);
  const headerLines = widths.map((column) => wrap(layout.doc, column.title, column.width - pad * 2, headerSize, true));
  const headerCount = Math.max(...headerLines.map((lines) => lines.length), 1);
  const headerTop = 3.4;
  const headerBelow = 1.8;
  const headerHeight = headerTop + (headerCount - 1) * headerStep + headerBelow;

  const drawHeader = () => {
    ensure(layout, headerHeight + 2);
    layout.doc.setFillColor(...COLORS.header);
    layout.doc.rect(PDF_MARGIN, layout.y - headerTop, layout.width, headerHeight, "F");
    let x = PDF_MARGIN;
    headerLines.forEach((lines, index) => {
      const column = widths[index];
      layout.doc.setFont("helvetica", "bold");
      layout.doc.setFontSize(headerSize);
      layout.doc.setTextColor(...COLORS.slate);
      layout.doc.text(lines, textAnchor(x, column, pad), layout.y, { align: textAlign(column) });
      x += column.width;
    });
    const ruleY = layout.y + (headerCount - 1) * headerStep + headerBelow - 0.4;
    layout.doc.setDrawColor(...COLORS.line);
    layout.doc.setLineWidth(0.2);
    layout.doc.line(PDF_MARGIN, ruleY, PDF_MARGIN + layout.width, ruleY);
    layout.y = ruleY + 3.1;
  };

  drawHeader();
  if (!rows.length) {
    paragraph(layout, "None.", { color: COLORS.muted, gap: 1 });
    return;
  }
  rows.forEach((row, index) => {
    const cells = widths.map((column, cellIndex) =>
      wrap(layout.doc, row[cellIndex], column.width - pad * 2, bodySize),
    );
    const lineCount = Math.max(...cells.map((cell) => cell.length), 1);
    const rowHeight = lineCount * bodyStep + 2.2;
    if (!layout.measuring && !layout.keep && layout.y + rowHeight > layout.bottom) {
      newPage(layout);
      drawHeader();
    }
    if (index % 2 === 0) {
      layout.doc.setFillColor(...COLORS.zebra);
      layout.doc.rect(PDF_MARGIN, layout.y - 3.3, layout.width, rowHeight, "F");
    }
    let x = PDF_MARGIN;
    cells.forEach((cell, cellIndex) => {
      const column = widths[cellIndex];
      layout.doc.setFont("helvetica", "normal");
      layout.doc.setFontSize(bodySize);
      layout.doc.setTextColor(...COLORS.body);
      layout.doc.text(cell, textAnchor(x, column, pad), layout.y, { align: textAlign(column) });
      x += column.width;
    });
    layout.y += rowHeight;
  });
  layout.doc.setDrawColor(...COLORS.line);
  layout.doc.setLineWidth(0.2);
  layout.doc.line(PDF_MARGIN, layout.y - 1.2, PDF_MARGIN + layout.width, layout.y - 1.2);
  layout.y += 3;
}

function textAlign(column) {
  return column.align === "left" ? "left" : "center";
}

function textAnchor(x, column, pad) {
  return textAlign(column) === "left" ? x + pad : x + column.width / 2;
}

function fitColumns(columns, total) {
  const claimed = columns.reduce((sum, column) => sum + (column.fraction || 0), 0);
  const flexible = columns.filter((column) => !column.fraction).length;
  const flexibleShare = flexible ? (total * (1 - claimed)) / flexible : 0;
  let used = 0;
  return columns.map((column, index) => {
    const width = index === columns.length - 1
      ? total - used
      : (column.fraction ? total * column.fraction : flexibleShare);
    used += width;
    return { ...column, width };
  });
}

function drawCover(layout, report) {
  const meta = report.meta || {};
  const generated = meta.generated_at ? new Date(meta.generated_at).toLocaleString() : "";
  layout.doc.setFillColor(...COLORS.accent);
  layout.doc.rect(PDF_MARGIN, layout.y - 4, 1.4, 16, "F");
  const x = PDF_MARGIN + 4;
  const textWidth = layout.width - 4;
  writeLines(layout, x, "CRQ Board Risk Report", { size: 15, bold: true, color: COLORS.ink, width: textWidth });
  writeLines(layout, x, `${meta.record_id || "Draft"}${meta.status ? `  ·  ${meta.status}` : ""}`, {
    size: 9,
    color: COLORS.slate,
    width: textWidth,
  });
  writeLines(layout, x, `Generated: ${generated}`, { size: 9, color: COLORS.slate, width: textWidth });
  writeLines(
    layout,
    x,
    `Model ${meta.model_version || "—"}  ·  Benchmarks ${meta.benchmarks_version || "—"}  ·  Seed ${meta.seed ?? "—"}  ·  Iterations ${Number(meta.iterations || 0).toLocaleString()}`,
    { size: 9, color: COLORS.slate, width: textWidth },
  );
  layout.y += 4;
}

function writeLines(layout, x, text, options) {
  const width = options.width || layout.width;
  const lines = wrap(layout.doc, text, width, options.size || 9, Boolean(options.bold));
  lines.forEach((line) => {
    layout.y = write(layout.doc, x, layout.y, line, options);
  });
}

function drawNarrative(layout, report) {
  const narrative = report.narrative || {};
  section(layout, "Narrative");
  [narrative.headline, narrative.exposure, narrative.appetite, narrative.treatment, narrative.decisions]
    .filter(Boolean)
    .forEach((text) => paragraph(layout, pdfProse(text)));
}

function drawAppetite(layout, report) {
  const appetite = report.appetite || {};
  const limits = appetite.limits || {};
  section(layout, "Risk appetite");
  paragraph(layout, appetite.statement || "No appetite statement is defined.", { color: COLORS.slate });
  paragraph(layout, "Draft scenarios are excluded from the appetite test.", { size: 8, color: COLORS.muted });
  keyValues(layout, [
    ["Annual Loss Expectancy appetite", `${amount(limits.portfolio_ale_limit)}  ·  ${appetite.evaluation?.portfolio_ale?.status || "Not defined"}`],
    ["Value at Risk 95 appetite", `${amount(limits.portfolio_var95_limit)}  ·  ${appetite.evaluation?.portfolio_var_95?.status || "Not defined"}`],
    ["Scenario Annual Loss Expectancy tolerance", amount(limits.scenario_ale_tolerance)],
    ["Annual treatment budget", amount(limits.annual_treatment_budget)],
    ["Approval threshold", amount(limits.approval_threshold)],
    ["Amortisation years", limits.amortisation_years ?? "N/A"],
  ]);
}

function drawPortfolio(layout, report) {
  const portfolio = report.portfolio || {};
  section(layout, "Portfolio exposure");
  table(
    layout,
    [
      { title: "Control set", width: 26 },
      { title: "Expected loss", width: 30, align: "right" },
      { title: "Value at Risk 95", width: 32, align: "right" },
      { title: "Tail Value at Risk 95", width: 40, align: "right" },
      { title: "Probability of a Loss Year", width: 54, align: "right" },
    ],
    [
      ["Inherent", "inherent"],
      ["Current", "current"],
      ["Target", "target"],
      ["Recommended", "recommended"],
    ].map(([label, key]) => {
      const row = portfolio[key] || {};
      return [label, amount(row.mean), amount(row.var_95), amount(row.tvar_95), percent(row.probability_of_loss_year)];
    }),
  );
  if (portfolio.independence_note) {
    paragraph(layout, `NOTE: ${portfolio.independence_note}`, { size: 8, color: COLORS.muted, gap: 1 });
  }
}

function drawScenarios(layout, report) {
  section(layout, "Scenarios");
  table(
    layout,
    [
      { title: "Scenario" },
      { title: "Name", fraction: 2 / 5 },
      { title: "Current" },
      { title: "Target" },
      { title: "Above tolerance" },
    ],
    (report.scenarios || []).map((item) => [
      item.scenario_id,
      item.scenario || "",
      amount(item.current?.mean),
      amount(item.target?.mean),
      toleranceText(item),
    ]),
  );
}

function drawTreatments(layout, report) {
  const treatments = report.treatments || {};
  const recommendation = treatments.recommendation || {};
  section(layout, "Treatments");
  keyValues(layout, [
    ["Selected", (recommendation.selected_control_ids || []).join(", ") || "none"],
    ["Annualised cost", amount(recommendation.total_annualised_cost)],
    ["Expected reduction", amount(recommendation.expected_reduction)],
  ]);
  table(
    layout,
    [
      { title: "Control", width: 24 },
      { title: "Annualised", width: 32, align: "right" },
      { title: "Reduction", width: 32, align: "right" },
      { title: "Benefit-Cost Ratio", width: 36, align: "right" },
      { title: "Return on Security Investment", width: 48, align: "right" },
      { title: "Net benefit", width: 50, align: "right" },
    ],
    (treatments.candidates || []).map((item) => [
      item.control_id,
      amount(item.annualised_cost),
      amount(item.standalone_reduction),
      ratioText(item.benefit_cost_ratio),
      ratioText(item.rosi),
      amount(item.net_benefit),
    ]),
  );
  const unranked = treatments.unranked || [];
  if (unranked.length) {
    paragraph(layout, "Unranked", { size: 10, color: COLORS.accent, gap: 1 });
    unranked.forEach((item) => paragraph(layout, `${item.control_id}  ·  ${item.reason}`, { size: 8, color: COLORS.slate, gap: 0.4 }));
    layout.y += 1.5;
  }
}

function drawDecisions(layout, report) {
  section(layout, "Decisions requiring approval");
  const items = report.decisions || [];
  if (!items.length) {
    paragraph(layout, "None.", { color: COLORS.muted });
    return;
  }
  items.forEach((item) => {
    const textWidth = layout.width - 8;
    const step = textStep(layout.doc, 8);
    const heading = wrap(
      layout.doc,
      `${item.decision_id || ""}   ·   ${item.type || ""}   ·   ${item.approval_level || "—"}   ·   ${amount(item.amount)}`,
      textWidth,
      8,
      true,
    );
    const rationale = wrap(layout.doc, pdfProse(item.rationale || ""), textWidth, 8);
    const height = 1.6 + heading.length * step + 1.4 + rationale.length * step + 2.4;
    ensure(layout, height + 1);
    layout.doc.setFillColor(...COLORS.accent);
    layout.doc.rect(PDF_MARGIN, layout.y - 3.2, 1.2, Math.max(height - 1.6, 4), "F");
    layout.doc.setFont("helvetica", "bold");
    layout.doc.setFontSize(8);
    layout.doc.setTextColor(...COLORS.ink);
    layout.doc.text(heading, PDF_MARGIN + 4, layout.y);
    layout.y += heading.length * step + 1.3;
    layout.doc.setFont("helvetica", "normal");
    layout.doc.setTextColor(...COLORS.slate);
    layout.doc.text(rationale, PDF_MARGIN + 4, layout.y);
    layout.y += rationale.length * step + 2.6;
  });
}

function drawAssumptions(layout, report) {
  section(layout, "Assumptions");
  (report.assumptions || []).forEach((text, index) => paragraph(layout, `${index + 1}.  ${text}`));
}

function drawQuality(layout, report) {
  const quality = report.data_quality || {};
  section(layout, "Data quality");
  paragraph(layout, `Known Exploited Vulnerability catalog checked at: ${quality.kev_checked_at ? new Date(quality.kev_checked_at).toLocaleString() : "unknown"}`, {
    color: COLORS.slate,
  });
  const gaps = quality.scenarios_with_gaps || [];
  table(
    layout,
    [
      { title: "Scenario" },
      { title: "Gaps", fraction: 0.7, align: "left" },
    ],
    gaps.map((item) => [item.scenario_id, (item.gaps || []).join("\n")]),
  );
}

function drawDigests(layout, report) {
  section(layout, "Input digest");
  table(
    layout,
    [
      { title: "Input" },
      { title: "Rows" },
      { title: "SHA-256", fraction: 0.7, align: "left" },
    ],
    Object.entries(report.inputs_digest || {}).map(([name, digest]) => [
      name.replaceAll("_", " "),
      digest.rows ?? "",
      digest.sha256 || "",
    ]),
  );
}

function drawFooters(layout, report) {
  const doc = layout.doc;
  const pageCount = doc.getNumberOfPages();
  const footerY = doc.internal.pageSize.getHeight() - 8;
  const record = report.meta?.record_id || "Draft";
  for (let page = 1; page <= pageCount; page += 1) {
    doc.setPage(page);
    doc.setDrawColor(...COLORS.line);
    doc.setLineWidth(0.3);
    doc.line(PDF_MARGIN, footerY - 3.5, doc.internal.pageSize.getWidth() - PDF_MARGIN, footerY - 3.5);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(7.5);
    doc.setTextColor(...COLORS.muted);
    doc.text(`CRQ Board Risk Report  |  ${record}`, PDF_MARGIN, footerY);
    doc.text(`Page ${page} of ${pageCount}`, doc.internal.pageSize.getWidth() - PDF_MARGIN, footerY, { align: "right" });
  }
}
