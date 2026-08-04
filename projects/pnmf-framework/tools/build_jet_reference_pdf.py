"""Build the measured ANP v6.3 jet release-holdout report PDF."""
from __future__ import annotations

import json
from pathlib import Path
from textwrap import wrap

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, Table, TableStyle
from reportlab.pdfgen import canvas


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "output" / "pdf" / "PNMF_Jet_Reference_Validation_Report.pdf"
ASSETS = PROJECT_ROOT / "docs" / "jet_reference_assets"
EVIDENCE = PROJECT_ROOT / "outputs" / "model_validation" / "jet_reference_v63"

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
TOP = PAGE_H - 18 * mm
BOTTOM = 16 * mm

NAVY = colors.HexColor("#17324D")
BLUE = colors.HexColor("#137CBD")
LIGHT_BLUE = colors.HexColor("#EAF4FA")
PALE = colors.HexColor("#F5F7F9")
GREEN = colors.HexColor("#27815C")
TEXT = colors.HexColor("#24313C")
MUTED = colors.HexColor("#667582")
RULE = colors.HexColor("#D4DDE4")
WHITE = colors.white

BODY = ParagraphStyle(
    "Body", fontName="Helvetica", fontSize=9.2, leading=13.1, textColor=TEXT
)
SMALL = ParagraphStyle(
    "Small", parent=BODY, fontSize=7.7, leading=10.4
)
TABLE_TEXT = ParagraphStyle(
    "Table", parent=BODY, fontSize=7.3, leading=9.1
)
CENTER = ParagraphStyle(
    "Center", parent=TABLE_TEXT, alignment=TA_CENTER
)
HEADER_TABLE_TEXT = ParagraphStyle(
    "HeaderTable",
    parent=TABLE_TEXT,
    fontName="Helvetica-Bold",
    textColor=WHITE,
)
HEADER_CENTER = ParagraphStyle(
    "HeaderCenter",
    parent=HEADER_TABLE_TEXT,
    alignment=TA_CENTER,
)


class Report:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.canvas = canvas.Canvas(str(path), pagesize=A4)
        self.page = 0

    def new_page(self, title: str, section: str = "") -> None:
        if self.page:
            self.canvas.showPage()
        self.page += 1
        self.canvas.setFillColor(NAVY)
        self.canvas.rect(0, PAGE_H - 13 * mm, PAGE_W, 13 * mm, fill=1, stroke=0)
        self.canvas.setFillColor(WHITE)
        self.canvas.setFont("Helvetica-Bold", 8.2)
        self.canvas.drawString(MARGIN_X, PAGE_H - 8.5 * mm, "PNMF  |  MODEL VALIDATION")
        self.canvas.setFont("Helvetica", 7.5)
        self.canvas.drawRightString(
            PAGE_W - MARGIN_X, PAGE_H - 8.5 * mm, section.upper()
        )
        self.canvas.setFillColor(NAVY)
        self.canvas.setFont("Helvetica-Bold", 19)
        self.canvas.drawString(MARGIN_X, TOP - 9 * mm, title)
        self.canvas.setStrokeColor(BLUE)
        self.canvas.setLineWidth(2.2)
        self.canvas.line(
            MARGIN_X, TOP - 13 * mm, MARGIN_X + 24 * mm, TOP - 13 * mm
        )

    def footer(
        self, note: str = "Conceptual screening evidence - not certification evidence"
    ) -> None:
        self.canvas.setStrokeColor(RULE)
        self.canvas.setLineWidth(0.5)
        self.canvas.line(MARGIN_X, BOTTOM, PAGE_W - MARGIN_X, BOTTOM)
        self.canvas.setFillColor(MUTED)
        self.canvas.setFont("Helvetica", 7.2)
        self.canvas.drawString(MARGIN_X, BOTTOM - 4.2 * mm, note)
        self.canvas.drawRightString(
            PAGE_W - MARGIN_X, BOTTOM - 4.2 * mm, f"Page {self.page}"
        )

    def heading(self, text: str, y: float, size: float = 12.5) -> float:
        self.canvas.setFillColor(NAVY)
        self.canvas.setFont("Helvetica-Bold", size)
        self.canvas.drawString(MARGIN_X, y, text)
        return y - 6 * mm

    def paragraph(
        self,
        text: str,
        y: float,
        width: float | None = None,
        style: ParagraphStyle = BODY,
        x: float = MARGIN_X,
    ) -> float:
        width = width or PAGE_W - 2 * MARGIN_X
        paragraph = Paragraph(text, style)
        _, height = paragraph.wrap(width, PAGE_H)
        paragraph.drawOn(self.canvas, x, y - height)
        return y - height - 3 * mm

    def bullet(self, text: str, y: float, width: float | None = None) -> float:
        return self.paragraph(f"-&nbsp;&nbsp;{text}", y, width)

    def image(
        self, name: str, x: float, y_top: float, width: float, height: float
    ) -> None:
        image = Image(
            str(ASSETS / name), width=width, height=height, kind="proportional"
        )
        image.drawOn(self.canvas, x, y_top - height)

    def table(
        self,
        data: list[list[object]],
        y_top: float,
        widths: list[float],
        x: float = MARGIN_X,
        font_size: float = 7.4,
    ) -> float:
        normalized = []
        for row_index, row in enumerate(data):
            normalized_row = []
            for col, value in enumerate(row):
                if row_index == 0:
                    header_value = (
                        value.getPlainText()
                        if isinstance(value, Paragraph)
                        else str(value)
                    )
                    style = HEADER_TABLE_TEXT if col == 0 else HEADER_CENTER
                    normalized_row.append(Paragraph(header_value, style))
                elif isinstance(value, Paragraph):
                    normalized_row.append(value)
                else:
                    normalized_row.append(
                        Paragraph(str(value), TABLE_TEXT if col == 0 else CENTER)
                    )
            normalized.append(normalized_row)
        table = Table(normalized, colWidths=widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                    ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), font_size),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("GRID", (0, 0), (-1, -1), 0.35, RULE),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PALE]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        _, height = table.wrap(sum(widths), PAGE_H)
        table.drawOn(self.canvas, x, y_top - height)
        return y_top - height - 4 * mm

    def kpi(
        self, x: float, y: float, width: float, value: str, label: str, color=BLUE
    ) -> None:
        self.canvas.setFillColor(LIGHT_BLUE)
        self.canvas.roundRect(x, y, width, 25 * mm, 3 * mm, fill=1, stroke=0)
        self.canvas.setFillColor(color)
        self.canvas.setFont("Helvetica-Bold", 20)
        self.canvas.drawCentredString(x + width / 2, y + 13.5 * mm, value)
        self.canvas.setFillColor(TEXT)
        self.canvas.setFont("Helvetica", 7.8)
        for index, line in enumerate(wrap(label, width=24)):
            self.canvas.drawCentredString(
                x + width / 2, y + (7 - 3.2 * index) * mm, line
            )

    def finish(self) -> None:
        self.canvas.save()


def _metric_rows(summary: pd.DataFrame, scope: str) -> pd.DataFrame:
    return summary[summary["scope"] == scope].copy()


def _fmt(value: float) -> str:
    return f"{float(value):.3f}"


def build() -> Path:
    """Build a six-page report directly from the saved v6.3 evidence."""
    summary = pd.read_csv(EVIDENCE / "summary.csv")
    references = pd.read_csv(EVIDENCE / "reference_metadata.csv")
    manifest = json.loads((EVIDENCE / "run_manifest.json").read_text("utf-8"))
    counts = manifest["counts"]
    conclusion = manifest["official_conclusion"]
    urls = manifest["official_source_urls"]
    overall = _metric_rows(summary, "overall")
    category = _metric_rows(summary, "category_overall")

    def metric(model: str, aggregation: str, field: str) -> float:
        row = overall[
            overall["model"].eq(model) & overall["aggregation"].eq(aggregation)
        ]
        return float(row.iloc[0][field])

    report = Report(OUTPUT)
    formula_style = ParagraphStyle(
        "Formula",
        parent=BODY,
        fontName="Courier-Bold",
        fontSize=8.5,
        leading=12,
        backColor=LIGHT_BLUE,
        borderPadding=7,
    )

    report.new_page("ANP v6.3 Jet Release Holdout", "Executive summary")
    y = TOP - 24 * mm
    y = report.paragraph(
        "<b>A source-separated check of PNMF's production Extra Trees and "
        "Random Forest models.</b> Models train only on legacy v2.3 Jet curves "
        "after a predeclared family purge and are scored on three frozen v6.3 "
        "reference curves.",
        y,
        style=ParagraphStyle("Lead", parent=BODY, fontSize=11.5, leading=16.2),
    )
    gap = 4 * mm
    box_w = (PAGE_W - 2 * MARGIN_X - 3 * gap) / 4
    box_y = y - 31 * mm
    report.kpi(MARGIN_X, box_y, box_w, "76 / 3", "legacy train / v6.3 test curves")
    report.kpi(MARGIN_X + box_w + gap, box_y, box_w, "1,160", "scored power-distance cells")
    report.kpi(
        MARGIN_X + 2 * (box_w + gap),
        box_y,
        box_w,
        _fmt(metric("et", "cell_pooled", "rmse_dB")),
        "ET pooled RMSE, dB",
        GREEN,
    )
    report.kpi(
        MARGIN_X + 3 * (box_w + gap),
        box_y,
        box_w,
        _fmt(metric("rf", "cell_pooled", "rmse_dB")),
        "RF pooled RMSE, dB",
        GREEN,
    )
    y = report.heading("Official-source conclusion", box_y - 10 * mm)
    y = report.paragraph(f"<b>{conclusion}</b>", y)
    y = report.paragraph(
        "This is a provenance and chronology judgment, not a universal "
        "curve-accuracy claim. Both model scores are close in this small holdout; "
        "the category tables are more informative than a winner label.",
        y,
    )
    y = report.heading("Evidence boundary", y - 2 * mm)
    for text in [
        "Only three independent curves are tested; the 1,160 cells are correlated.",
        "Tri- and quad-engine categories each have one v6.3 candidate only.",
        "Use for conceptual screening and model scrutiny, never certification.",
    ]:
        y = report.bullet(text, y)
    report.footer()

    report.new_page("Sources, Selection, and Split", "Evidence design")
    y = TOP - 23 * mm
    y = report.paragraph(
        "EASA states that it collects, verifies and makes ANP information "
        "available under Regulation (EU) No 598/2014. EASA separately labels "
        "v2.3 as legacy data assembled before that mandate.",
        y,
    )
    y = report.paragraph(
        f"<link href='{urls['easa_anp_data']}' color='#137CBD'>"
        "EASA Aircraft Noise and Performance (ANP)</link>  |  "
        f"<link href='{urls['easa_anp_legacy_data']}' color='#137CBD'>"
        "EASA ANP legacy data</link>  |  "
        f"<link href='{urls['eu_regulation_598_2014']}' color='#137CBD'>"
        "Regulation (EU) 598/2014</link>",
        y,
        style=SMALL,
    )
    report.image(
        "jet_reference_architecture.png",
        MARGIN_X,
        y,
        PAGE_W - 2 * MARGIN_X,
        43 * mm,
    )
    y -= 50 * mm
    selection = [["Eng.", "Frozen NPD / ACFT_ID", "Description", "Distance"]]
    for row in references.sort_values("engine_count").itertuples(index=False):
        selection.append(
            [
                str(int(row.engine_count)),
                f"{row.npd_id} / {row.acft_id}",
                row.description,
                f"{row.robust_distance:.6f}",
            ]
        )
    y = report.table(
        selection, y, [17 * mm, 45 * mm, 82 * mm, 32 * mm]
    )
    y = report.paragraph(
        "<b>Descriptor-only rule:</b> per-category IQR-scaled Euclidean "
        "distance over log10(MTOW), log10(total static thrust), and noise "
        "chapter. Zero-IQR terms contribute zero; lexical NPD_ID breaks ties. "
        "Targets and errors never select a reference.",
        y,
        style=SMALL,
    )
    split = [
        ["Evidence unit", "Train", "Test", "Interpretation"],
        ["Jet curves", "76", "3", "v2.3 only / v6.3 only"],
        ["Approach rows per metric", "216", "12", "Power rows"],
        ["Departure rows per metric", "297", "17", "Power rows"],
        ["All test cells", "-", "1,160", "116 rows x 10 distances"],
    ]
    report.table(split, y, [48 * mm, 22 * mm, 22 * mm, 84 * mm])
    report.footer()

    report.new_page("Separation and Learning Method", "Method")
    y = TOP - 23 * mm
    y = report.heading("Predeclared family guard", y)
    y = report.paragraph(
        "Before fitting, seven legacy NPDs are excluded: <b>CF680E, TRENT7, "
        "JT9DBD, JT9DFL, JT9D7Q, PW4056, and GENX67</b>. They conservatively "
        "guard the A330 and 747 families represented in the v6.3 holdout. "
        "Falcon 20 is not automatically purged; no broad name heuristic is used.",
        y,
    )
    purge_table = [
        ["Stage", "Twin", "Tri", "Quad", "Total"],
        ["Legacy complete-task Jet pool", "59", "9", "15", "83"],
        ["Predeclared exclusions", "2", "0", "5", "7"],
        ["Training after purge", "57", "9", "10", "76"],
        ["Frozen v6.3 test", "1", "1", "1", "3"],
    ]
    y = report.table(
        purge_table, y, [72 * mm, 26 * mm, 26 * mm, 26 * mm, 26 * mm]
    )
    y = report.heading("Models and tasks", y - 2 * mm)
    models = [
        ["Route", "Configuration", "Coverage"],
        ["Extra Trees", "500 trees; depth 24; features 0.5; leaf 1", "8 tasks"],
        ["Random Forest", "200 bootstrap trees; leaf 2", "8 tasks"],
    ]
    y = report.table(models, y, [42 * mm, 88 * mm, 46 * mm])
    y = report.paragraph(
        "Each task predicts ten standard NPD distances. Inputs retain the frozen "
        "12-feature learned surface and mixed-power-unit correction. Predictions "
        "retain the non-increasing distance projection.",
        y,
    )
    y = report.heading("Scoring formulas", y - 2 * mm)
    y = report.paragraph(
        "error = prediction - truth<br/>"
        "RMSE = sqrt(mean(error^2)); MAE = mean(abs(error))<br/>"
        "bias = mean(error); p90 = percentile(abs(error), 90)<br/>"
        "within +/-k dB = 100 x mean(abs(error) &lt;= k)",
        y,
        style=formula_style,
    )
    report.paragraph(
        "PhysicsNPDModel remains an independent SEL/LAmax component-source "
        "workflow. It supplies neither features nor targets to ET/RF here.",
        y,
    )
    report.footer()

    report.new_page("Overall Measured Results", "ET and RF")
    y = TOP - 23 * mm
    table = [
        ["Model", "Aggregation", "RMSE", "MAE", "Bias", "P90 abs", "+/-3", "+/-5"]
    ]
    for model in ("et", "rf"):
        for aggregation, label in (
            ("cell_pooled", "Cell pooled"),
            ("category_balanced", "Category balanced"),
        ):
            row = overall[
                overall["model"].eq(model)
                & overall["aggregation"].eq(aggregation)
            ].iloc[0]
            table.append(
                [
                    model.upper(),
                    label,
                    _fmt(row.rmse_dB),
                    _fmt(row.mae_dB),
                    f"{row.bias_dB:+.3f}",
                    _fmt(row.p90_abs_error_dB),
                    f"{row.pct_within_3_dB:.3f}%",
                    f"{row.pct_within_5_dB:.3f}%",
                ]
            )
    y = report.table(
        table,
        y,
        [16 * mm, 42 * mm, 21 * mm, 20 * mm, 20 * mm, 23 * mm, 22 * mm, 22 * mm],
    )
    report.image(
        "jet_reference_metrics.png",
        MARGIN_X + 6 * mm,
        y,
        PAGE_W - 2 * MARGIN_X - 12 * mm,
        98 * mm,
    )
    y -= 106 * mm
    report.paragraph(
        "Cell-pooled metrics weight every cell equally. Category-balanced "
        "metrics give twin, tri, and quad categories equal influence; balanced "
        'RMSE is the square root of mean category MSE. "Within +/-3 dB" and '
        '"within +/-5 dB" are threshold-agreement percentages over correlated '
        "cells, not success probabilities or certification margins.",
        y,
        style=SMALL,
    )
    report.footer()

    report.new_page("Reference-Level Error Patterns", "Diagnostics")
    y = TOP - 23 * mm
    table = [["Model", "Eng.", "RMSE", "MAE", "Bias", "P90", "+/-3", "+/-5"]]
    pooled_category = category[category["aggregation"].eq("cell_pooled")]
    for row in pooled_category.sort_values(
        ["model", "engine_count_category"]
    ).itertuples(index=False):
        table.append(
            [
                row.model.upper(),
                str(row.engine_count_category),
                _fmt(row.rmse_dB),
                _fmt(row.mae_dB),
                f"{row.bias_dB:+.3f}",
                _fmt(row.p90_abs_error_dB),
                f"{row.pct_within_3_dB:.2f}%",
                f"{row.pct_within_5_dB:.2f}%",
            ]
        )
    y = report.table(
        table,
        y,
        [17 * mm, 17 * mm, 22 * mm, 21 * mm, 22 * mm, 22 * mm, 27 * mm, 28 * mm],
    )
    report.image(
        "jet_reference_residual_heatmap.png",
        MARGIN_X + 20 * mm,
        y,
        PAGE_W - 2 * MARGIN_X - 40 * mm,
        60 * mm,
    )
    y -= 65 * mm
    report.image(
        "jet_reference_npd_comparison.png",
        MARGIN_X,
        y,
        PAGE_W - 2 * MARGIN_X,
        50 * mm,
    )
    y -= 55 * mm
    report.paragraph(
        "The lower chart is an illustrative maximum-power SEL departure slice. "
        "The four-engine reference shows a positive bias for both learners. "
        "All eight tasks and every power row remain in predictions.csv.",
        y,
        style=SMALL,
    )
    report.footer()

    report.new_page("Validity Boundaries and Audit Trail", "Conclusion")
    y = TOP - 23 * mm
    y = report.paragraph(
        f"<b>{conclusion}</b>",
        y,
        style=ParagraphStyle(
            "BoundaryLead", parent=BODY, fontSize=10.8, leading=15.2
        ),
    )
    y = report.heading("Scientific limitations", y - 2 * mm)
    for text in [
        "Three independent curves are too few for fleet-wide or certification claims.",
        "The 1,160 cells are repeated observations within those curves and are correlated.",
        "Tri- and quad-engine categories each have one v6.3 candidate; neither is a general representative.",
        "Selection uses only weight, installed thrust, and noise chapter.",
        "The family purge reduces obvious A330/747 leakage but cannot prove absence of all engineering similarity.",
        "Results do not establish performance for unconventional aircraft or propulsion.",
    ]:
        y = report.bullet(text, y)
    y = report.heading("Reproducible evidence", y - 2 * mm)
    y = report.paragraph(
        f"Seed {manifest['config']['seed']}. Datastore SHA-256 "
        f"<font name='Courier'>{manifest['inputs']['datastore_sha256']}</font>. "
        "Candidate scores, reference metadata, exclusions, predictions, fit "
        "records, summaries, source manifest, official URLs, and artifact hashes "
        "are saved under "
        "<font name='Courier'>outputs/model_validation/jet_reference_v63</font>.",
        y,
        style=SMALL,
    )
    y = report.heading("Decision boundary", y - 2 * mm)
    report.paragraph(
        "Use this release holdout as a transparent diagnostic of legacy-trained "
        "ET/RF behavior on the three frozen v6.3 references. It does not replace "
        "broader grouped validation and must not be presented as universal "
        "accuracy or certification evidence.",
        y,
    )
    report.footer("PNMF v6.3 release holdout | Saved measured results")
    report.finish()
    return OUTPUT


if __name__ == "__main__":
    print(build())
