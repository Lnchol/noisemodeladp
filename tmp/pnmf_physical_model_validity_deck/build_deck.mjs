import fs from "node:fs/promises";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const W = 1280;
const H = 720;
const M = 58;
const INK = "#111111";
const MUTED = "#5F6670";
const RULE = "#B8BCC4";
const PANEL = "#EDEDED";
const PANEL_DARK = "#D9DDE3";
const BLUE = "#3D8DFF";
const BLUE_LIGHT = "#D8F1FF";
const WHITE = "#FFFFFF";
const FONT = "Arial";
const finalPath = "C:/Users/efeko/adp/framework/pnmf_project_2/pnmf_project/projects/pnmf/output/PNMF_Physical_Model_Validity_Assessment.pptx";
const fleetValidationPath = "C:/Users/efeko/adp/framework/pnmf_project_2/pnmf_project/projects/pnmf/outputs/physics_fleet_validation.csv";
const workOut = "C:/Users/efeko/adp/framework/pnmf_project_2/pnmf_project/tmp/pnmf_physical_model_validity_deck/rendered";
let autoTextId = 0;

function addText(slide, name, value, position, options = {}) {
  if (typeof value !== "string") {
    options = position;
    position = value;
    value = name;
    name = `auto-text-${autoTextId++}`;
  }
  const shape = slide.shapes.add({ geometry: "textbox", name, position,
    fill: "none", line: { style: "solid", fill: "none", width: 0 } });
  shape.text = value;
  shape.text.style = {
    fontSize: options.fontSize ?? 20,
    typeface: options.typeface ?? FONT,
    color: options.color ?? INK,
    bold: options.bold ?? false,
    italic: options.italic ?? false,
    alignment: options.alignment ?? "left",
    verticalAlignment: options.verticalAlignment ?? "top",
    autoFit: options.autoFit ?? "shrinkText",
    wrap: "square",
    insets: options.insets ?? { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return shape;
}

function addBox(slide, name, position, options = {}) {
  const geometry = options.geometry ?? "roundRect";
  const config = { geometry, name, position,
    fill: options.fill ?? WHITE,
    line: { style: "solid", fill: options.line ?? RULE, width: options.lineWidth ?? 1 } };
  if (geometry !== "rect") config.borderRadius = options.borderRadius ?? "rounded-lg";
  return slide.shapes.add(config);
}

function addRule(slide, name, left, top, width, color = RULE, height = 2) {
  return slide.shapes.add({ geometry: "rect", name,
    position: { left, top, width, height }, fill: color,
    line: { style: "solid", fill: color, width: 0 } });
}

function addTitle(slide, title, kicker, page) {
  addText(slide, `kicker-${page}`, kicker.toUpperCase(),
    { left: M, top: 34, width: 620, height: 24 },
    { fontSize: 15, bold: true, color: BLUE });
  addText(slide, `title-${page}`, title,
    { left: M, top: 65, width: 1150, height: 62 },
    { fontSize: 38, bold: true, color: INK, autoFit: "shrinkText" });
  addRule(slide, `rule-${page}`, M, 137, 1164, RULE, 1);
  addText(slide, `footer-${page}`, `PNMF  |  physical-model validity  |  ${page}`,
    { left: M, top: 680, width: 720, height: 18 },
    { fontSize: 12, color: MUTED });
}

function addNotes(slide, text) {
  slide.speakerNotes.textFrame.setText(text);
  slide.speakerNotes.setVisible(true);
}

function addBulletList(slide, name, items, position, options = {}) {
  return addText(slide, name, items.map((item) => `| ${item}`).join("\n"), position, {
    fontSize: options.fontSize ?? 20, color: options.color ?? INK,
    bold: options.bold ?? false, ...options,
  });
}

function addCell(slide, name, text, left, top, width, height, options = {}) {
  addBox(slide, `${name}-box`, { left, top, width, height }, {
    geometry: "rect", fill: options.fill ?? WHITE, line: options.line ?? RULE,
    lineWidth: options.lineWidth ?? 1, borderRadius: "square",
  });
  return addText(slide, `${name}-text`, text,
    { left: left + (options.pad ?? 12), top: top + (options.topPad ?? 8),
      width: width - 2 * (options.pad ?? 12), height: height - 2 * (options.topPad ?? 8) },
    { fontSize: options.fontSize ?? 16, bold: options.bold ?? false,
      color: options.color ?? INK, verticalAlignment: options.verticalAlignment ?? "middle" });
}

function addTag(slide, name, label, left, top, width, fill = PANEL, color = INK) {
  addBox(slide, name, { left, top, width, height: 34 }, { fill, line: fill, borderRadius: "rounded-md" });
  addText(slide, `${name}-text`, label, { left: left + 8, top: top + 7, width: width - 16, height: 20 },
    { fontSize: 15, bold: true, color, alignment: "center", verticalAlignment: "middle" });
}

function cover(presentation) {
  const slide = presentation.slides.add(); slide.background.fill = WHITE;
  addRule(slide, "cover-blue-bar", 58, 58, 12, BLUE, 588);
  addText(slide, "cover-kicker", "PNMF  /  EVIDENCE REVIEW", { left: 104, top: 88, width: 700, height: 28 }, { fontSize: 18, bold: true, color: BLUE });
  addText(slide, "cover-title", "Evaluating PNMF's\nPhysical-Model Validity", { left: 104, top: 174, width: 790, height: 190 }, { fontSize: 55, bold: true, color: INK });
  addText(slide, "cover-subtitle", "Current evidence, improvement priorities, and explicit limits.", { left: 106, top: 404, width: 760, height: 62 }, { fontSize: 25, color: MUTED });
  addRule(slide, "cover-rule", 106, 514, 520, RULE, 1);
  addText(slide, "cover-date", "Advisor review  |  03 August 2026", { left: 106, top: 536, width: 520, height: 26 }, { fontSize: 17, color: MUTED });
  addBox(slide, "cover-boundary", { left: 900, top: 224, width: 286, height: 214 }, { fill: PANEL, line: PANEL, borderRadius: "rounded-xl" });
  addText(slide, "cover-boundary-title", "Validity boundary", { left: 928, top: 258, width: 230, height: 34 }, { fontSize: 26, bold: true, color: INK });
  addText(slide, "cover-boundary-body", "Physically coherent.\nSoftware-auditable.\n\nConceptual screening only.\nNot certification evidence.", { left: 928, top: 308, width: 228, height: 116 }, { fontSize: 18, color: MUTED });
  addNotes(slide, "[Sources]\nScope and wording: projects/pnmf/docs/ADVISOR_PRESENTATION_TEXT.md; projects/pnmf/docs/NPD_SYSTEM_DESIGN.md.\nNo external assets used.");
}

function verdict(presentation) {
  const slide = presentation.slides.add(); slide.background.fill = WHITE;
  addTitle(slide, "Validity is claim-specific, not binary", "01  /  current verdict", 2);
  addText(slide, "The current route clears a software and physical-coherence bar. It does not yet clear an independent measurement-validity bar.", { left: M, top: 176, width: 1110, height: 64 }, { fontSize: 27, bold: true, color: INK });
  const xs = [58, 420, 700, 930]; const ws = [362, 280, 230, 292];
  const head = ["Claim", "Current evidence", "Status", "What remains unproven"];
  for (let c = 0; c < 4; c += 1) addCell(slide, `v-head-${c}`, head[c], xs[c], 270, ws[c], 44, { fill: INK, line: INK, color: WHITE, bold: true, fontSize: 16 });
  const rows = [
    ["Physical plausibility", "Mechanistic scaling + SI boundary", "SUPPORTED", "Measurement residuals"],
    ["Implementation correctness", "Unit, gate, provenance, regression tests", "SUPPORTED", "Real-world accuracy"],
    ["A320-211 anchoring", "Frozen fit to ANP SEL/LAmax", "CONDITIONAL", "Independent component proof"],
    ["Predictive / transfer validity", "No component ledger or held-out family study", "NOT DEMONSTRATED", "Unseen engine/configuration behavior"],
  ];
  for (let r = 0; r < rows.length; r += 1) {
    const y = 314 + r * 67;
    for (let c = 0; c < 4; c += 1) addCell(slide, `v-${r}-${c}`, rows[r][c], xs[c], y, ws[c], 67, { fill: r % 2 === 0 ? WHITE : PANEL, line: RULE, fontSize: 16, bold: c === 0 || c === 2, color: c === 2 && r === 3 ? MUTED : INK });
  }
  addText(slide, "Use the status language to keep physical claims proportional to evidence.", { left: 170, top: 610, width: 940, height: 32 }, { fontSize: 22, bold: true, color: BLUE, alignment: "center" });
  addNotes(slide, "[Sources]\nImplementation evidence: projects/pnmf/pnmf/physics.py; projects/pnmf/tests/test_physics.py.\nCalibration and route boundary: projects/pnmf/pnmf/api.py; projects/pnmf/docs/NPD_SYSTEM_DESIGN.md.\nEvidence framing: NASA Dahl, https://ntrs.nasa.gov/citations/20080032565.");
}

function auditMethod(presentation) {
  const slide = presentation.slides.add(); slide.background.fill = WHITE;
  addTitle(slide, "A validity claim needs four pieces of evidence", "02  /  audit method", 3);
  addText(slide, "Every technical statement in the deck follows the same audit pattern.", { left: M, top: 174, width: 820, height: 40 }, { fontSize: 24, color: MUTED });
  const labels = [
    ["CLAIM", "What do we want\nto say?"],
    ["EVIDENCE", "What does the\ncheckout show?"],
    ["LIMITATION", "Where does the\nclaim stop?"],
    ["NEXT PROOF", "What data would\nupgrade it?"],
  ];
  const xs = [72, 372, 672, 972]; const nodes = [];
  for (let i = 0; i < labels.length; i += 1) {
    const box = addBox(slide, `audit-box-${i}`, { left: xs[i], top: 278, width: 230, height: 156 }, { fill: i === 1 ? BLUE_LIGHT : PANEL, line: i === 1 ? BLUE_LIGHT : PANEL, borderRadius: "rounded-xl" });
    nodes.push(box);
    addText(slide, `audit-label-${i}`, labels[i][0], { left: xs[i] + 20, top: 304, width: 190, height: 26 }, { fontSize: 18, bold: true, color: i === 1 ? BLUE : MUTED, alignment: "center" });
    addText(slide, `audit-detail-${i}`, labels[i][1], { left: xs[i] + 20, top: 350, width: 190, height: 58 }, { fontSize: 23, bold: true, color: INK, alignment: "center" });
  }
  for (let i = 0; i < nodes.length - 1; i += 1) slide.shapes.connect(nodes[i], nodes[i + 1], { kind: "straight", fromSide: "right", toSide: "left", line: { style: "solid", fill: BLUE, width: 2 }, head: { type: "arrow", width: "sm", length: "sm" } });
  addBox(slide, "audit-foot", { left: 190, top: 524, width: 900, height: 74 }, { fill: WHITE, line: RULE, borderRadius: "rounded-lg" });
  addText(slide, "audit-foot-text", "A passing unit test is evidence for implementation behavior, not a substitute for a measured component comparison.", { left: 222, top: 546, width: 836, height: 32 }, { fontSize: 20, bold: true, color: INK, alignment: "center" });
  addNotes(slide, "[Sources]\nAudit structure: projects/pnmf/docs/PHYSICAL_MODEL_IMPROVEMENT_RESEARCH.md.\nValidation practice: ECAC Doc 29, 5th Edition, Volume 1, https://www.ecac-ceac.org/images/documents/ECAC-CEAC-DOC_29_5th_Edition-REPORT_ON_STANDARD_METHOD_OF_COMPUTING_NOISE_CONTOURS_AROUND_CIVIL_AIRPORTS-Volume_1-APPLICATIONS_GUIDE.pdf.\nNo external assets used.");
}

function propulsionEquations(presentation) {
  const slide = presentation.slides.add(); slide.background.fill = WHITE;
  addTitle(slide, "Simplified source laws show the key inputs", "03  /  propulsion physics", 4);
  addBox(slide, "jet-eq", { left: 58, top: 186, width: 540, height: 300 }, { fill: PANEL, line: PANEL, borderRadius: "rounded-xl" });
  addText(slide, "jet-eq-title", "JET  /  Stone-style mixing", { left: 90, top: 218, width: 410, height: 32 }, { fontSize: 25, bold: true, color: BLUE });
  addText(slide, "jet-eq-1", "Iⱼₑₜ  ∝  ρⱼ² · Aⱼ · Vⱼ⁸", { left: 90, top: 272, width: 410, height: 36 }, { fontSize: 22, bold: true, color: INK });
  addText(slide, "jet-eq-2", "Lⱼₑₜ  ≈  Cⱼₑₜ + 80 log₁₀(Vⱼ/c₀) + 10 log₁₀(Aⱼ)", { left: 90, top: 324, width: 500, height: 36 }, { fontSize: 19, bold: true, color: INK });
  addText(slide, "jet-eq-3", "fₚₑₐₖ  ≈  0.25 · fₛ꜀ₐₗₑ · Vⱼ / Dⱼ", { left: 90, top: 374, width: 470, height: 34 }, { fontSize: 20, bold: true, color: INK });
  addText(slide, "jet-eq-note", "Velocity dominates; detailed streams add density/pressure state. Fallback stays visible.", { left: 90, top: 426, width: 442, height: 42 }, { fontSize: 17, color: MUTED });
  addBox(slide, "fan-eq", { left: 632, top: 186, width: 590, height: 300 }, { fill: BLUE_LIGHT, line: BLUE_LIGHT, borderRadius: "rounded-xl" });
  addText(slide, "fan-eq-title", "FAN  /  Heidmann-style path", { left: 664, top: 218, width: 460, height: 32 }, { fontSize: 25, bold: true, color: BLUE });
  addText(slide, "fan-eq-1", "L𝒇𝒂𝒏  ≈  C𝒇𝒂𝒏 + 10 log₁₀(ṁ) + 40 log₁₀(Mₜᵢₚ)", { left: 664, top: 272, width: 540, height: 36 }, { fontSize: 20, bold: true, color: INK });
  addText(slide, "fan-eq-2", "BPF  =  Uₜᵢₚ · Nᵦₗₐdₑₛ / (π · D)", { left: 664, top: 324, width: 520, height: 34 }, { fontSize: 21, bold: true, color: INK });
  addText(slide, "fan-eq-3", "Uₜᵢₚ  =  Mₜᵢₚ · c₀", { left: 664, top: 374, width: 300, height: 30 }, { fontSize: 20, bold: true, color: INK });
  addText(slide, "fan-eq-note", "Detailed fan paths add temperature-rise, spacing, tone, and lobe terms; fallback stays visible.", { left: 664, top: 426, width: 500, height: 42 }, { fontSize: 17, color: MUTED });
  addText(slide, "Evidence dependency: mass flow, nozzle state, fan diameter, RPM/blade count, temperature rise, and provenance.", { left: 120, top: 554, width: 1040, height: 38 }, { fontSize: 21, bold: true, color: INK, alignment: "center" });
  addNotes(slide, "[Sources]\nEquations: projects/pnmf/pnmf/physics.py, module documentation and StoneSource/FanSource implementations.\nInput contract: projects/pnmf/pnmf/physics.py (EnginePhysicalInputs, FanDeck, JetStream).\nImprovement rationale: projects/pnmf/docs/PHYSICAL_MODEL_IMPROVEMENT_RESEARCH.md; NASA jet assessment https://ntrs.nasa.gov/citations/20080032565.");
}

function eventEquations(presentation) {
  const slide = presentation.slides.add(); slide.background.fill = WHITE;
  addTitle(slide, "A short event calculation keeps the boundary visible", "04  /  propagation and metrics", 5);
  addBox(slide, "airframe-eq", { left: 58, top: 184, width: 542, height: 326 }, { fill: PANEL, line: PANEL, borderRadius: "rounded-xl" });
  addText(slide, "airframe-title", "AIRFRAME  /  Fink-style laws", { left: 90, top: 216, width: 440, height: 32 }, { fontSize: 25, bold: true, color: BLUE });
  addText(slide, "airframe-list", "L𝒘ᵢₙ𝓰/𝒇ₗₐₚ  ∝  50 log₁₀(V/c₀)\nL𝓰ₑₐᵣ  ∝  60 log₁₀(V/c₀)\nδ*  =  0.37 · c̄ · Re⁻⁰·²", { left: 90, top: 278, width: 470, height: 116 }, { fontSize: 21, color: INK });
  addText(slide, "airframe-note", "Area, flap angle, wheel count, diameter, and directivity refine each component; six outputs remain inspectable.", { left: 90, top: 422, width: 470, height: 54 }, { fontSize: 17, color: MUTED });
  addBox(slide, "prop-eq", { left: 636, top: 184, width: 586, height: 326 }, { fill: BLUE_LIGHT, line: BLUE_LIGHT, borderRadius: "rounded-xl" });
  addText(slide, "prop-title", "PROPAGATION  /  EVENT OUTPUT", { left: 668, top: 216, width: 480, height: 32 }, { fontSize: 25, bold: true, color: BLUE });
  addText(slide, "prop-list", "Lₚ(f,r)  =  L₁ₘ(f) − 20 log₁₀(r / 1 m) − α(f)·r\nLₜₒₜₐₗ  =  10 log₁₀(Σᵢ 10^(Lᵢ/10))\nSEL  =  10 log₁₀[(1/1 s) ∫ 10^(Lᴬ(t)/10) dt]\nLᴬ,ₘₐₓ  =  maxₜ Lᴬ(t)", { left: 668, top: 278, width: 530, height: 150 }, { fontSize: 19, color: INK });
  addText(slide, "prop-note", "A-weighting is applied before the two metrics; the reference event is 160 kt, straight-level, 69 angles.", { left: 668, top: 442, width: 520, height: 48 }, { fontSize: 17, color: MUTED });
  addText(slide, "160 kt straight-level reference event  |  69 emission angles  |  SEL + LAmax only", { left: 154, top: 564, width: 972, height: 36 }, { fontSize: 21, bold: true, color: INK, alignment: "center" });
  addNotes(slide, "[Sources]\nAirframe, propagation, and metric equations: projects/pnmf/pnmf/physics.py; projects/pnmf/docs/NPD_SYSTEM_DESIGN.md.\nReference event: projects/pnmf/pnmf/physics.py (Reference160KtFlightPath, NPD_REF_SPEED_MS).\nMetric boundary: projects/pnmf/pnmf/api.py (physics route supports SEL and LAmax only).");
}

async function loadFleetValidation() {
  const csv = await fs.readFile(fleetValidationPath, "utf8");
  const lines = csv.trim().split(/\r?\n/);
  const header = lines.shift().split(",");
  return lines.map((line) => {
    const values = line.split(",");
    const row = Object.fromEntries(header.map((key, index) => [key, values[index]]));
    return {
      acft_id: row.acft_id,
      rmse_dB: Number(row.rmse_dB),
      bias_dB: Number(row.bias_dB),
      role: row.role,
    };
  });
}

function workedExample(presentation, fleet) {
  const slide = presentation.slides.add(); slide.background.fill = WHITE;
  addTitle(slide, "One reference event shows how measurements become a bounded prediction", "05  /  worked example", 6);
  addText(slide, "A320-211  |  BPR 6.0  |  160 kt reference event  |  SEL + LAmax", { left: M, top: 170, width: 1000, height: 32 }, { fontSize: 23, bold: true, color: INK });
  const steps = [
    ["1  MEASURE / SPECIFY", "ANP truth curve\naircraft + BPR\ninput status"],
    ["2  CALCULATE SOURCES", "jet + fan\nwing/slat + flap\ngear spectra"],
    ["3  PROPAGATE", "spreading\nabsorption\nA-weighting"],
    ["4  PREDICT", "energetic sum\nSEL + LAmax\nNPD row"],
  ];
  const xs = [58, 348, 638, 928];
  for (let i = 0; i < steps.length; i += 1) {
    addBox(slide, `example-step-${i}`, { left: xs[i], top: 220, width: 240, height: 96 }, { fill: i === 0 || i === 3 ? BLUE_LIGHT : PANEL, line: i === 0 || i === 3 ? BLUE_LIGHT : PANEL, borderRadius: "rounded-xl" });
    addText(slide, `example-step-head-${i}`, steps[i][0], { left: xs[i] + 14, top: 240, width: 212, height: 22 }, { fontSize: 16, bold: true, color: i === 0 || i === 3 ? BLUE : MUTED, alignment: "center" });
    addText(slide, `example-step-body-${i}`, steps[i][1], { left: xs[i] + 14, top: 267, width: 212, height: 42 }, { fontSize: 17, color: INK, alignment: "center" });
    if (i < steps.length - 1) addText(slide, `example-arrow-${i}`, "→", { left: xs[i] + 248, top: 250, width: 40, height: 30 }, { fontSize: 28, bold: true, color: BLUE, alignment: "center" });
  }
  const calibration = fleet.find((row) => row.role === "calibration");
  const outOfSample = fleet.filter((row) => row.role === "out-of-sample");
  const ordered = [calibration, ...outOfSample.sort((a, b) => b.rmse_dB - a.rmse_dB)];
  const meanOos = outOfSample.reduce((sum, row) => sum + row.rmse_dB, 0) / outOfSample.length;
  const maxOos = Math.max(...outOfSample.map((row) => row.rmse_dB));
  addText(slide, `Observed residuals: calibration RMSE ${calibration.rmse_dB.toFixed(2)} dB  |  out-of-sample mean ${meanOos.toFixed(2)} dB  |  maximum ${maxOos.toFixed(2)} dB`, { left: 110, top: 326, width: 1060, height: 24 }, { fontSize: 17, bold: true, color: BLUE, alignment: "center" });
  addBox(slide, "rmse-frame", { left: 58, top: 360, width: 566, height: 286 }, { fill: PANEL, line: RULE, borderRadius: "rounded-xl" });
  addText(slide, "rmse-title", "Observed residual RMSE by aircraft (dB)", { left: 80, top: 374, width: 520, height: 24 }, { fontSize: 20, bold: true, color: INK });
  slide.charts.add("bar", {
    position: { left: 76, top: 406, width: 530, height: 224 },
    categories: ordered.map((row) => row.acft_id),
    series: [{ name: "RMSE", values: ordered.map((row) => row.rmse_dB), fill: BLUE, dataLabelOverrides: [{ idx: 0, fill: "#111111" }] }],
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 34 },
    hasLegend: false,
    xAxis: { min: 0, max: 5, majorUnit: 1, title: "dB", textStyle: { fontSize: 12, fill: MUTED }, majorGridlines: { style: "solid", fill: RULE, width: 1 } },
    yAxis: { textStyle: { fontSize: 11, fill: INK }, line: { style: "solid", fill: RULE, width: 1 } },
    dataLabels: { showValue: true, position: "outEnd", textStyle: { fontSize: 11, fill: INK } },
  });
  addBox(slide, "bias-frame", { left: 656, top: 360, width: 566, height: 286 }, { fill: BLUE_LIGHT, line: RULE, borderRadius: "rounded-xl" });
  addText(slide, "bias-title", "Signed bias: prediction − truth (dB)", { left: 678, top: 374, width: 520, height: 24 }, { fontSize: 20, bold: true, color: INK });
  slide.charts.add("bar", {
    position: { left: 674, top: 406, width: 530, height: 224 },
    categories: ordered.map((row) => row.acft_id),
    series: [{ name: "Bias", values: ordered.map((row) => row.bias_dB), fill: "#5F6670", dataLabelOverrides: [{ idx: 0, fill: "#111111" }] }],
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 34 },
    hasLegend: false,
    xAxis: { min: -4, max: 4, majorUnit: 2, title: "dB", textStyle: { fontSize: 12, fill: MUTED }, majorGridlines: { style: "solid", fill: RULE, width: 1 } },
    yAxis: { textStyle: { fontSize: 11, fill: INK }, line: { style: "solid", fill: RULE, width: 1 } },
    dataLabels: { showValue: true, position: "outEnd", textStyle: { fontSize: 11, fill: INK } },
  });
  addText(slide, "Observed residual summaries from physics_fleet_validation.csv; RMSE/bias are not confidence intervals or certification margins.", { left: 92, top: 652, width: 1096, height: 22 }, { fontSize: 16, bold: true, color: BLUE, alignment: "center" });
  addNotes(slide, "[Sources]\nWorked calculation chain: projects/pnmf/pnmf/physics.py (EngineState, JetSource, FanSource, AirframeSource, propagation, SEL/LAmax); projects/pnmf/docs/NPD_SYSTEM_DESIGN.md.\nReference event and calibration: projects/pnmf/pnmf/physics.py (Reference160KtFlightPath, PhysicsNPDModel.calibrate); projects/pnmf/pnmf/api.py.\nResidual charts: projects/pnmf/outputs/physics_fleet_validation.csv, generated by projects/pnmf/pnmf_cli.py (frozen constants, prediction minus ANP truth, A320-211 calibration plus 12 out-of-sample aircraft).\nInterpretation: RMSE and bias are observed residual summaries, not confidence intervals; projects/pnmf/pnmf/validation.py.");
}

function oneAircraftCalculation(presentation) {
  const slide = presentation.slides.add(); slide.background.fill = WHITE;
  addTitle(slide, "A320-211: one complete calculation from inputs to noise level", "06  /  one-aircraft calculation", 7);
  addText(slide, "Departure example  |  22,500 lb/engine  |  1,000 ft observer  |  160 kt reference event", { left: M, top: 160, width: 1120, height: 30 }, { fontSize: 22, bold: true, color: INK });

  addBox(slide, "case-panel", { left: 58, top: 198, width: 300, height: 422 }, { fill: PANEL, line: PANEL, borderRadius: "rounded-xl" });
  addText(slide, "case-title", "CASE + DERIVED STATE", { left: 82, top: 222, width: 250, height: 28 }, { fontSize: 21, bold: true, color: BLUE, alignment: "center" });
  addText(slide, "case-inputs", "Aircraft  A320-211 / CFM56-5A1\nBPR  6.0\nEngines  2\nFmax  25,000 lb/engine\nP  22,500 lb/engine\nV  82.31 m/s\nd  304.8 m\nAngles  69 (5° to 175°)", { left: 82, top: 266, width: 250, height: 156 }, { fontSize: 16, color: INK });
  addRule(slide, "case-rule", 82, 436, 250, RULE, 1);
  addText(slide, "case-derived", "v_j  282.08 m/s\nṁ  354.81 kg/s\nA_j  1.604 m²\nd_j  1.429 m\nM_tip  1.140\nBPF  1,859 Hz", { left: 82, top: 456, width: 250, height: 116 }, { fontSize: 16, color: INK });
  addText(slide, "case-status", "Engine-deck streams unavailable; fallback source paths and estimated geometry are visible.", { left: 82, top: 582, width: 250, height: 26 }, { fontSize: 14.5, color: MUTED });

  addBox(slide, "formula-panel", { left: 380, top: 198, width: 520, height: 422 }, { fill: WHITE, line: RULE, borderRadius: "rounded-xl" });
  addText(slide, "formula-title", "FORMULATION  /  LaTeX SOURCE", { left: 406, top: 222, width: 468, height: 28 }, { fontSize: 21, bold: true, color: BLUE });
  const latex = String.raw`F = P_{eng}(4.44822),
v_j = \frac{700}{(1+BPR)^{0.44}}\sqrt{\frac{F}{F_{max}}},
\dot m = \frac{F}{v_j},\quad A_j = \frac{\dot m}{\rho_j v_j},
d_j = \sqrt{\frac{4A_j}{\pi}},\quad
f_{peak} = f_{scale}\,0.25\frac{v_j}{d_j}

L_{i}(f,r_k) = L_{i,1m}(f) - 20\log_{10}(r_k/1m) - \alpha(f)r_k
r_k = \frac{d}{\sin\theta_k},\quad t_k = \frac{-d\cot\theta_k}{V}

L_A(t_k) = 10\log_{10}\sum_i 10^{L_{A,k}^{(i)}/10}
L_{A,max} = \max_k L_A(t_k),\quad
SEL = 10\log_{10}\left[\frac{1}{1s}\int 10^{L_A(t)/10}dt\right]`;
  addText(slide, "formula-text", latex, { left: 406, top: 264, width: 468, height: 292 }, { fontSize: 15.5, typeface: "Courier New", color: INK, autoFit: "shrinkText" });
  addText(slide, "formula-note", "Source spectra are A-weighted after propagation, then summed energetically. SEL integrates the 69-point receiver history; LAmax takes its peak.", { left: 406, top: 568, width: 468, height: 36 }, { fontSize: 14.5, color: MUTED });

  addBox(slide, "result-panel", { left: 922, top: 198, width: 300, height: 422 }, { fill: BLUE_LIGHT, line: BLUE_LIGHT, borderRadius: "rounded-xl" });
  addText(slide, "result-title", "RESULT VS DATA", { left: 946, top: 222, width: 252, height: 28 }, { fontSize: 21, bold: true, color: BLUE, alignment: "center" });
  const rx = [936, 1002, 1057, 1112]; const rw = [66, 55, 55, 86];
  ["Metric", "ANP", "ET", "Physics"].forEach((h, i) => addCell(slide, `case-head-${i}`, h, rx[i], 266, rw[i], 38, { fill: INK, line: INK, color: WHITE, bold: true, fontSize: 13, pad: 5, topPad: 6 }));
  const resultRows = [["SEL", "96.40", "96.40", "97.27"], ["LAmax", "88.90", "88.90", "87.27"]];
  for (let r = 0; r < resultRows.length; r += 1) for (let c = 0; c < 4; c += 1) addCell(slide, `case-${r}-${c}`, resultRows[r][c], rx[c], 304 + r * 38, rw[c], 38, { fill: r % 2 === 0 ? WHITE : PANEL, line: RULE, fontSize: 14, bold: c === 0, pad: 5, topPad: 6 });
  addText(slide, "result-error", "Physics − ANP\nSEL  +0.87 dB\nLAmax  −1.63 dB", { left: 946, top: 398, width: 252, height: 72 }, { fontSize: 18, bold: true, color: INK, alignment: "center" });
  addRule(slide, "result-rule", 946, 490, 252, RULE, 1);
  addText(slide, "result-components", "Physics component SEL\njet  94.40 dB\nfan  94.05 dB\nairframe  76.03 dB\ntotal  97.27 dB", { left: 946, top: 508, width: 252, height: 98 }, { fontSize: 15.5, color: INK, alignment: "center" });
  addText(slide, "case-foot", "Error = prediction − ANP truth. ANP is the real-aircraft benchmark; ET is in-sample for this A320-211 row, not held-out evidence.", { left: 82, top: 642, width: 1116, height: 24 }, { fontSize: 16, bold: true, color: BLUE, alignment: "center" });
  addNotes(slide, "[Sources]\nNumerical case: projects/pnmf/pnmf_cli.py (A320-211 / BPR 6.0 fleet context); projects/pnmf/pnmf/physics.py (PhysicsDesign, EngineState, Reference160KtFlightPath, EventDiagnostics).\nFormulation: projects/pnmf/docs/NPD_SYSTEM_DESIGN.md, section 3.3; projects/pnmf/pnmf/physics.py (JetSource, FanSource, AirframeSource, propagation, SEL/LAmax).\nANP benchmark: CFM565 A320-211 rows in the local ANP truth database (SEL/LAmax, departure, 22,500 lb, 1,000 ft).\nET comparison: projects/pnmf/pnmf/api.py (NoisePredictor) and projects/pnmf/pnmf/models.py.\nThe displayed values are a traceable reference calculation, not a measurement-validity or certification claim.");
}

function latexReference(presentation) {
  const slide = presentation.slides.add(); slide.background.fill = WHITE;
  addTitle(slide, "LaTeX formulation: source spectra become receiver metrics", "07  /  formula reference", 8);
  addText(slide, "Copy these blocks into PowerPoint's equation editor and keep the comparison definition unchanged.", { left: M, top: 166, width: 980, height: 32 }, { fontSize: 22, color: MUTED });
  const panels = [
    { id: "latex-source", left: 58, width: 366, fill: PANEL, title: "1  /  SOURCE LEVEL" },
    { id: "latex-prop", left: 457, width: 366, fill: WHITE, title: "2  /  PROPAGATE + SUM" },
    { id: "latex-compare", left: 856, width: 366, fill: BLUE_LIGHT, title: "3  /  COMPARE TO DATA" },
  ];
  for (const panel of panels) {
    addBox(slide, panel.id, { left: panel.left, top: 210, width: panel.width, height: 358 }, { fill: panel.fill, line: panel.fill === WHITE ? RULE : panel.fill, borderRadius: "rounded-xl" });
    addText(slide, `${panel.id}-title`, panel.title, { left: panel.left + 24, top: 234, width: panel.width - 48, height: 26 }, { fontSize: 20, bold: true, color: BLUE, alignment: "center" });
  }
  const sourceLatex = String.raw`I_{jet}\propto\rho_j^2 A_j v_j^8
L_{jet,1m}=C_j+80\log_{10}(v_j/c_0)
\quad+10\log_{10}(A_j)+D_j(\theta)+H_j(f)

L_{fan,1m}=C_f+10\log_{10}(\dot m)
\quad+40\log_{10}(M_{tip})+D_f(\theta)+H_f(f)

L_{air,1m}=C_a+p\log_{10}(V/c_0)
\quad+G_a+D_a(\theta)+H_a(f),\quad p\in\{50,60\}`;
  const propLatex = String.raw`r_k=\frac{d}{\sin\theta_k},\quad
t_k=\frac{-d\cot\theta_k}{V}

L_i(f,r_k)=L_{i,1m}(f)
-20\log_{10}(r_k/1m)-\alpha(f)r_k

L_{A,k}^{(i)}=10\log_{10}\sum_f
10^{[L_i(f,r_k)+A(f)]/10}

L_A(t_k)=10\log_{10}\sum_i
10^{L_{A,k}^{(i)}/10}`;
  const compareLatex = String.raw`L_{A,max}=\max_k L_A(t_k)

SEL=10\log_{10}\left[\frac{1}{1s}
\int 10^{L_A(t)/10}dt\right]

e_{phys}=y_{phys}-y_{ANP}
e_{ET}=y_{ET}-y_{ANP}

RMSE=\sqrt{\frac{1}{n}\sum e_i^2}
\quad bias=\frac{1}{n}\sum e_i`;
  addText(slide, "latex-source-text", sourceLatex, { left: 82, top: 280, width: 318, height: 252 }, { fontSize: 15.5, typeface: "Courier New", color: INK, autoFit: "shrinkText" });
  addText(slide, "latex-prop-text", propLatex, { left: 481, top: 280, width: 318, height: 252 }, { fontSize: 15.5, typeface: "Courier New", color: INK, autoFit: "shrinkText" });
  addText(slide, "latex-compare-text", compareLatex, { left: 880, top: 280, width: 318, height: 252 }, { fontSize: 15.5, typeface: "Courier New", color: INK, autoFit: "shrinkText" });
  addText(slide, "latex-foot", "A320-211 at 1,000 ft: ANP = 96.40 / 88.90 dB, ET = 96.40 / 88.90 dB, physics = 97.27 / 87.27 dB (SEL / LAmax).", { left: 88, top: 606, width: 1104, height: 28 }, { fontSize: 18, bold: true, color: BLUE, alignment: "center" });
  addNotes(slide, "[Sources]\nSource laws and symbols: projects/pnmf/docs/NPD_SYSTEM_DESIGN.md, section 3.3; projects/pnmf/pnmf/physics.py (JetSource, FanSource, AirframeSource).\nPropagation and metrics: projects/pnmf/pnmf/physics.py (propagate, EventDiagnostics, SEL/LAmax).\nComparison definitions: projects/pnmf/pnmf/validation.py (prediction minus truth, RMSE, bias); projects/pnmf/pnmf/api.py (independent ET and physics routes).\nThe LaTeX is provided as editable source text for manual PowerPoint equation conversion.");
}

function softwareEvidence(presentation) {
  const slide = presentation.slides.add(); slide.background.fill = WHITE;
  addTitle(slide, "Tests verify behavior; they do not validate reality", "08  /  software evidence", 9);
  addText(slide, "The existing suite is valuable evidence, but each test has a bounded claim.", { left: M, top: 174, width: 920, height: 40 }, { fontSize: 24, color: MUTED });
  const xs = [58, 280, 610, 960]; const ws = [222, 330, 350, 262];
  ["Test family", "What it supports", "What it does not prove", "Status"].forEach((h, c) => addCell(slide, `s-head-${c}`, h, xs[c], 224, ws[c], 46, { fill: INK, line: INK, color: WHITE, bold: true, fontSize: 16 }));
  const rows = [
    ["Units and scaling", "A-weighting, absorption, jet Vⱼ⁸, gear V⁶, BPR sensitivity", "Correctness of the chosen physical law for a new engine", "SUPPORTED"],
    ["Source gates", "Detailed jet/fan/core paths and six airframe outputs appear only when inputs permit", "That the available inputs describe the real aircraft", "SUPPORTED"],
    ["Calibration behavior", "Four anchors and spectral factor affect the documented reference fit", "Independent component accuracy or transferability", "CONDITIONAL"],
    ["Metric and provenance", "SEL/LAmax scope, unavailable states, and separate truth/prediction tables", "A measured uncertainty interval or certification claim", "SUPPORTED"],
  ];
  for (let r = 0; r < rows.length; r += 1) for (let c = 0; c < 4; c += 1) addCell(slide, `s-${r}-${c}`, rows[r][c], xs[c], 270 + r * 76, ws[c], 76, { fill: r % 2 === 0 ? WHITE : PANEL, line: RULE, fontSize: 16, bold: c === 0 || c === 3, color: c === 3 && rows[r][3] === "CONDITIONAL" ? BLUE : INK });
  addBox(slide, "s-callout", { left: 140, top: 602, width: 1000, height: 46 }, { fill: BLUE_LIGHT, line: BLUE_LIGHT, borderRadius: "rounded-lg" });
  addText(slide, "s-callout-text", "Software verification closes implementation questions; measurement validation closes physical-accuracy questions.", { left: 166, top: 615, width: 948, height: 22 }, { fontSize: 18, bold: true, color: INK, alignment: "center" });
  addNotes(slide, "[Sources]\nTests: projects/pnmf/tests/test_physics.py.\nImplementation: projects/pnmf/pnmf/physics.py; projects/pnmf/pnmf/api.py.\nValidation distinction: NASA Dahl, https://ntrs.nasa.gov/citations/20080032565; ECAC Doc 29, 5th Edition, Volume 1, official applications guide.");
}

function componentAudit(presentation) {
  const slide = presentation.slides.add(); slide.background.fill = WHITE;
  addTitle(slide, "Component mechanisms remain the weakest evidence layer", "09  /  component validity", 10);
  addText(slide, "Implemented mechanisms are inspectable; independent component measurement evidence is the missing link.", { left: M, top: 174, width: 1040, height: 40 }, { fontSize: 24, color: MUTED });
  const xs = [58, 220, 770, 1032]; const ws = [162, 550, 262, 190];
  ["Component", "Implemented basis", "Missing evidence", "Status"].forEach((h, c) => addCell(slide, `c-head-${c}`, h, xs[c], 224, ws[c], 44, { fill: INK, line: INK, color: WHITE, bold: true, fontSize: 16 }));
  const rows = [
    ["Jet", "Stone-style mixing; Vⱼ⁸ scaling; multi-stream gate", "Measured spectra/directivity by state", "CONDITIONAL"],
    ["Fan", "Heidmann scaling; BPF; inlet/discharge lobes", "Engine-deck and flight component data", "CONDITIONAL"],
    ["Core", "Optional branch; unavailable without complete core state", "Any component evidence in current workflow", "NOT DEMONSTRATED"],
    ["Wing / slat", "Fink-style 50 log₁₀(V/c₀) + geometry proxies", "Modern high-lift component measurements", "CONDITIONAL"],
    ["Flap edges", "Main and side-edge spectra separated", "Interaction and configuration evidence", "CONDITIONAL"],
    ["Main gear", "Fink-style 60 log₁₀(V/c₀) + wheel/diameter terms", "Gear and flap-wake interaction data", "CONDITIONAL"],
    ["Nose gear", "Separate wheel/strut source", "Component-resolved measurements", "CONDITIONAL"],
    ["System sum", "Energetic combination + propagation + metrics", "Held-out event and aircraft-family tests", "NOT DEMONSTRATED"],
  ];
  for (let r = 0; r < rows.length; r += 1) for (let c = 0; c < 4; c += 1) addCell(slide, `c-${r}-${c}`, rows[r][c], xs[c], 268 + r * 44, ws[c], 44, { fill: r % 2 === 0 ? WHITE : PANEL, line: RULE, fontSize: c === 3 ? 14.5 : 16, bold: c === 0 || c === 3, color: c === 3 && rows[r][3] === "CONDITIONAL" ? BLUE : INK });
  addText(slide, "Evidence upgrade order: component spectra/directivity  ->  propagated event  ->  total SEL/LAmax  ->  NPD transfer.", { left: 105, top: 640, width: 1070, height: 24 }, { fontSize: 18, bold: true, color: BLUE, alignment: "center" });
  addNotes(slide, "[Sources]\nComponent implementation: projects/pnmf/pnmf/physics.py; projects/pnmf/docs/NPD_SYSTEM_DESIGN.md.\nInput/preset limitations: projects/pnmf/docs/PHYSICS_PRESETS.md.\nEvidence ladder: projects/pnmf/docs/PHYSICAL_MODEL_IMPROVEMENT_RESEARCH.md; NASA airframe measurements https://ntrs.nasa.gov/citations/20220006685; NASA fan flight effects https://ntrs.nasa.gov/citations/20220006704.");
}

function calibrationVsValidation(presentation) {
  const slide = presentation.slides.add(); slide.background.fill = WHITE;
  addTitle(slide, "Calibration anchors the system, not the components", "10  /  calibration boundary", 11);
  addBox(slide, "cal-anchor", { left: 72, top: 202, width: 432, height: 290 }, { fill: BLUE_LIGHT, line: BLUE_LIGHT, borderRadius: "rounded-xl" });
  addText(slide, "cal-title", "CALIBRATION EVIDENCE", { left: 104, top: 234, width: 330, height: 28 }, { fontSize: 18, bold: true, color: BLUE, alignment: "center" });
  addText(slide, "cal-main", "A320-211\nBPR 6.0\nANP SEL + LAmax", { left: 104, top: 282, width: 330, height: 108 }, { fontSize: 30, bold: true, color: INK, alignment: "center" });
  addText(slide, "cal-detail", "Four additive anchors + one spectral-placement factor are fitted, then frozen.", { left: 104, top: 422, width: 330, height: 42 }, { fontSize: 17, color: MUTED, alignment: "center" });
  addBox(slide, "validation-box", { left: 594, top: 202, width: 614, height: 290 }, { fill: PANEL, line: PANEL, borderRadius: "rounded-xl" });
  addText(slide, "val-title", "VALIDATION STILL NEEDED", { left: 630, top: 234, width: 500, height: 28 }, { fontSize: 18, bold: true, color: INK, alignment: "center" });
  addBulletList(slide, "val-list", ["independent component spectra and directivity", "held-out event states and aircraft families", "measurement plus model-form uncertainty", "transfer limits tied to real input provenance"], { left: 650, top: 286, width: 510, height: 150 }, { fontSize: 20, color: INK });
  addText(slide, "A fit can make the reference curve agree while leaving component mechanisms or new configurations untested.", { left: 130, top: 556, width: 1020, height: 44 }, { fontSize: 22, bold: true, color: BLUE, alignment: "center" });
  addNotes(slide, "[Sources]\nCalibration code and contract: projects/pnmf/pnmf/physics.py (PhysicsNPDModel.calibrate); projects/pnmf/pnmf/api.py.\nReference data context: projects/pnmf/docs/NPD_SYSTEM_DESIGN.md.\nCalibration-versus-validation method: NASA Dahl, https://ntrs.nasa.gov/citations/20080032565; NASA uncertainty assessment https://ntrs.nasa.gov/citations/20190000984.");
}

function applicability(presentation) {
  const slide = presentation.slides.add(); slide.background.fill = WHITE;
  addTitle(slide, "Applicability shrinks when state or mechanism is missing", "11  /  transfer limits", 12);
  addText(slide, "The output remains useful only inside a documented state envelope.", { left: M, top: 174, width: 860, height: 40 }, { fontSize: 24, color: MUTED });
  const xs = [58, 250, 630, 1015]; const ws = [192, 380, 385, 207];
  ["Input / path", "Current practice", "Validity consequence", "Report as"].forEach((h, c) => addCell(slide, `a-head-${c}`, h, xs[c], 224, ws[c], 44, { fill: INK, line: INK, color: WHITE, bold: true, fontSize: 16 }));
  const rows = [
    ["Engine deck", "Detailed state is optional; named fallback remains", "Fallback may dominate the source spectrum", "ESTIMATED"],
    ["Geometry", "Preset span/BPR plus estimated high-lift and strut fields", "Mechanism fidelity varies by aircraft", "ESTIMATED"],
    ["Trajectory", "160 kt straight-level reference event", "No segmented or operational-profile claim", "CONDITIONAL"],
    ["Propagation", "Free-field spreading + molecular absorption", "Installation, shielding, ground, terrain and lateral effects excluded", "EXCLUDED"],
    ["Metric", "SEL and LAmax", "EPNL/PNLTM tone corrections are outside physics route", "BOUNDED"],
  ];
  for (let r = 0; r < rows.length; r += 1) for (let c = 0; c < 4; c += 1) addCell(slide, `a-${r}-${c}`, rows[r][c], xs[c], 268 + r * 65, ws[c], 65, { fill: r % 2 === 0 ? WHITE : PANEL, line: RULE, fontSize: c === 3 ? 15 : 16, bold: c === 0 || c === 3, color: c === 3 && rows[r][3] === "CONDITIONAL" ? BLUE : INK });
  addBox(slide, "a-bottom", { left: 86, top: 604, width: 1108, height: 40 }, { fill: BLUE_LIGHT, line: BLUE_LIGHT, borderRadius: "rounded-lg" });
  addText(slide, "a-bottom-text", "Explicit exclusions: installation/shielding, nacelle treatment, ground reflection, lateral attenuation, terrain, and non-uniform atmosphere.", { left: 108, top: 615, width: 1064, height: 20 }, { fontSize: 17, bold: true, color: INK, alignment: "center" });
  addNotes(slide, "[Sources]\nApplicability and exclusions: projects/pnmf/pnmf/physics.py (EventDiagnostics.excluded_effects); projects/pnmf/docs/NPD_SYSTEM_DESIGN.md; projects/pnmf/docs/PHYSICS_PRESETS.md.\nMetric scope: projects/pnmf/pnmf/api.py.\nMethod rationale: ECAC Doc 29, 5th Edition, Volume 1 official applications guide.");
}

function validationCampaign(presentation) {
  const slide = presentation.slides.add(); slide.background.fill = WHITE;
  addTitle(slide, "Validation should proceed from components to systems", "12  /  improvement campaign", 13);
  addText(slide, "Do not jump directly from one calibrated reference curve to a universal accuracy claim.", { left: M, top: 174, width: 950, height: 40 }, { fontSize: 24, color: MUTED });
  const labels = [
    ["1  COMPONENT", "Spectra + directivity", "Jet, fan, airframe\nmeasured by state"],
    ["2  SYSTEM EVENT", "Held-out SEL/LAmax", "Propagated history\nand total metric"],
    ["3  TRANSFER", "Aircraft/configuration", "New family, state,\nor installation bound"],
  ];
  const xs = [80, 470, 860]; const nodes = [];
  for (let i = 0; i < labels.length; i += 1) {
    const box = addBox(slide, `vc-box-${i}`, { left: xs[i], top: 246, width: 300, height: 180 }, { fill: i === 0 ? BLUE_LIGHT : PANEL, line: i === 0 ? BLUE_LIGHT : PANEL, borderRadius: "rounded-xl" });
    nodes.push(box);
    addText(slide, `vc-head-${i}`, labels[i][0], { left: xs[i] + 24, top: 274, width: 252, height: 24 }, { fontSize: 17, bold: true, color: i === 0 ? BLUE : MUTED, alignment: "center" });
    addText(slide, `vc-main-${i}`, labels[i][1], { left: xs[i] + 24, top: 316, width: 252, height: 34 }, { fontSize: 24, bold: true, color: INK, alignment: "center" });
    addText(slide, `vc-detail-${i}`, labels[i][2], { left: xs[i] + 24, top: 364, width: 252, height: 44 }, { fontSize: 18, color: MUTED, alignment: "center" });
  }
  for (let i = 0; i < nodes.length - 1; i += 1) slide.shapes.connect(nodes[i], nodes[i + 1], { kind: "straight", fromSide: "right", toSide: "left", line: { style: "solid", fill: BLUE, width: 2 }, head: { type: "arrow", width: "sm", length: "sm" } });
  addBox(slide, "record-box", { left: 94, top: 498, width: 1092, height: 90 }, { fill: WHITE, line: RULE, borderRadius: "rounded-lg" });
  addText(slide, "record-title", "Validation record  |  dataset/version/hash  |  aircraft/engine state  |  geometry/configuration  |  observer  |  corrections + uncertainty  |  residual  |  calibration/holdout tag", { left: 120, top: 520, width: 1040, height: 48 }, { fontSize: 18, bold: true, color: INK, alignment: "center" });
  addText(slide, "The ledger makes evidence portable, reviewable, and separable from training data.", { left: 180, top: 624, width: 920, height: 26 }, { fontSize: 20, bold: true, color: BLUE, alignment: "center" });
  addNotes(slide, "[Sources]\nValidation campaign design: projects/pnmf/docs/PHYSICAL_MODEL_IMPROVEMENT_RESEARCH.md.\nData separation and provenance: projects/pnmf/docs/ADVISOR_PRESENTATION_TEXT.md; projects/pnmf/docs/NPD_SYSTEM_DESIGN.md.\nPrimary methodology: NASA Dahl https://ntrs.nasa.gov/citations/20080032565; NASA airframe component measurements https://ntrs.nasa.gov/citations/20220006685.");
}

function evidenceGates(presentation) {
  const slide = presentation.slides.add(); slide.background.fill = WHITE;
  addTitle(slide, "Stronger claims require explicit evidence gates", "13  /  acceptance bar", 14);
  addText(slide, "The gate is about evidence quality and reproducibility, not a target accuracy number.", { left: M, top: 174, width: 1000, height: 40 }, { fontSize: 24, color: MUTED });
  const gates = [
    "Predeclare metrics, tolerances, and comparison protocol",
    "Compare component spectra/directivity against measurements",
    "Validate held-out system-event SEL/LAmax",
    "Separate measurement, input, and model-form uncertainty",
    "Load a versioned calibration artifact without silent refit",
    "Tie applicability labels to actual evidence coverage",
    "Keep excluded physics and unquantified uncertainty visible",
  ];
  for (let i = 0; i < gates.length; i += 1) {
    const y = 228 + i * 48;
    addRule(slide, `gate-bar-${i}`, 78, y + 2, 6, i < 3 ? BLUE : RULE, 34);
    addText(slide, `gate-num-${i}`, String(i + 1).padStart(2, "0"), { left: 100, top: y + 5, width: 36, height: 22 }, { fontSize: 17, bold: true, color: MUTED });
    addText(slide, `gate-text-${i}`, gates[i], { left: 150, top: y + 3, width: 690, height: 28 }, { fontSize: 18, bold: i < 3, color: INK });
  }
  addBox(slide, "status-box", { left: 910, top: 228, width: 290, height: 344 }, { fill: PANEL, line: PANEL, borderRadius: "rounded-xl" });
  addText(slide, "status-title", "Claim upgrade", { left: 946, top: 258, width: 218, height: 30 }, { fontSize: 25, bold: true, color: INK, alignment: "center" });
  addText(slide, "status-flow", "NOT DEMONSTRATED\n\n+ component evidence\n\nCONDITIONAL\n\n+ held-out transfer\n\nSUPPORTED FOR A BOUND", { left: 946, top: 316, width: 218, height: 204 }, { fontSize: 19, bold: true, color: INK, alignment: "center" });
  addText(slide, "No invented intervals. No universal claim outside the evidence range.", { left: 120, top: 590, width: 1040, height: 28 }, { fontSize: 20, bold: true, color: BLUE, alignment: "center" });
  addNotes(slide, "[Sources]\nAcceptance logic: projects/pnmf/docs/PHYSICAL_MODEL_IMPROVEMENT_RESEARCH.md.\nAuditability, reliability, consistency, accuracy, and input-quality principles: ECAC Doc 29, 5th Edition, Volume 1, https://www.ecac-ceac.org/images/documents/ECAC-CEAC-DOC_29_5th_Edition-REPORT_ON_STANDARD_METHOD_OF_COMPUTING_NOISE_CONTOURS_AROUND_CIVIL_AIRPORTS-Volume_1-APPLICATIONS_GUIDE.pdf.\nUncertainty wording: projects/pnmf/pnmf/physics.py (uncertainty_note).");
}

function conclusion(presentation) {
  const slide = presentation.slides.add(); slide.background.fill = WHITE;
  addTitle(slide, "Current verdict: bounded validity, not predictive proof", "14  /  conclusion", 15);
  addText(slide, "PNMF's physical route is ready for disciplined conceptual screening.", { left: M, top: 192, width: 760, height: 62 }, { fontSize: 34, bold: true, color: INK });
  addText(slide, "Its strongest claims today are physical coherence, software auditability, and explicit scope. Its weakest claims are component accuracy, cross-aircraft transfer, and quantitative uncertainty.", { left: M, top: 292, width: 710, height: 106 }, { fontSize: 23, color: MUTED });
  addBox(slide, "now-box", { left: 828, top: 202, width: 360, height: 156 }, { fill: BLUE_LIGHT, line: BLUE_LIGHT, borderRadius: "rounded-xl" });
  addText(slide, "now-title", "SUPPORTED NOW", { left: 860, top: 232, width: 296, height: 28 }, { fontSize: 18, bold: true, color: BLUE, alignment: "center" });
  addText(slide, "now-text", "coherence  |  provenance\nimplementation checks  |  bounded metrics", { left: 860, top: 278, width: 296, height: 50 }, { fontSize: 20, bold: true, color: INK, alignment: "center" });
  addBox(slide, "next-box", { left: 828, top: 388, width: 360, height: 156 }, { fill: PANEL, line: PANEL, borderRadius: "rounded-xl" });
  addText(slide, "next-title", "EARNED NEXT", { left: 860, top: 418, width: 296, height: 28 }, { fontSize: 18, bold: true, color: INK, alignment: "center" });
  addText(slide, "next-text", "component evidence  |  held-out events\ntransfer bounds  |  calibrated uncertainty", { left: 860, top: 464, width: 296, height: 50 }, { fontSize: 20, bold: true, color: INK, alignment: "center" });
  addText(slide, "Future physics work starts after the evidence gate, not before it.", { left: 120, top: 604, width: 1040, height: 30 }, { fontSize: 22, bold: true, color: BLUE, alignment: "center" });
  addNotes(slide, "[Sources]\nCurrent scope and boundary: projects/pnmf/docs/ADVISOR_PRESENTATION_TEXT.md; projects/pnmf/docs/NPD_SYSTEM_DESIGN.md.\nFuture priorities: projects/pnmf/docs/PHYSICAL_MODEL_IMPROVEMENT_RESEARCH.md.\nNo numerical accuracy or certification claim is made.");
}

async function writeBlob(path, blob) {
  await fs.mkdir(path.substring(0, path.lastIndexOf("/")), { recursive: true });
  await fs.writeFile(path, new Uint8Array(await blob.arrayBuffer()));
}

async function main() {
  const presentation = Presentation.create({ slideSize: { width: W, height: H } });
  const fleet = await loadFleetValidation();
  cover(presentation); verdict(presentation); auditMethod(presentation); propulsionEquations(presentation);
  eventEquations(presentation); workedExample(presentation, fleet); oneAircraftCalculation(presentation); latexReference(presentation); softwareEvidence(presentation); componentAudit(presentation);
  calibrationVsValidation(presentation); applicability(presentation); validationCampaign(presentation);
  evidenceGates(presentation); conclusion(presentation);
  await fs.mkdir(workOut, { recursive: true });
  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    await writeBlob(`${workOut}/${stem}.png`, await presentation.export({ slide, format: "png", scale: 1 }));
    await fs.writeFile(`${workOut}/${stem}.layout.json`, await (await slide.export({ format: "layout" })).text());
  }
  await writeBlob(`${workOut}/deck-montage.webp`, await presentation.export({ format: "webp", montage: true, scale: 1 }));
  const pptx = await PresentationFile.exportPptx(presentation); await pptx.save(finalPath);
  await fs.writeFile(`${workOut}/deck-inspect.ndjson`, (await presentation.inspect({ kind: "slide,textbox,shape,notes", maxChars: 60000 })).ndjson);
  console.log(`Created ${finalPath}`); console.log(`Slides: ${presentation.slides.items.length}`);
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
