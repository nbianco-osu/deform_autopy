"""Regenerate PDF manuals from the Markdown sources in manual/.

Run from the DEFORM API folder:

    python regenerate_manual_pdfs.py

The Markdown files remain the source of truth. Mermaid flowcharts are rendered as
readable code blocks so the PDFs are dependency-free.
"""

from __future__ import annotations

from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import HRFlowable


ROOT = Path(__file__).resolve().parent
MANUAL_DIR = ROOT / "manual"


def escape(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clean_inline(text: str) -> str:
    """Convert a small subset of Markdown inline syntax to ReportLab markup."""
    text = escape(text)
    text = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', text)
    text = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return text


def build_styles():
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle(
            "ManualTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=21,
            leading=25,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#111827"),
            spaceAfter=12,
        ),
        "H1": ParagraphStyle(
            "ManualH1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=21,
            textColor=colors.HexColor("#111827"),
            spaceBefore=10,
            spaceAfter=7,
        ),
        "H2": ParagraphStyle(
            "ManualH2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13.2,
            leading=16,
            textColor=colors.HexColor("#1f4e79"),
            spaceBefore=10,
            spaceAfter=5,
        ),
        "H3": ParagraphStyle(
            "ManualH3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10.8,
            leading=13,
            textColor=colors.HexColor("#374151"),
            spaceBefore=7,
            spaceAfter=4,
        ),
        "Body": ParagraphStyle(
            "ManualBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=12.2,
            textColor=colors.HexColor("#1f2937"),
            spaceAfter=5,
        ),
        "Bullet": ParagraphStyle(
            "ManualBullet",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.9,
            leading=11.8,
            leftIndent=14,
            firstLineIndent=-8,
            textColor=colors.HexColor("#1f2937"),
            spaceAfter=3,
        ),
        "Code": ParagraphStyle(
            "ManualCode",
            parent=base["Code"],
            fontName="Courier",
            fontSize=6.9,
            leading=8.5,
            textColor=colors.HexColor("#111827"),
            backColor=colors.HexColor("#f3f4f6"),
            borderColor=colors.HexColor("#d1d5db"),
            borderWidth=0.35,
            borderPadding=5,
            leftIndent=0,
            rightIndent=0,
            spaceBefore=4,
            spaceAfter=7,
        ),
        "TableCell": ParagraphStyle(
            "ManualTableCell",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.8,
            leading=9.8,
            textColor=colors.HexColor("#111827"),
        ),
        "TableHeader": ParagraphStyle(
            "ManualTableHeader",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.9,
            leading=9.8,
            textColor=colors.white,
        ),
    }


def paragraph(text: str, styles, name: str = "Body"):
    return Paragraph(clean_inline(text), styles[name])


def make_table(lines: list[str], styles):
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and not all(set(cell) <= {"-", ":", " "} for cell in cells):
            rows.append(cells)
    if len(rows) < 2:
        return []
    col_count = max(len(row) for row in rows)
    rows = [row + [""] * (col_count - len(row)) for row in rows]
    usable_width = 7.1 * inch
    widths = [usable_width / col_count] * col_count
    data = []
    for row_index, row in enumerate(rows):
        style = styles["TableHeader"] if row_index == 0 else styles["TableCell"]
        data.append([Paragraph(clean_inline(cell), style) for cell in row])
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#374151")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
    ]))
    return [table, Spacer(1, 0.08 * inch)]


def parse_markdown(md_path: Path, styles):
    lines = md_path.read_text(encoding="utf-8").splitlines()
    story = []
    paragraph_buffer = []
    code_buffer = []
    table_buffer = []
    in_code = False
    title_used = False

    def flush_paragraph():
        nonlocal paragraph_buffer
        if paragraph_buffer:
            story.append(paragraph(" ".join(paragraph_buffer), styles))
            paragraph_buffer = []

    def flush_table():
        nonlocal table_buffer
        if table_buffer:
            story.extend(make_table(table_buffer, styles))
            table_buffer = []

    for line in lines:
        stripped = line.rstrip()
        if stripped.startswith("```"):
            flush_paragraph()
            flush_table()
            if in_code:
                story.append(Preformatted("\n".join(code_buffer), styles["Code"], maxLineLength=95))
                code_buffer = []
                in_code = False
            else:
                in_code = True
            continue

        if in_code:
            code_buffer.append(stripped)
            continue

        if not stripped:
            flush_paragraph()
            flush_table()
            story.append(Spacer(1, 0.04 * inch))
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            flush_paragraph()
            table_buffer.append(stripped)
            continue
        else:
            flush_table()

        if stripped.startswith("# "):
            flush_paragraph()
            text = stripped[2:].strip()
            story.append(paragraph(text, styles, "Title" if not title_used else "H1"))
            title_used = True
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#d1d5db"), spaceAfter=8))
        elif stripped.startswith("## "):
            flush_paragraph()
            story.append(paragraph(stripped[3:].strip(), styles, "H2"))
        elif stripped.startswith("### "):
            flush_paragraph()
            story.append(paragraph(stripped[4:].strip(), styles, "H3"))
        elif stripped.startswith("- "):
            flush_paragraph()
            story.append(Paragraph("- " + clean_inline(stripped[2:].strip()), styles["Bullet"]))
        elif re.match(r"^\d+\.\s+", stripped):
            flush_paragraph()
            story.append(Paragraph(clean_inline(stripped), styles["Bullet"]))
        else:
            paragraph_buffer.append(stripped)

    flush_paragraph()
    flush_table()
    if in_code and code_buffer:
        story.append(Preformatted("\n".join(code_buffer), styles["Code"], maxLineLength=95))
    return story


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    canvas.drawString(0.65 * inch, 0.45 * inch, "DEFORM automation manuals")
    canvas.drawRightString(7.85 * inch, 0.45 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build_pdf(md_path: Path):
    styles = build_styles()
    pdf_path = md_path.with_suffix(".pdf")
    doc = BaseDocTemplate(
        str(pdf_path),
        pagesize=letter,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.7 * inch,
        title=md_path.stem,
        author="DEFORM API automation",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="manual", frames=[frame], onPage=footer)])
    doc.build(parse_markdown(md_path, styles))
    return pdf_path


def main():
    outputs = []
    for md_path in sorted(MANUAL_DIR.glob("*.md")):
        outputs.append(build_pdf(md_path))
    print("Regenerated PDF manuals:")
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
