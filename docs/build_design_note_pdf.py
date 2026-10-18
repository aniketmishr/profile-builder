"""Render docs/design-note.md to docs/design-note.pdf (2 pages, A4).  Needs: pip install reportlab"""
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

HERE = Path(__file__).parent
FD = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("DV", FD + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DV-B", FD + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DV-I", FD + "DejaVuSans-Oblique.ttf"))
pdfmetrics.registerFont(TTFont("DVM", FD + "DejaVuSansMono.ttf"))
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV-I", boldItalic="DV-B")

BASE = 7.9
body = ParagraphStyle("body", fontName="DV", fontSize=BASE, leading=BASE * 1.36, textColor=colors.HexColor("#1A202C"), alignment=TA_LEFT, spaceAfter=3)
h1 = ParagraphStyle("h1", parent=body, fontName="DV-B", fontSize=14.5, leading=18, spaceAfter=3)
h2 = ParagraphStyle("h2", parent=body, fontName="DV-B", fontSize=9.4, leading=12, textColor=colors.HexColor("#2B6CB0"), spaceBefore=5, spaceAfter=2, keepWithNext=1)
meta = ParagraphStyle("meta", parent=body, textColor=colors.HexColor("#4A5568"), fontSize=7.6)


def inline(t: str) -> str:
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`(.+?)`", r'<font name="DVM" size="%.1f" color="#744210">\1</font>' % (BASE - 0.7), t)
    return t


def build() -> None:
    lines = (HERE / "design-note.md").read_text(encoding="utf-8").splitlines()
    story, items, ordered = [], [], False

    def flush():
        nonlocal items
        if items:
            story.append(ListFlowable(items, bulletType="1" if ordered else "bullet", start=None if ordered else "•",
                                      bulletFontName="DV", bulletFontSize=BASE, leftIndent=11, bulletOffsetY=0))
            items = []

    for raw in lines:
        line = raw.rstrip()
        if not line:
            flush(); continue
        if line.startswith("# "):
            flush(); story.append(Paragraph(inline(line[2:]), h1))
        elif line.startswith("## "):
            flush(); story.append(Paragraph(inline(line[3:]), h2))
        elif re.match(r"^(- |\d+\. )", line):
            is_ord = bool(re.match(r"^\d+\. ", line))
            if items and is_ord != ordered:
                flush()
            ordered = is_ord
            text = re.sub(r"^(- |\d+\. )", "", line)
            items.append(ListItem(Paragraph(inline(text), body), leftIndent=11))
        else:
            flush()
            story.append(Paragraph(inline(line), meta if story and len(story) == 1 else body))
    flush()

    def footer(c, d):
        c.saveState(); c.setFont("DV", 6.8); c.setFillColor(colors.HexColor("#718096"))
        c.drawString(1.5 * cm, 0.9 * cm, "Profile Builder · design note · Aniket Mishra")
        c.drawRightString(A4[0] - 1.5 * cm, 0.9 * cm, f"Page {d.page}")
        c.restoreState()

    doc = SimpleDocTemplate(str(HERE / "design-note.pdf"), pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.3 * cm, bottomMargin=1.5 * cm, title="Profile Builder: design note", author="Aniket Mishra")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    build()
    print("wrote design-note.pdf")
