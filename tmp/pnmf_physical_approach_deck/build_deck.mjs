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

const finalPath = "C:/Users/efeko/adp/framework/pnmf_project_2/pnmf_project/projects/pnmf/output/PNMF_Physical_Approach_Stabilization_Roadmap.pptx";
const workOut = "C:/Users/efeko/adp/framework/pnmf_project_2/pnmf_project/tmp/pnmf_physical_approach_deck/rendered";

let autoTextId = 0;

function addText(slide, name, value, position, options = {}) {
  if (typeof value !== "string") {
    options = position;
    position = value;
    value = name;
    name = `"auto-text-${autoTextId++}"`;
  }
  const shape = slide.shapes.add({
    geometry: "textbox",
    name,
    position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
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
  const config = {
    geometry: options.geometry ?? "roundRect",
    name,
    position,
    fill: options.fill ?? WHITE,
    line: {
      style: "solid",
      fill: options.line ?? RULE,
      width: options.lineWidth ?? 1,
    },
  };
  if (config.geometry !== "rect") config.borderRadius = options.borderRadius ?? "rounded-lg";
  return slide.shapes.add(config);
}

function addRule(slide, name, left, top, width, color = RULE, height = 2) {
  return slide.shapes.add({
    geometry: "rect",
    name,
    position: { left, top, width, height },
    fill: color,
    line: { style: "solid", fill: color, width: 0 },
  });
}

function addTitle(slide, title, kicker, page) {
  addText(slide, `kicker-${page}`, kicker.toUpperCase(),
    { left: M, top: 34, width: 560, height: 24 },
    { fontSize: 15, bold: true, color: BLUE });
  addText(slide, `title-${page}`, title,
    { left: M, top: 65, width: 1120, height: 62 },
    { fontSize: 38, bold: true, color: INK, autoFit: "shrinkText" });
  addRule(slide, `rule-${page}`, M, 137, 1164, RULE, 1);
  addText(slide, `footer-${page}`, `PNMF  |  physical approach stabilization  |  ${page}`,
    { left: M, top: 680, width: 700, height: 18 },
    { fontSize: 12, color: MUTED });
}

function addNotes(slide, text) {
  slide.speakerNotes.textFrame.setText(text);
  slide.speakerNotes.setVisible(true);
}

function addBulletList(slide, name, items, position, options = {}) {
  const text = items.map((item) => `| ${item}`).join("\n");
  return addText(slide, name, text, position, {
    fontSize: options.fontSize ?? 20,
    color: options.color ?? INK,
    bold: options.bold ?? false,
    ...options,
  });
}

function addTag(slide, name, label, left, top, width, fill = PANEL, color = INK) {
  const box = addBox(slide, name, { left, top, width, height: 34 }, {
    fill,
    line: fill,
    borderRadius: "rounded-md",
  });
  addText(slide, `${name}-text`, label, { left: left + 10, top: top + 7, width: width - 20, height: 20 }, {
    fontSize: 15, bold: true, color, alignment: "center", verticalAlignment: "middle",
  });
  return box;
}

function addStatusRow(slide, index, label, body, tone = "neutral") {
  const y = 218 + index * 94;
  const accent = tone === "blue" ? BLUE : tone === "gray" ? RULE : INK;
  addRule(slide, `status-accent-${index}`, 632, y + 5, 6, accent, 64);
  addText(slide, `status-label-${index}`, label,
    { left: 660, top: y, width: 235, height: 30 },
    { fontSize: 23, bold: true, color: INK });
  addText(slide, `status-body-${index}`, body,
    { left: 660, top: y + 33, width: 540, height: 42 },
    { fontSize: 17, color: MUTED });
}

function addCell(slide, name, text, left, top, width, height, options = {}) {
  addBox(slide, `${name}-box`, { left, top, width, height }, {
    geometry: "rect",
    fill: options.fill ?? WHITE,
    line: options.line ?? RULE,
    lineWidth: options.lineWidth ?? 1,
    borderRadius: "square",
  });
  return addText(slide, `${name}-text`, text,
    { left: left + (options.pad ?? 12), top: top + (options.topPad ?? 9), width: width - 2 * (options.pad ?? 12), height: height - 2 * (options.topPad ?? 9) },
    { fontSize: options.fontSize ?? 16, bold: options.bold ?? false, color: options.color ?? INK, verticalAlignment: "middle" });
}

function slide01(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = WHITE;
  addRule(slide, "cover-blue-bar", 58, 58, 12, BLUE, 588);
  addText(slide, "cover-kicker", "PNMF  /  CONCEPTUAL NOISE MODELING", { left: 104, top: 88, width: 700, height: 28 }, { fontSize: 18, bold: true, color: BLUE });
  addText(slide, "cover-title", "Stabilizing PNMF's\nPhysical Noise Approach", { left: 104, top: 174, width: 760, height: 190 }, { fontSize: 55, bold: true, color: INK });
  addText(slide, "cover-subtitle", "Current setup, evidence limits, and an eight-week control plan.", { left: 106, top: 404, width: 730, height: 62 }, { fontSize: 25, color: MUTED });
  addRule(slide, "cover-rule", 106, 514, 520, RULE, 1);
  addText(slide, "cover-date", "Advisor review  |  03 August 2026", { left: 106, top: 536, width: 520, height: 26 }, { fontSize: 17, color: MUTED });
  addBox(slide, "cover-boundary", { left: 888, top: 224, width: 286, height: 214 }, { fill: PANEL, line: PANEL, borderRadius: "rounded-xl" });
  addText(slide, "cover-boundary-title", "Stability first", { left: 920, top: 260, width: 220, height: 38 }, { fontSize: 28, bold: true, color: INK });
  addText(slide, "cover-boundary-body", "Controlled, reproducible, bounded, and reviewable.\n\nNot certification-ready.\nNot a promise of better accuracy.", { left: 920, top: 310, width: 220, height: 100 }, { fontSize: 18, color: MUTED });
  addNotes(slide, "[Sources]\nScope and wording: projects/pnmf/README.md; projects/pnmf/docs/PROJECT_UNDERSTANDING.md.\nNo external assets used.");
}

function slide02(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = WHITE;
  addTitle(slide, "The next two months are about control, not novelty", "01  /  priority", 2);
  addText(slide, "PNMF already has a useful physical route.\nThe credibility work is to make its limits and repeatability impossible to miss.", { left: M, top: 204, width: 760, height: 150 }, { fontSize: 42, bold: true, color: INK });
  addBox(slide, "priority-rail", { left: 900, top: 205, width: 322, height: 256 }, { fill: BLUE_LIGHT, line: BLUE_LIGHT, borderRadius: "rounded-xl" });
  addText(slide, "priority-rail-label", "Decision rule", { left: 932, top: 238, width: 240, height: 32 }, { fontSize: 20, bold: true, color: BLUE });
  addText(slide, "priority-rail-body", "Freeze the baseline.\nMake applicability explicit.\nValidate evidence in layers.\nOnly then add mechanisms.", { left: 932, top: 290, width: 246, height: 145 }, { fontSize: 25, bold: true, color: INK });
  addText(slide, "This is a maturity and evidence program, not a new-results program.", { left: M, top: 498, width: 780, height: 42 }, { fontSize: 22, color: MUTED });
  addNotes(slide, "[Sources]\nPriority framing: projects/pnmf/docs/PHYSICAL_MODEL_IMPROVEMENT_RESEARCH.md.\nResearch boundary: no physics behavior or calibration change is proposed in this deck.");
}

function slide03(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = WHITE;
  addTitle(slide, "The calculation chain is already inspectable", "02  /  current setup", 3);
  const labels = [
    ["Inputs", "typed values\n+ provenance"],
    ["Sources", "jet | fan\n+ airframe"],
    ["Propagation", "spreading\n+ absorption"],
    ["Receiver", "time history\n+ energy sum"],
    ["Metrics", "SEL\n+ LAmax"],
    ["Output", "NPD table\n+ 10 distances"],
  ];
  const xs = [58, 254, 450, 646, 842, 1038];
  const nodes = [];
  for (let i = 0; i < labels.length; i += 1) {
    const box = addBox(slide, `chain-box-${i}`, { left: xs[i], top: 274, width: 160, height: 126 }, { fill: i === 0 || i === 5 ? BLUE_LIGHT : PANEL, line: i === 0 || i === 5 ? BLUE_LIGHT : PANEL, borderRadius: "rounded-lg" });
    nodes.push(box);
    addText(slide, `chain-label-${i}`, labels[i][0], { left: xs[i] + 16, top: 300, width: 128, height: 28 }, { fontSize: 22, bold: true, color: INK, alignment: "center" });
    addText(slide, `chain-detail-${i}`, labels[i][1].replaceAll("+", ""), { left: xs[i] + 16, top: 340, width: 128, height: 44 }, { fontSize: 17, color: MUTED, alignment: "center" });
  }
  for (let i = 0; i < nodes.length - 1; i += 1) {
    slide.shapes.connect(nodes[i], nodes[i + 1], {
      kind: "straight",
      fromSide: "right",
      toSide: "left",
      line: { style: "solid", fill: BLUE, width: 2 },
      head: { type: "arrow", width: "sm", length: "sm" },
    });
  }
  addText(slide, "chain-note", "The learned ET/RF route and component-physics route remain independent; comparison is downstream evidence, never shared fitting.", { left: 160, top: 482, width: 960, height: 58 }, { fontSize: 22, color: MUTED, alignment: "center" });
  addNotes(slide, "[Sources]\nImplementation: projects/pnmf/pnmf/physics.py; projects/pnmf/pnmf/api.py.\nArchitecture: projects/pnmf/docs/NPD_SYSTEM_DESIGN.md, sections 6.3-6.5.\nThe arrows are an editable schematic of the documented source-to-receiver flow.");
}

function slide04(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = WHITE;
  addTitle(slide, "Several controls are already in place", "03  /  current setup", 4);
  addText(slide, "The baseline is not empty; it has strong seams to preserve.", { left: M, top: 185, width: 540, height: 48 }, { fontSize: 28, bold: true, color: INK });
  addStatusRow(slide, 0, "Independent routes", "ET/RF learning and PhysicsNPDModel do not share fitting or targets.", "blue");
  addStatusRow(slide, 1, "Visible provenance", "Inputs stay supplied, estimated, or unavailable; fallbacks are named.", "gray");
  addStatusRow(slide, 2, "Inspectable events", "Component spectra, time histories, energetic sums, SEL, and LAmax are retained.", "blue");
  addText(slide, "controlled-foot", "SI units are internal to physics; ANP/Doc-29 conversions happen at the boundary.", { left: M, top: 590, width: 540, height: 42 }, { fontSize: 20, color: MUTED });
  addNotes(slide, "[Sources]\nImplementation and tests: projects/pnmf/pnmf/physics.py; projects/pnmf/tests/test_physics.py.\nArchitecture: projects/pnmf/docs/MODEL_ARCHITECTURE_REPORT.md; projects/pnmf/docs/NPD_SYSTEM_DESIGN.md.");
}

function slide05(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = WHITE;
  addTitle(slide, "The physical route is a component-to-event model", "04  /  current setup", 5);
  addText(slide, "Source mechanisms", { left: M, top: 184, width: 350, height: 36 }, { fontSize: 26, bold: true, color: INK });
  const sourceRows = [
    ["JET", "Stone-style multi-stream path; simplified mixed-jet fallback"],
    ["FAN", "Heidmann-style engine-deck path; estimated fan fallback"],
    ["CORE", "Optional combustor branch; disabled until complete inputs exist"],
    ["AIRFRAME", "Six Fink-style components: wing, slat, flap edges, nose/main gear"],
    ["EVENT", "160 kt straight level reference path; 69 emission angles"],
  ];
  for (let i = 0; i < sourceRows.length; i += 1) {
    const y = 238 + i * 68;
    addTag(slide, `source-tag-${i}`, sourceRows[i][0], M, y + 5, 120, i === 0 || i === 1 ? BLUE_LIGHT : PANEL, i === 0 || i === 1 ? BLUE : INK);
    addText(slide, `source-row-${i}`, sourceRows[i][1], { left: 200, top: y + 8, width: 475, height: 42 }, { fontSize: 18, color: MUTED });
    addRule(slide, `source-rule-${i}`, 200, y + 56, 470, RULE, 1);
  }
  addBox(slide, "formula-panel", { left: 755, top: 198, width: 457, height: 352 }, { fill: PANEL, line: PANEL, borderRadius: "rounded-xl" });
  addText(slide, "formula-title", "What the event actually produces", { left: 790, top: 232, width: 370, height: 36 }, { fontSize: 24, bold: true, color: INK });
  addBulletList(slide, "formula-list", ["one-third-octave spectra", "frequency-dependent absorption", "receiver level history", "energetic component sum", "SEL and LAmax", "ANP-shaped NPD rows"], { left: 790, top: 292, width: 355, height: 190 }, { fontSize: 20, color: INK });
  addText(slide, "This is an auditable screening route, not a certification engine.", { left: 790, top: 510, width: 360, height: 40 }, { fontSize: 18, bold: true, color: BLUE });
  addNotes(slide, "[Sources]\nFormulas and event definition: projects/pnmf/docs/NPD_SYSTEM_DESIGN.md, sections 6.3-6.5.\nImplementation: projects/pnmf/pnmf/physics.py.\nScope: SEL/LAmax only; EPNL/PNLTM tone corrections are not implemented.");
}

function slide06(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = WHITE;
  addTitle(slide, "The main limitations are evidence and applicability limits", "05  /  current boundary", 6);
  addText(slide, "These are not hidden defects; they are the conditions that decide when the output deserves review.", { left: M, top: 172, width: 1000, height: 40 }, { fontSize: 22, color: MUTED });
  const cols = [58, 270, 698, 1020];
  const widths = [212, 428, 322];
  const headers = ["Area", "Current state", "Implication"];
  for (let i = 0; i < 3; i += 1) addCell(slide, `lim-head-${i}`, headers[i], cols[i], 225, widths[i], 48, { fill: INK, line: INK, color: WHITE, bold: true, fontSize: 17 });
  const rows = [
    ["Engine inputs", "Detailed mass-flow, nozzle, fan-map, and core data are optional.", "Fallbacks can dominate the result."],
    ["Geometry", "Presets keep published span/BPR fields but estimate high-lift and strut geometry.", "Mechanism fidelity is uneven."],
    ["Propagation", "Free-field spreading plus atmospheric absorption only.", "Installation and terrain effects stay out."],
    ["Validation", "ANP fleet comparisons are system-level; component measurements are not yet a ledger.", "Agreement is not component proof."],
    ["Uncertainty", "Tree spread and route disagreement are warning signals, not calibrated physics intervals.", "Do not present them as confidence bounds."],
  ];
  for (let r = 0; r < rows.length; r += 1) {
    const y = 273 + r * 67;
    for (let c = 0; c < 3; c += 1) addCell(slide, `lim-${r}-${c}`, rows[r][c], cols[c], y, widths[c], 67, { fill: r % 2 === 0 ? WHITE : PANEL, line: RULE, fontSize: c === 0 ? 16 : 15, bold: c === 0 });
  }
  addNotes(slide, "[Sources]\nLimitations: projects/pnmf/docs/NPD_SYSTEM_DESIGN.md, sections 6.3-6.6; projects/pnmf/docs/PHYSICS_PRESETS.md.\nValidation boundary: projects/pnmf/docs/PROJECT_UNDERSTANDING.md; projects/pnmf/pnmf/validation.py.\nUncertainty wording is intentionally non-certification language.");
}

function slide07(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = WHITE;
  addTitle(slide, "The urgent reproducibility gap is the word 'frozen'", "06  /  control point", 7);
  const left = addBox(slide, "policy-box", { left: 78, top: 220, width: 300, height: 184 }, { fill: PANEL, line: PANEL, borderRadius: "rounded-xl" });
  addText(slide, "policy-label", "POLICY", { left: 112, top: 252, width: 190, height: 24 }, { fontSize: 17, bold: true, color: MUTED, alignment: "center" });
  addText(slide, "policy-text", "Calibrate once\non A320-211\nthen freeze", { left: 112, top: 295, width: 230, height: 96 }, { fontSize: 29, bold: true, color: INK, alignment: "center" });
  const runtime = addBox(slide, "runtime-box", { left: 478, top: 220, width: 340, height: 184 }, { fill: BLUE_LIGHT, line: BLUE_LIGHT, borderRadius: "rounded-xl" });
  addText(slide, "runtime-label", "CURRENT RUNTIME", { left: 512, top: 252, width: 270, height: 24 }, { fontSize: 17, bold: true, color: BLUE, alignment: "center" });
  addText(slide, "runtime-text", "First cross-check\nrefits from the\nlocal database", { left: 512, top: 295, width: 270, height: 96 }, { fontSize: 29, bold: true, color: INK, alignment: "center" });
  slide.shapes.connect(left, runtime, { kind: "straight", fromSide: "right", toSide: "left", line: { style: "solid", fill: BLUE, width: 3 }, head: { type: "arrow", width: "med", length: "med" } });
  addBox(slide, "artifact-box", { left: 898, top: 204, width: 320, height: 252 }, { fill: WHITE, line: RULE, borderRadius: "rounded-xl" });
  addText(slide, "artifact-title", "Stability artifact", { left: 930, top: 234, width: 250, height: 30 }, { fontSize: 25, bold: true, color: INK });
  addBulletList(slide, "artifact-list", ["five fitted parameters", "A320-211 / BPR 6.0", "corpus and code fingerprints", "runtime + solver metadata", "canonical outputs + tolerances"], { left: 930, top: 286, width: 245, height: 140 }, { fontSize: 17, color: MUTED });
  addText(slide, "The two-month fix is provenance and repeatability, not another offset.", { left: 110, top: 515, width: 1030, height: 40 }, { fontSize: 23, bold: true, color: BLUE, alignment: "center" });
  addNotes(slide, "[Sources]\nPolicy language: projects/pnmf/docs/NPD_SYSTEM_DESIGN.md, section 6.6.\nRuntime behavior: projects/pnmf/pnmf/api.py, NoisePredictor._calibrated_physics().\nCLI calibration path: projects/pnmf/pnmf_cli.py, cmd_physics().\nThis slide describes the implementation gap to be stabilized; it does not change it.");
}

function slide08(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = WHITE;
  addTitle(slide, "The applicability boundary must stay visible", "07  /  control point", 8);
  addBox(slide, "included-panel", { left: M, top: 205, width: 520, height: 310 }, { fill: BLUE_LIGHT, line: BLUE_LIGHT, borderRadius: "rounded-xl" });
  addText(slide, "included-title", "Included baseline", { left: 94, top: 239, width: 360, height: 34 }, { fontSize: 27, bold: true, color: BLUE });
  addBulletList(slide, "included-list", ["conventional subsonic conceptual screening", "SEL and LAmax", "SI-internal component physics", "160 kt straight-level reference event", "free-field spreading + atmospheric absorption"], { left: 94, top: 300, width: 400, height: 165 }, { fontSize: 19, color: INK });
  addBox(slide, "excluded-panel", { left: 704, top: 205, width: 520, height: 310 }, { fill: PANEL, line: PANEL, borderRadius: "rounded-xl" });
  addText(slide, "excluded-title", "Explicitly excluded", { left: 742, top: 239, width: 360, height: 34 }, { fontSize: 27, bold: true, color: INK });
  addBulletList(slide, "excluded-list", ["installation and shielding", "nacelle treatment and suppression", "ground reflection and terrain", "lateral attenuation", "non-uniform atmosphere", "EPNL / PNLTM tone corrections"], { left: 742, top: 300, width: 410, height: 190 }, { fontSize: 19, color: INK });
  addText(slide, "A future mechanism earns a module only after it has a bounded input contract and evidence range.", { left: 118, top: 579, width: 1040, height: 38 }, { fontSize: 21, bold: true, color: MUTED, alignment: "center" });
  addNotes(slide, "[Sources]\nIncluded and excluded effects: projects/pnmf/pnmf/physics.py EventDiagnostics; projects/pnmf/docs/NPD_SYSTEM_DESIGN.md, sections 6.5-6.6.\nFuture mechanism priorities: projects/pnmf/docs/PHYSICAL_MODEL_IMPROVEMENT_RESEARCH.md.\nSupersonic NASA/SERDP09 material is outside this subsonic stabilization scope.");
}

function addTimeline(slide, activeIndex) {
  const start = 78;
  const gap = 10;
  const width = 128;
  const labels = ["W1-2", "W3-4", "W5-6", "W7-8"];
  for (let i = 0; i < 4; i += 1) {
    const x = start + i * (width + gap);
    addBox(slide, `timeline-${i}`, { left: x, top: 168, width, height: 54 }, { fill: i === activeIndex ? BLUE : PANEL, line: i === activeIndex ? BLUE : PANEL, borderRadius: "rounded-md" });
    addText(slide, `timeline-label-${i}`, labels[i], { left: x + 10, top: 183, width: width - 20, height: 24 }, { fontSize: 20, bold: true, color: i === activeIndex ? WHITE : INK, alignment: "center" });
    if (i < 3) addRule(slide, `timeline-rule-${i}`, x + width, 194, gap, RULE, 2);
  }
}

function slide09(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = WHITE;
  addTitle(slide, "Weeks 1-2: freeze the baseline before touching the physics", "08  /  eight-week plan", 9);
  addTimeline(slide, 0);
  addText(slide, "Deliverable", { left: 78, top: 280, width: 200, height: 30 }, { fontSize: 24, bold: true, color: BLUE });
  addText(slide, "A versioned calibration and canonical-output package that can be rerun without refitting.", { left: 78, top: 320, width: 520, height: 70 }, { fontSize: 26, bold: true, color: INK });
  addText(slide, "Capture", { left: 700, top: 280, width: 200, height: 30 }, { fontSize: 24, bold: true, color: BLUE });
  addBulletList(slide, "w12-list", ["C_jet, C_fan, C_wingflap, C_gear, f_scale", "A320-211 / BPR 6.0 reference context", "corpus, code, runtime, and solver fingerprints", "departure + approach canonical cases", "declared tolerance-equivalent output checks"], { left: 700, top: 322, width: 450, height: 168 }, { fontSize: 19, color: INK });
  addBox(slide, "w12-gate", { left: 78, top: 540, width: 1070, height: 62 }, { fill: PANEL, line: PANEL, borderRadius: "rounded-lg" });
  addText(slide, "w12-gate-text", "Gate: the same input and calibration context produce equivalent outputs, with no hidden runtime fit.", { left: 106, top: 557, width: 1012, height: 26 }, { fontSize: 21, bold: true, color: INK, alignment: "center" });
  addNotes(slide, "[Sources]\nCalibration contract: projects/pnmf/docs/NPD_SYSTEM_DESIGN.md, section 6.6.\nRuntime gap: projects/pnmf/pnmf/api.py and projects/pnmf/pnmf_cli.py.\nThis is a proposed stabilization deliverable, not a claim that the artifact already exists.");
}

function slide10(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = WHITE;
  addTitle(slide, "Weeks 3-4: define when the model is usable", "09  /  eight-week plan", 10);
  addTimeline(slide, 1);
  addText(slide, "One applicability matrix", { left: 78, top: 275, width: 360, height: 32 }, { fontSize: 25, bold: true, color: BLUE });
  const matrix = [
    ["Input / path", "Supplied", "Estimated", "Unavailable"],
    ["Jet / fan", "deck gate passes", "fallback named", "no source claim"],
    ["Airframe", "typed geometry", "preset estimate", "review required"],
    ["Atmosphere", "typed state", "standard default", "outside validity"],
    ["Trajectory", "segment state", "reference event", "do not infer"],
  ];
  const xs = [78, 330, 566, 802, 1040];
  const ws = [252, 236, 236, 238];
  for (let c = 0; c < 4; c += 1) addCell(slide, `app-h-${c}`, matrix[0][c], xs[c], 328, ws[c], 42, { fill: INK, line: INK, color: WHITE, bold: true, fontSize: 15 });
  for (let r = 1; r < matrix.length; r += 1) for (let c = 0; c < 4; c += 1) addCell(slide, `app-${r}-${c}`, matrix[r][c], xs[c], 370 + (r - 1) * 48, ws[c], 48, { fill: r % 2 === 0 ? PANEL : WHITE, line: RULE, fontSize: c === 0 ? 15 : 14, bold: c === 0 });
  addText(slide, "Gate: every result reports what was supplied, estimated, unavailable, or excluded.", { left: 110, top: 610, width: 1040, height: 28 }, { fontSize: 21, bold: true, color: BLUE, alignment: "center" });
  addNotes(slide, "[Sources]\nInput provenance contracts: projects/pnmf/pnmf/physics.py (PhysicalInput, InputStatus, EnginePhysicalInputs, AirframePhysicalInputs, AtmosphericPhysicalInputs, FlightTrajectoryInputs).\nPreset assumptions: projects/pnmf/docs/PHYSICS_PRESETS.md.\nThe matrix is a proposed reporting contract.");
}

function slide11(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = WHITE;
  addTitle(slide, "Weeks 5-6: organize validation and uncertainty", "10  /  eight-week plan", 11);
  addTimeline(slide, 2);
  addBox(slide, "ledger-box", { left: 78, top: 270, width: 512, height: 270 }, { fill: PANEL, line: PANEL, borderRadius: "rounded-xl" });
  addText(slide, "ledger-title", "Validation ledger", { left: 112, top: 302, width: 350, height: 32 }, { fontSize: 27, bold: true, color: INK });
  addBulletList(slide, "ledger-list", ["analytical and contract checks", "A320 calibration evidence", "fleet-level ANP comparison", "component spectra / directivity evidence", "measurement and applicability gaps"], { left: 112, top: 360, width: 400, height: 150 }, { fontSize: 19, color: INK });
  addBox(slide, "uncertainty-box", { left: 650, top: 270, width: 512, height: 270 }, { fill: BLUE_LIGHT, line: BLUE_LIGHT, borderRadius: "rounded-xl" });
  addText(slide, "uncertainty-title", "Uncertainty register", { left: 684, top: 302, width: 390, height: 32 }, { fontSize: 27, bold: true, color: BLUE });
  addBulletList(slide, "uncertainty-list", ["input uncertainty", "model-form uncertainty", "calibration anchoring", "measurement uncertainty", "no invented confidence interval"], { left: 684, top: 360, width: 400, height: 150 }, { fontSize: 19, color: INK });
  addText(slide, "Gate: claims identify the evidence tier they actually rely on.", { left: 110, top: 610, width: 1040, height: 28 }, { fontSize: 21, bold: true, color: BLUE, alignment: "center" });
  addNotes(slide, "[Sources]\nValidation ladder and uncertainty rationale: projects/pnmf/docs/PHYSICAL_MODEL_IMPROVEMENT_RESEARCH.md.\nCurrent tests: projects/pnmf/tests/test_physics.py.\nCurrent uncertainty boundary: projects/pnmf/pnmf/validation.py and projects/pnmf/docs/PROJECT_UNDERSTANDING.md.");
}

function slide12(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = WHITE;
  addTitle(slide, "Weeks 7-8: close the stability gate", "11  /  decision", 12);
  addText(slide, "At the end of two months, the question is not 'is it perfect?'\nIt is 'can we explain when to trust it, and reproduce what it does?'", { left: M, top: 190, width: 700, height: 150 }, { fontSize: 34, bold: true, color: INK });
  addBox(slide, "gate-box", { left: 810, top: 180, width: 410, height: 326 }, { fill: BLUE_LIGHT, line: BLUE_LIGHT, borderRadius: "rounded-xl" });
  addText(slide, "gate-title", "Green-light criteria", { left: 846, top: 214, width: 330, height: 34 }, { fontSize: 27, bold: true, color: BLUE });
  addBulletList(slide, "gate-list", ["versioned calibration loads", "canonical outputs match tolerance", "provenance is complete", "exclusions remain visible", "full suite and report rerun pass", "advisor review accepts the boundary"], { left: 846, top: 274, width: 330, height: 188 }, { fontSize: 19, color: INK });
  addBox(slide, "next-box", { left: M, top: 390, width: 680, height: 152 }, { fill: PANEL, line: PANEL, borderRadius: "rounded-xl" });
  addText(slide, "next-title", "Only after the gate", { left: 92, top: 418, width: 270, height: 28 }, { fontSize: 23, bold: true, color: INK });
  addText(slide, "engine decks  |  modern high-lift mechanisms  |  installation/scattering  |  segmented trajectories  |  advanced propagation", { left: 92, top: 460, width: 590, height: 52 }, { fontSize: 19, color: MUTED });
  addText(slide, "The proposed outcome is a stable platform for the next scientific question.", { left: M, top: 602, width: 1120, height: 32 }, { fontSize: 23, bold: true, color: BLUE, alignment: "center" });
  addNotes(slide, "[Sources]\nClosing boundary: projects/pnmf/docs/PHYSICAL_MODEL_IMPROVEMENT_RESEARCH.md; projects/pnmf/docs/NPD_SYSTEM_DESIGN.md.\nNo new numerical result or certification claim is made.\nFuture priorities are evidence-gated and separate from the two-month stabilization bar.");
}

async function writeBlob(path, blob) {
  await fs.mkdir(path.substring(0, path.lastIndexOf("/")), { recursive: true });
  await fs.writeFile(path, new Uint8Array(await blob.arrayBuffer()));
}

async function main() {
  const presentation = Presentation.create({ slideSize: { width: W, height: H } });
  slide01(presentation);
  slide02(presentation);
  slide03(presentation);
  slide04(presentation);
  slide05(presentation);
  slide06(presentation);
  slide07(presentation);
  slide08(presentation);
  slide09(presentation);
  slide10(presentation);
  slide11(presentation);
  slide12(presentation);

  await fs.mkdir(workOut, { recursive: true });
  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    await writeBlob(`${workOut}/${stem}.png`, await presentation.export({ slide, format: "png", scale: 1 }));
    await fs.writeFile(`${workOut}/${stem}.layout.json`, await (await slide.export({ format: "layout" })).text());
  }
  await writeBlob(`${workOut}/deck-montage.webp`, await presentation.export({ format: "webp", montage: true, scale: 1 }));
  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(finalPath);
  await fs.writeFile(`${workOut}/deck-inspect.ndjson`, (await presentation.inspect({ kind: "slide,textbox,shape,notes", maxChars: 30000 })).ndjson);
  console.log(`Created ${finalPath}`);
  console.log(`Slides: ${presentation.slides.items.length}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});







