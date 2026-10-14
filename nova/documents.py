"""Branded A4 financial documents. All monetary totals use integer paisa."""
import html
import io
from datetime import datetime, timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from decimal import Decimal
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from nova.branding import BUSINESS, LOGO
from nova.models import Account, Booking, Installment, Invoice, InvoiceItem, Line, Party, Project, Setting, Unit, User, Voucher
from nova.services.common import rupees

for name, file in [('NovaSans', 'DejaVuSans.ttf'), ('NovaSansBold', 'DejaVuSans-Bold.ttf')]:
    pdfmetrics.registerFont(TTFont(name, str(LOGO.parent / 'fonts' / file)))
INK = colors.HexColor('#18334b')
GOLD = colors.HexColor('#cba334')
TEXT = ParagraphStyle('NovaText', fontName='NovaSans', fontSize=9, leading=13, textColor=INK)
SMALL = ParagraphStyle('NovaSmall', parent=TEXT, fontSize=8, leading=11)
TITLE = ParagraphStyle('NovaTitle', parent=TEXT, fontName='NovaSansBold', fontSize=19, leading=24)


def p(value, style=TEXT):
    return Paragraph(html.escape(str(value if value is not None else '')).replace('\n', '<br/>'), style)


def format_money(value):
    return f'{Decimal(str(value)) / 100:,.2f}'


def build(session, title, number, metadata, columns, rows, widths, totals, notes=''):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=38, rightMargin=38, topMargin=34, bottomMargin=42)
    setting = lambda key: (session.get(Setting, key).value if session.get(Setting, key) else '')
    business = setting('business_name') or BUSINESS
    header_text = [p(business, TITLE)]
    for key in ('business_address', 'business_contact'):
        if setting(key):
            header_text.append(p(setting(key), SMALL))
    logo = Image(str(LOGO), width=75, height=75) if LOGO.exists() else p('NOVA', TITLE)
    header = Table([[logo, header_text]], colWidths=[90, 429])
    header.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LINEBELOW', (0, 0), (-1, -1), 1.5, GOLD)]))
    story = [header, Spacer(1, 18), p(title, TITLE), p(f'Document No. {number}', TEXT), Spacer(1, 12)]
    meta = Table([[p(k, SMALL), p(v)] for k, v in metadata], colWidths=[115, 404])
    meta.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
    story += [meta, Spacer(1, 16)]
    data = [[p(c, SMALL) for c in columns]] + [[p(c, SMALL) for c in row] for row in rows]
    grid = Table(data, colWidths=widths, repeatRows=1, splitInRow=1)
    grid.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9eff5')),
          ('LINEBELOW', (0, 0), (-1, 0), 1, GOLD), ('GRID', (0, 1), (-1, -1), .3, colors.HexColor('#dce4ec')),
          ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    story += [grid, Spacer(1, 12)]
    total_table = Table([[p(k), p(v)] for k, v in totals], colWidths=[389, 130])
    total_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f5f7fa')),
                                    ('LINEABOVE', (0, 0), (-1, 0), 1, GOLD), ('BOTTOMPADDING', (0, 0), (-1, -1), 7)]))
    story += [total_table, Spacer(1, 16)]
    if notes:
        story += [p(notes, SMALL), Spacer(1, 14)]
    story += [KeepTogether([Spacer(1, 20), Table([[p('Prepared by: ______________', SMALL), p('Approved by: ______________', SMALL),
                                               p('Received by: ______________', SMALL)]], colWidths=[173, 173, 173])])]
    if setting('business_footer'):
        story += [Spacer(1, 16), p(setting('business_footer'), SMALL)]
    def footer(canvas, document):
        canvas.setStrokeColor(GOLD)
        canvas.line(38, 30, A4[0] - 38, 30)
        canvas.setFont('NovaSans', 7)
        canvas.setFillColor(INK)
        canvas.drawString(38, 19, f'Nova ERP | {number} | PKR')
        canvas.drawRightString(A4[0] - 38, 19, f'Page {document.page}')
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def voucher_pdf(session, voucher_id):
    v = session.get(Voucher, voucher_id)
    project = session.get(Project, v.project_id)
    creator = session.get(User, v.created_by)
    lines = session.execute(select(Line, Account, Party).join(Account, Line.account_id == Account.id)
                             .outerjoin(Party, Line.party_id == Party.id).where(Line.voucher_id == v.id).order_by(Account.code, Line.id)).all()
    rows = [[str(index), a.code + '\n' + a.name, (l.description or '') + ('\nParty: ' + party.name if party else ''),
             format_money(l.debit), format_money(l.credit)] for index, (l, a, party) in enumerate(lines, 1)]
    meta = [('Date', v.date.isoformat()), ('Project', project.name), ('Status', v.status), ('Payment mode', v.payment_mode or v.kind),
            ('Payment type', v.payment_type or 'Not specified'), ('Description', v.description), ('Prepared by', creator.name)]
    debit, credit = sum(l.debit for l, _, _ in lines), sum(l.credit for l, _, _ in lines)
    return build(session, 'GENERAL PAYMENTS' if v.kind == 'Payment' else v.kind.upper() + ' VOUCHER', v.number, meta,
                 ['SR', 'Account', 'Description / party', 'Debit', 'Credit'], rows, [25, 135, 189, 85, 85],
                 [('Total debit (PKR)', format_money(debit)), ('Total credit (PKR)', format_money(credit))],
                 'Pending or rejected documents are not proof of approved posting.' if v.status != 'Posted' else '')


def invoice_pdf(session, invoice_id):
    from nova.services.sales import invoice_paid
    obj = session.get(Invoice, invoice_id)
    v, party, project = session.get(Voucher, obj.voucher_id), session.get(Party, obj.party_id), session.get(Project, obj.project_id)
    paid = invoice_paid(session, obj.id)
    meta = [('Invoice reference', obj.reference), ('Date', str(obj.date)), ('Due date', str(obj.due)), ('Project', project.name),
            ('Customer / supplier', party.name), ('Contact', party.phone), ('Address', party.address), ('Status', 'Rejected / Cancelled' if obj.status == 'Rejected' else v.status)]
    items = session.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == obj.id).order_by(InvoiceItem.sequence)).all()
    rows = [[str(n), item.description, format_money(item.amount)] for n, item in enumerate(items, 1)] if items else [['1', obj.description, format_money(obj.amount)]]
    return build(session, obj.kind.upper() + ' INVOICE', v.number, meta, ['SR', 'Description', 'Amount (PKR)'],
          rows, [25, 364, 130],
          [('Invoice total (PKR)', format_money(obj.amount)), ('Approved settlements (PKR)', format_money(paid)),
           ('Outstanding (PKR)', format_money(0 if obj.status == 'Rejected' else obj.amount - paid))],
          'Draft / awaiting approval. Amounts are not included in approved balances.' if v.status != 'Posted' else '')


def booking_pdf(session, booking_id):
    from nova.services.sales import booking_paid
    b = session.get(Booking, booking_id)
    unit, customer = session.get(Unit, b.unit_id), session.get(Party, b.party_id)
    project = session.get(Project, unit.project_id)
    schedule = session.scalars(select(Installment).where(Installment.booking_id == b.id).order_by(Installment.sequence)).all()
    return build(session, 'UNIT BOOKING FORM', b.number,
         [('Project', project.name), ('Customer', customer.name), ('Unit / area', unit.number + ' / ' + unit.area),
          ('Booking date', str(b.date)), ('Status', b.status)], ['SR', 'Payment', 'Due date', 'Amount (PKR)'],
         [[str(n), 'Down payment' if i.sequence == 0 else f'Installment {i.sequence}', str(i.due), format_money(i.amount)] for n, i in enumerate(schedule, 1)],
         [25, 234, 130, 130], [('Agreed price (PKR)', format_money(b.total)), ('Approved receipts (PKR)', format_money(booking_paid(session, b.id)))], project.terms)
