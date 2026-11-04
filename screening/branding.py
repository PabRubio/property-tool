"""Locally bundled Lacewing colours, fonts and logo used by report renderers."""
from functools import lru_cache
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ASSETS = Path(__file__).resolve().parents[1] / 'web' / 'assets'
FONT_DIR = ASSETS / 'fonts'
GREEN = '#012c21'
GOLD = '#d9ad5f'
IVORY = '#f6f1e6'
INK = '#14211d'
MUTED = '#586861'
LINE = '#dcd3bf'
TINT = '#eee7d9'
LINK = '#0b3a30'
BODY = 'Inter'
BOLD = 'Inter-SemiBold'
HEADING = 'CormorantGaramond-SemiBold'


@lru_cache(maxsize=1)
def register_fonts():
    for name, filename in (
        (BODY, 'Inter-Regular.ttf'), (BOLD, 'Inter-SemiBold.ttf'),
        ('Inter-Italic', 'Inter-Italic.ttf'), ('Inter-SemiBoldItalic', 'Inter-SemiBoldItalic.ttf'),
        ('CormorantGaramond', 'CormorantGaramond-Medium.ttf'),
        (HEADING, 'CormorantGaramond-SemiBold.ttf'),
    ):
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / filename)))
    pdfmetrics.registerFontFamily(BODY, normal=BODY, bold=BOLD,
                                  italic='Inter-Italic', boldItalic='Inter-SemiBoldItalic')
    pdfmetrics.registerFontFamily('CormorantGaramond', normal='CormorantGaramond', bold=HEADING)


@lru_cache(maxsize=1)
def logo():
    return ImageReader(str(ASSETS / 'brand-mark.webp'))


def page_background(pdf, width, height, header_height=55):
    pdf.setFillColor(colors.HexColor(IVORY))
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor(GREEN))
    pdf.rect(0, height-header_height, width, header_height, fill=1, stroke=0)


def header_logo(pdf, left, baseline):
    # The mark occupies the existing left margin; header text keeps its position.
    pdf.drawImage(logo(), left-35, baseline-3, width=28, height=18, mask='auto',
                  preserveAspectRatio=True, anchor='c')
