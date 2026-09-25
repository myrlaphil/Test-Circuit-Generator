"""exam_pdf.py - turn a list of problems into a two-part PDF: questions, then solutions."""
from __future__ import annotations

import io
import re
from typing import List, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BODY = ParagraphStyle("b", fontName="Helvetica", fontSize=11, leading=15, spaceAfter=6)
H1 = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=16, leading=20, spaceAfter=10)
SMALL = ParagraphStyle("s", parent=BODY, fontSize=9.5, leading=13)


def _md(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return text


def _fig(png: bytes, max_w=4.6 * inch, max_h=3.0 * inch) -> Image:
    from PIL import Image as PILImage
    w, h = PILImage.open(io.BytesIO(png)).size
    scale = min(max_w / w, max_h / h)
    return Image(io.BytesIO(png), width=w * scale, height=h * scale)


def build(problems: List[Tuple[str, str, bytes, str]], title="Circuit problems", with_solutions=True) -> bytes:
    """problems: [(question_text, solution_markdown, png_bytes, answers_text)]"""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.9 * inch, rightMargin=0.9 * inch,
                            topMargin=0.8 * inch, bottomMargin=0.8 * inch, title=title)
    S = [Paragraph(title, H1),
         Paragraph("Show your work and include units.", SMALL), Spacer(1, 8)]
    for i, (q, _, png, _) in enumerate(problems, 1):
        S.append(KeepTogether([Paragraph(f"<b>{i}.</b> {_md(q)}", BODY), _fig(png), Spacer(1, 16)]))
    if with_solutions:
        S.append(PageBreak())
        S.append(Paragraph(title + " - solutions", H1))
        for i, (q, sol, png, ans) in enumerate(problems, 1):
            block = [Paragraph(f"<b>{i}.</b> {_md(q)}", BODY), _fig(png, 3.2 * inch, 2.0 * inch)]
            lines = [ln for ln in sol.splitlines()]
            table_rows = []
            for ln in lines:
                if ln.startswith("|"):
                    cells = [c.strip() for c in ln.strip("|").split("|")]
                    if not set("".join(cells)) <= set("-: "):
                        table_rows.append(cells)
                elif ln.strip():
                    block.append(Paragraph(_md(ln), SMALL))
            if table_rows:
                t = Table(table_rows, hAlign="LEFT")
                t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 9), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                                       ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke)]))
                block.append(t)
            block.append(Spacer(1, 14))
            S.append(KeepTogether(block))
    doc.build(S)
    return buf.getvalue()
