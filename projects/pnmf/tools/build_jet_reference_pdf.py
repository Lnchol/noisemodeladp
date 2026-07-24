"""Build the PNMF frozen jet-reference validation report PDF."""
from __future__ import annotations

from pathlib import Path
from textwrap import wrap

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Image, Paragraph, Table, TableStyle
from reportlab.pdfgen import canvas


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "output" / "pdf" / "PNMF_Jet_Reference_Validation_Report.pdf"
ASSETS = PROJECT_ROOT / "docs" / "jet_reference_assets"

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
TOP = PAGE_H - 18 * mm
BOTTOM = 16 * mm

NAVY = colors.HexColor("#17324D")
BLUE = colors.HexColor("#137CBD")
LIGHT_BLUE = colors.HexColor("#EAF4FA")
PALE = colors.HexColor("#F5F7F9")
ORANGE = colors.HexColor("#D55E00")
GREEN = colors.HexColor("#27815C")
TEXT = colors.HexColor("#24313C")
MUTED = colors.HexColor("#667582")
RULE = colors.HexColor("#D4DDE4")
WHITE = colors.white

BODY = ParagraphStyle(
    "Body",
    fontName="Helvetica",
    fontSize=9.2,
    leading=13.1,
    textColor=TEXT,
)
SMALL = ParagraphStyle(
    "Small",
    parent=BODY,
    fontSize=7.7,
    leading=10.4,
)
TABLE_TEXT = ParagraphStyle(
    "Table",
    parent=BODY,
    fontSize=7.4,
    leading=9.2,
)
CENTER = ParagraphStyle(
    "Center",
    parent=TABLE_TEXT,
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
        self.canvas.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 8.5 * mm, section.upper())
        self.canvas.setFillColor(NAVY)
        self.canvas.setFont("Helvetica-Bold", 19)
        self.canvas.drawString(MARGIN_X, TOP - 9 * mm, title)
        self.canvas.setStrokeColor(BLUE)
        self.canvas.setLineWidth(2.2)
        self.canvas.line(MARGIN_X, TOP - 13 * mm, MARGIN_X + 24 * mm, TOP - 13 * mm)

    def footer(self, note: str = "Conceptual screening evidence - not certification evidence") -> None:
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
        p = Paragraph(text, style)
        _, height = p.wrap(width, PAGE_H)
        p.drawOn(self.canvas, x, y - height)
        return y - height - 3 * mm

    def bullet(self, text: str, y: float, width: float | None = None) -> float:
        return self.paragraph(f"<bullet>&bull;</bullet>{text}", y, width)

    def image(self, name: str, x: float, y_top: float, width: float, height: float) -> None:
        img = Image(str(ASSETS / name), width=width, height=height, kind="proportional")
        img.drawOn(self.canvas, x, y_top - height)

    def table(
        self,
        data: list[list[object]],
        y_top: float,
        widths: list[float],
        row_heights: list[float] | None = None,
        x: float = MARGIN_X,
        font_size: float = 7.5,
    ) -> float:
        normalized = [
            [
                value
                if isinstance(value, Paragraph)
                else Paragraph(str(value), TABLE_TEXT if col == 0 else CENTER)
                for col, value in enumerate(row)
            ]
            for row in data
        ]
        table = Table(normalized, colWidths=widths, rowHeights=row_heights, repeatRows=1)
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

    def kpi(self, x: float, y: float, w: float, value: str, label: str, color=BLUE) -> None:
        self.canvas.setFillColor(LIGHT_BLUE)
        self.canvas.roundRect(x, y, w, 25 * mm, 3 * mm, fill=1, stroke=0)
        self.canvas.setFillColor(color)
        self.canvas.setFont("Helvetica-Bold", 20)
        self.canvas.drawCentredString(x + w / 2, y + 13.5 * mm, value)
        self.canvas.setFillColor(TEXT)
        self.canvas.setFont("Helvetica", 7.8)
        for idx, line in enumerate(wrap(label, width=24)):
            self.canvas.drawCentredString(x + w / 2, y + (7 - 3.2 * idx) * mm, line)

    def finish(self) -> None:
        self.canvas.save()


def build() -> Path:
    """Build the bounded six-page handoff edition."""
    r = Report(OUTPUT)
    formula_style = ParagraphStyle(
        "ConciseFormula",
        parent=BODY,
        fontName="Courier-Bold",
        fontSize=9.2,
        leading=13,
        backColor=LIGHT_BLUE,
        borderPadding=8,
    )

    r.new_page("Frozen Jet-Reference Validation", "Executive summary")
    y = TOP - 24 * mm
    y = r.paragraph(
        "<b>A transparent sanity check of PNMF's production Extra Trees and Random "
        "Forest models.</b> Three conventional jet references were frozen before "
        "errors were calculated, with every connected aircraft identity removed "
        "from training.",
        y,
        style=ParagraphStyle("ConciseLead", parent=BODY, fontSize=12, leading=17),
    )
    gap = 4 * mm
    box_w = (PAGE_W - 2 * MARGIN_X - 3 * gap) / 4
    box_y = y - 31 * mm
    r.kpi(MARGIN_X, box_y, box_w, "94", "complete-task jet curves")
    r.kpi(MARGIN_X + box_w + gap, box_y, box_w, "91 / 3", "train / test curves")
    r.kpi(MARGIN_X + 2 * (box_w + gap), box_y, box_w, "4.659", "RF pooled RMSE, dB", GREEN)
    r.kpi(MARGIN_X + 3 * (box_w + gap), box_y, box_w, "64.423%", "RF cells within +/-5 dB", GREEN)
    y = r.heading("Plain-language result", box_y - 10 * mm)
    for text in [
        "<b>RF:</b> 4.659 dB pooled RMSE and 64.423% of cells within +/-5 dB.",
        "<b>ET:</b> 5.125 dB pooled RMSE and 57.885% of cells within +/-5 dB.",
        "Category-balanced RMSE is 4.633 dB for RF and 4.840 dB for ET.",
        "Performance differs materially by category; the four-engine ET reference "
        "is the clearest weakness.",
        "The 1,040 cells are correlated observations inside only <b>three "
        "independent curves</b>. Threshold agreement is not general accuracy.",
    ]:
        y = r.bullet(text, y)
    y = r.heading("Decision boundary", y - 2 * mm)
    r.paragraph(
        "Use this evidence for conceptual screening and model scrutiny. It is not "
        "fleet-wide accuracy evidence and not certification evidence.",
        y,
    )
    r.footer()

    r.new_page("Data, Selection, and Split", "Evidence design")
    y = TOP - 23 * mm
    y = r.paragraph(
        "The canonical datastore combines the EASA ANP legacy v2.3 corpus with "
        "the v6.3 supplement. The complete-task jet population contains 94 curves "
        "in 93 connected aircraft-identity groups.",
        y,
    )
    r.image("jet_reference_architecture.png", MARGIN_X, y, PAGE_W - 2 * MARGIN_X, 43 * mm)
    y -= 50 * mm
    selection = [
        ["Category", "Frozen NPD", "Reference aircraft", "ACFT_ID", "Distance"],
        ["2 engines", "BR715", "Boeing 717-200", "717200", "0.036467"],
        ["3 engines", "3JT8E5", "Boeing 727-200", "727EM2", "0.023327"],
        ["4 engines", "PW4056", "Boeing 747-400", "747400", "0.352528"],
    ]
    y = r.table(selection, y, [29 * mm, 27 * mm, 49 * mm, 32 * mm, 39 * mm])
    y = r.paragraph(
        "<b>Descriptor-only rule:</b> distance = sqrt(sum_j (((x_j - median_j) / "
        "IQR_j)^2)), using log10(MTOW), log10(total static thrust), and noise "
        "chapter. Zero-IQR terms contribute zero; NPD_ID is the tie-break. Noise "
        "targets and model errors never select a reference.",
        y,
        style=SMALL,
    )
    split = [
        ["Evidence unit", "Train", "Test", "Interpretation"],
        ["Jet curves", "91", "3", "Strict identity-group separation"],
        ["Approach rows / task", "270", "10", "Held-out power rows"],
        ["Departure rows / task", "370", "16", "Held-out power rows"],
        ["All test cells", "-", "1,040", "104 power rows x 10 distances"],
    ]
    y = r.table(split, y, [46 * mm, 22 * mm, 22 * mm, 86 * mm])
    r.paragraph(
        "Only singleton identity groups are selectable. The mapping is frozen and "
        "the implementation fails if datastore drift changes it.",
        y,
        style=SMALL,
    )
    r.footer()

    r.new_page("Model Inputs and Learning Routes", "Method")
    y = TOP - 23 * mm
    y = r.paragraph(
        "Each requested power row becomes a 12-feature vector. The target is the "
        "measured NPD level vector at ten standard slant distances from 200 to "
        "25,000 ft.",
        y,
    )
    features = [
        ["#", "Feature", "Purpose"],
        ["1-3", "Engine type one-hot", "Jet / turboprop / piston indicators"],
        ["4", "Engine count", "Installed engine count"],
        ["5-6", "log10(MTOW), log10(MLW)", "Takeoff and landing weight scales"],
        ["7", "MLW / MTOW", "Relative landing-weight descriptor"],
        ["8-9", "log10(per-engine and total thrust)", "Per-engine and installed thrust"],
        ["10", "Noise chapter", "Certification-era descriptor"],
        ["11", "log10(converted row power in lbf)", "Requested operating power"],
        ["12", "Throttle", "Normalized operating setting"],
    ]
    y = r.table(features, y, [15 * mm, 76 * mm, 85 * mm])
    y = r.heading("Frozen production learners", y)
    models = [
        ["Route", "Configuration", "Plain-language behavior"],
        ["Extra Trees (ET)", "500 trees; depth 24; max features 0.5; leaf 1", "Highly randomized tree ensemble"],
        ["Random Forest (RF)", "200 bootstrap trees; leaf 2", "Bootstrap tree ensemble"],
    ]
    y = r.table(models, y, [38 * mm, 67 * mm, 71 * mm])
    y = r.heading("Scoring formulas", y)
    y = r.paragraph(
        "<font name='Courier'>error = prediction - truth</font><br/>"
        "<font name='Courier'>RMSE = sqrt(mean(error^2))</font><br/>"
        "<font name='Courier'>MAE = mean(abs(error))</font><br/>"
        "<font name='Courier'>within +/-5 = 100 x mean(abs(error) &lt;= 5)</font>",
        y,
        style=formula_style,
    )
    r.paragraph(
        "Both learned routes use the normal non-increasing distance projection. "
        "PhysicsNPDModel is separate and excluded: it supplies no features or "
        "targets to ET/RF.",
        y,
    )
    r.footer()

    r.new_page("Overall Measured Results", "ET and RF")
    y = TOP - 23 * mm
    overall = [
        ["Model", "Aggregation", "RMSE", "MAE", "Bias", "P90 abs", "Within +/-5"],
        ["ET", "Cell pooled", "5.125", "4.499", "-1.193", "7.366", "57.885%"],
        ["ET", "Category balanced", "4.840", "4.147", "-1.265", "6.430", "63.278%"],
        ["RF", "Cell pooled", "4.659", "4.304", "-0.992", "6.427", "64.423%"],
        ["RF", "Category balanced", "4.633", "4.252", "-1.375", "6.575", "63.278%"],
    ]
    y = r.table(overall, y, [18 * mm, 45 * mm, 23 * mm, 21 * mm, 21 * mm, 25 * mm, 30 * mm])
    r.image("jet_reference_metrics.png", MARGIN_X + 6 * mm, y, PAGE_W - 2 * MARGIN_X - 12 * mm, 98 * mm)
    y -= 106 * mm
    r.paragraph(
        "<b>Interpretation:</b> RF has the lower pooled RMSE. Balanced RMSE is "
        "closer because every engine-count category contributes equally. RMSE "
        "emphasizes large misses; MAE describes typical absolute cell error; bias "
        "is prediction minus truth. The threshold percentages describe correlated "
        "cells, not independent aircraft successes.",
        y,
        style=SMALL,
    )
    r.footer()

    r.new_page("Category and Curve Differences", "Error pattern")
    y = TOP - 23 * mm
    category = [
        ["Model", "Eng.", "RMSE", "MAE", "Bias", "P90", "+/-5"],
        ["ET", "2", "4.611", "4.269", "+4.248", "6.610", "63.000%"],
        ["ET", "3", "2.229", "1.863", "-1.733", "3.228", "98.333%"],
        ["ET", "4", "6.636", "6.310", "-6.310", "9.452", "28.500%"],
        ["RF", "2", "4.534", "4.294", "+4.288", "6.255", "64.500%"],
        ["RF", "3", "4.459", "3.914", "-3.867", "6.334", "55.833%"],
        ["RF", "4", "4.893", "4.547", "-4.547", "7.136", "69.500%"],
    ]
    y = r.table(category, y, [20 * mm, 18 * mm, 23 * mm, 22 * mm, 22 * mm, 22 * mm, 29 * mm])
    y = r.paragraph(
        "The four-engine reference is the main ET weakness: -6.310 dB mean bias "
        "and 28.500% of cells within +/-5 dB. RF also underpredicts it, but less.",
        y,
        style=SMALL,
    )
    r.image("jet_reference_residual_heatmap.png", MARGIN_X + 20 * mm, y, PAGE_W - 2 * MARGIN_X - 40 * mm, 62 * mm)
    y -= 67 * mm
    r.image("jet_reference_npd_comparison.png", MARGIN_X, y, PAGE_W - 2 * MARGIN_X, 52 * mm)
    y -= 57 * mm
    r.paragraph(
        "The lower chart is an illustrative maximum-power SEL departure slice. "
        "All eight tasks, power rows, and ten distances remain in predictions.csv.",
        y,
        style=SMALL,
    )
    r.footer()

    r.new_page("Validity Boundaries and Audit Trail", "Conclusion")
    y = TOP - 23 * mm
    y = r.paragraph(
        "<b>The result is a pre-frozen implementation sanity check on three "
        "conventional jet curves with strict identity separation.</b>",
        y,
        style=ParagraphStyle("BoundaryLead", parent=BODY, fontSize=11, leading=15.5),
    )
    y = r.heading("Limitations", y)
    for text in [
        "Three independent curves are too few for fleet-wide accuracy or certification.",
        "The 1,040 cells are repeated power-distance observations and are correlated.",
        "Selection represents only weight, total thrust, and noise chapter.",
        "The references do not establish performance for unseen families, unusual "
        "geometry, or unconventional propulsion.",
        "Category differences matter; pooled values can hide four-engine weakness.",
    ]:
        y = r.bullet(text, y)
    y = r.heading("Physics remains separate", y - 2 * mm)
    y = r.paragraph(
        "PhysicsNPDModel is an independent component-source cross-check for SEL and "
        "LAmax with explicit bypass-ratio/component assumptions and frozen "
        "calibration. It is not trained or evaluated here and does not feed ET/RF.",
        y,
    )
    y = r.heading("Reproducible evidence", y)
    y = r.paragraph(
        "Seed 20260724. Saved artifacts include selection_candidates.csv, "
        "reference_metadata, split.csv, predictions.csv, fit_runs.csv, summary.csv "
        "and summary.json, source_manifest.csv, and run_manifest.json under "
        "<font name='Courier'>outputs/model_validation/jet_reference</font>.",
        y,
        style=SMALL,
    )
    y = r.heading("Final interpretation", y)
    r.paragraph(
        "RF is stronger on the pooled headline in this frozen check, while balanced "
        "results are closer. Treat the category table and residual patterns as the "
        "main diagnostic evidence. Use the report for conceptual screening and "
        "model scrutiny - never as a certification or broad fleet-performance claim.",
        y,
    )
    r.footer("PNMF frozen jet-reference validation | Saved measured results")
    r.finish()
    return OUTPUT


if __name__ == "__main__":
    print(build())
