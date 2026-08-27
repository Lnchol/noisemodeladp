import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { marked } = require("marked");
const { chromium } = require("playwright");
const { PDFDocument } = require("pdf-lib");

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectDir = path.resolve(scriptDir, "..");
const reportPath = path.join(projectDir, "docs", "PNMF_METHODOLOGY_RATIONALE_AND_VALIDATION_REPORT.md");
const outputPath = path.join(projectDir, "output", "pdf", "PNMF_Methodology_Rationale_and_Validation_Report.pdf");
const temporaryDir = path.join(projectDir, "tmp", "pdfs");
const htmlPath = path.join(temporaryDir, "PNMF_Methodology_Rationale_and_Validation_Report.html");
const chromiumPath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || path.join(process.env.LOCALAPPDATA || "C:/Users/efeko/AppData/Local", "ms-playwright", "chromium-1228", "chrome-win64", "chrome.exe");

const escapeAttribute = (value) => value.replaceAll("&", "&amp;").replaceAll('"', "&quot;");

function renderDocument(markdown) {
  const renderer = new marked.Renderer();
  renderer.image = ({ href, title, text }) => {
    const titleAttribute = title ? ` title="${escapeAttribute(title)}"` : "";
    return `<figure class="report-figure"><img src="${escapeAttribute(href)}" alt="${escapeAttribute(text || "Figure")}"${titleAttribute}><figcaption>${text || "Figure"}</figcaption></figure>`;
  };
  const body = marked.parse(markdown, { gfm: true, breaks: false, renderer });
  return body.replace("<h1>", '<h1 class="report-title">');
}

function buildHtml(body) {
  const docsUrl = `file:///${projectDir.replaceAll("\\", "/")}/docs/`;
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<base href="${docsUrl}">
<title>PNMF Rationale, Methodology, and Verification &amp; Validation Report</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js" onload="renderMathInElement(document.body,{delimiters:[{left:'$$',right:'$$',display:true},{left:'\\\\[',right:'\\\\]',display:true},{left:'$',right:'$',display:false}]})"></script>
<style>
@page { size: A4 portrait; margin: 12mm 13mm 12mm 13mm; }
* { box-sizing: border-box; }
html { background: #eef2f7; }
body { margin: 0; color: #172033; background: #fff; font-family: "Aptos", "Segoe UI", Arial, sans-serif; font-size: 8.4pt; line-height: 1.24; }
main { width: 100%; }
h1, h2, h3, h4 { break-after: avoid; page-break-after: avoid; }
h1.report-title { color: #0b1f3a; font-size: 18pt; line-height: 1.08; margin: 0 0 4mm; padding: 6mm 7mm 5mm; border-radius: 5px; background: linear-gradient(135deg,#0b1f3a,#134e73); color: white; page-break-before: avoid; }
h1:not(.report-title) { color: #0b1f3a; font-size: 14pt; margin: 6mm 0 2mm; padding-bottom: 1mm; border-bottom: 1.3px solid #96a8bb; }
h2 { color: #164e73; font-size: 11pt; margin: 4mm 0 1.6mm; padding-left: 2mm; border-left: 3px solid #2c8bb8; }
h3 { color: #1d5678; font-size: 9.6pt; margin: 2.8mm 0 1.2mm; }
h4 { color: #3d566d; font-size: 8.9pt; margin: 2mm 0 .8mm; }
p { margin: 0 0 1.5mm; text-align: justify; orphans: 2; widows: 2; }
strong { color: #0b1f3a; }
code { font-family: "Cascadia Mono", Consolas, monospace; font-size: 8.1pt; color: #183b54; background: #eef4f7; padding: 0 1px; }
pre { white-space: pre-wrap; background: #f2f5f8; border: 1px solid #d1dbe4; padding: 3mm; font-size: 7.5pt; line-height: 1.2; break-inside: avoid; }
blockquote { margin: 3mm 0; padding: 2mm 4mm; border-left: 3px solid #2c8bb8; background: #f2f7fa; break-inside: avoid; }
ul, ol { margin: .6mm 0 2mm 5mm; padding-left: 3mm; }
li { margin-bottom: .5mm; }
hr { border: 0; border-top: 1px solid #c7d2dc; margin: 4mm 0; }
table { width: 100%; border-collapse: collapse; margin: 1.5mm 0 2.5mm; font-size: 6.8pt; line-height: 1.12; break-inside: auto; page-break-inside: auto; }
thead { display: table-header-group; }
tr { break-inside: avoid; page-break-inside: avoid; }
th { background: #123b58; color: #fff; font-weight: 700; text-align: left; padding: .9mm 1mm; border: 0.5px solid #aebdca; }
td { vertical-align: top; padding: .8mm 1mm; border: 0.5px solid #c6d1da; }
tbody tr:nth-child(even) { background: #f5f8fa; }
a { color: #075e87; text-decoration: underline; }
figure.report-figure { margin: 3mm auto 4mm; text-align: center; break-inside: avoid; page-break-inside: avoid; }
figure.report-figure img { display: block; width: auto; max-width: 100%; max-height: 78mm; margin: 0 auto 1mm; object-fit: contain; }
figure.report-figure figcaption { color: #475d70; font-size: 7pt; line-height: 1.14; text-align: center; }
.katex-display { margin: 3mm 0 !important; padding: 1.5mm 2mm; overflow-x: hidden; break-inside: avoid; }
.math-display { text-align: center; margin: 3mm 0; }
.page-break { break-before: page; page-break-before: always; }
@media print { html { background: white; } }
</style>
</head>
<body><main>${body}</main></body>
</html>`;
}

async function main() {
  const markdown = fs.readFileSync(reportPath, "utf8");
  fs.mkdirSync(temporaryDir, { recursive: true });
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(htmlPath, buildHtml(renderDocument(markdown)), "utf8");
  const browser = await chromium.launch({ headless: true, executablePath: chromiumPath });
  try {
    const page = await browser.newPage({ viewport: { width: 1240, height: 1754 }, deviceScaleFactor: 1 });
    await page.goto(`file:///${htmlPath.replaceAll("\\", "/")}`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => Array.from(document.images).every((image) => image.complete), null, { timeout: 15000 });
    await page.waitForFunction(() => document.fonts.ready, null, { timeout: 15000 });
    await page.waitForFunction(() => document.querySelectorAll(".katex").length > 0 || !document.body.innerText.includes("\\(") , null, { timeout: 15000 }).catch(() => {});
    await page.pdf({
      path: outputPath,
      format: "A4",
      printBackground: true,
      preferCSSPageSize: true,
      displayHeaderFooter: true,
      headerTemplate: '<div style="width:100%;font:7px Arial;color:#65788b;text-align:right;padding:0 15mm">PNMF assurance report | verified scope</div>',
      footerTemplate: '<div style="width:100%;font:7px Arial;color:#65788b;display:flex;justify-content:space-between;padding:0 15mm"><span>Conceptual screening evidence, not certification</span><span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>',
      margin: { top: "11mm", bottom: "11mm", left: "13mm", right: "13mm" },
    });
  } finally {
    await browser.close();
  }
  const bytes = fs.readFileSync(outputPath);
  const pdf = await PDFDocument.load(bytes);
  pdf.setTitle("PNMF Rationale, Methodology, and Verification & Validation Report");
  pdf.setAuthor("PNMF project");
  pdf.setSubject("Academic engineering assurance report for verified ANP conceptual screening");
  pdf.setKeywords(["PNMF", "ANP", "Doc 29", "verification", "validation", "aircraft noise"]);
  fs.writeFileSync(outputPath, await pdf.save());
  console.log(JSON.stringify({ reportPath, outputPath, htmlPath, pages: pdf.getPageCount(), bytes: fs.statSync(outputPath).size }, null, 2));
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
