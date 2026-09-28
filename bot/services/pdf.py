from __future__ import annotations

import pathlib
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from bot.database.models import Invoice
from bot.utils import fmt_num, local

_FONTS = pathlib.Path(__file__).resolve().parent.parent / "assets" / "fonts"
_registered = False


def _register_fonts() -> None:
    global _registered
    if not _registered:
        pdfmetrics.registerFont(TTFont("DejaVu", str(_FONTS / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(_FONTS / "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")
        _registered = True


def _t(value) -> str:
    return escape(str(value)) if value not in (None, "") else "-"


def build_invoice_pdf(inv: Invoice) -> bytes:
    """Nakladnoyni bazadagi ma'lumotlar asosida elektron hujjat (PDF) qilib chiqaradi.
    `inv` supplier, customer, sales_agent, expediter, submitter va items(product) bilan yuklangan bo'lishi kerak."""
    _register_fonts()
    base = ParagraphStyle("base", fontName="DejaVu", fontSize=9, leading=12)
    bold = ParagraphStyle("bold", parent=base, fontName="DejaVu-Bold")
    title = ParagraphStyle("title", parent=bold, fontSize=14, leading=18, alignment=1)
    center = ParagraphStyle("center", parent=base, alignment=1)
    right = ParagraphStyle("right", parent=base, alignment=2)
    right_b = ParagraphStyle("right_b", parent=bold, alignment=2, fontSize=10)
    small = ParagraphStyle("small", parent=base, fontSize=7.5, leading=10, textColor=colors.grey)

    sup, cus = inv.supplier, inv.customer
    story = [
        Paragraph(f"ТОВАРНАЯ НАКЛАДНАЯ №{_t(inv.invoice_number)}", title),
        Paragraph(f"Дата: {inv.date:%d.%m.%Y}", center),
        Spacer(1, 6 * mm),
    ]

    left = [Paragraph("<b>Поставщик</b>", base), Paragraph(_t(sup.name), bold),
            Paragraph(f"ИНН: {_t(sup.inn)}", base), Paragraph(f"Адрес: {_t(sup.address)}", base),
            Paragraph(f"Телефон: {_t(sup.phone)}", base)]
    rgt = [Paragraph("<b>Покупатель</b>", base), Paragraph(_t(cus.name), bold),
           Paragraph(f"ИНН: {_t(cus.inn)}", base), Paragraph(f"Адрес: {_t(cus.address)}", base),
           Paragraph(f"Код клиента: {_t(cus.client_code)}", base)]
    parties = Table([[left, rgt]], colWidths=[90 * mm, 90 * mm])
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                                 ("LINEAFTER", (0, 0), (0, 0), 0.5, colors.grey), ("LEFTPADDING", (0, 0), (-1, -1), 6),
                                 ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [parties, Spacer(1, 3 * mm)]
    story.append(Paragraph(
        f"Агент: <b>{_t(inv.sales_agent.full_name if inv.sales_agent else None)}</b> &nbsp;&nbsp;&nbsp; "
        f"Экспедитор: <b>{_t(inv.expediter.full_name if inv.expediter else None)}</b>", base))
    story.append(Spacer(1, 4 * mm))

    data = [[Paragraph(h, bold) for h in ("№", "Код", "Наименование товара", "Ед.", "Кол-во", "Цена за уп.", "Всего")]]
    for i, it in enumerate(inv.items, 1):
        data.append([str(i), _plain(it.product.code), Paragraph(_t(it.product.name), base), _plain(it.product.unit),
                     fmt_num(it.quantity), fmt_num(it.unit_price), fmt_num(it.line_total)])
    widths = [8, 18, 64, 14, 22, 26, 28]
    table = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 1), (-1, -1), "DejaVu"), ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (4, 1), (-1, -1), "RIGHT"), ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [table, KeepTogether([
        Spacer(1, 4 * mm),
        Paragraph(f"Итого (кол-во): <b>{fmt_num(inv.total_qty)}</b>", right),
        Paragraph(f"Всего к оплате: {fmt_num(inv.total_sum)} сум", right_b),
        Spacer(1, 10 * mm),
        Paragraph(f"Электронная копия. Внёс в систему: {_t(inv.submitter.full_name)}, "
                  f"{local(inv.created_at):%d.%m.%Y %H:%M}. Сформировано ботом на основе данных из базы.", small),
    ])]

    buf = BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                      bottomMargin=15 * mm, title=f"Накладная {inv.invoice_number}").build(story)
    return buf.getvalue()


def _plain(value) -> str:
    return str(value) if value not in (None, "") else "-"
