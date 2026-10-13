import io
import pandas as pd
from openpyxl import load_workbook
from nova.ui.common import excel_bytes, pdf_bytes, safe_csv


def test_excel_csv_exports_preserve_amounts_and_do_not_execute_formulas():
    frame = pd.DataFrame([{'Name': '=HYPERLINK("example")', 'Amount': 1000.01}])
    workbook = load_workbook(io.BytesIO(excel_bytes(frame)))
    sheet = workbook.active
    assert sheet['A2'].data_type == 's'
    assert sheet['A2'].value == '=HYPERLINK("example")'
    assert sheet['B2'].value == 1000.01
    assert "'=HYPERLINK" in safe_csv(frame).decode('utf-8-sig')


def test_printable_pdf_generation():
    frame = pd.DataFrame([{'Description': 'Sample <test> & transaction', 'Debit': 1000.01, 'Credit': 0.0}])
    pdf = pdf_bytes(frame, 'Sample voucher')
    assert pdf.startswith(b'%PDF-')
    assert len(pdf) > 1000
