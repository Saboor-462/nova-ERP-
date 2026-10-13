from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import func, select
import pytest
from nova.models import Account, Booking, Credential, FinancialYear, Installment, Invoice, Line, Party, Project, User, Voucher
from nova.services import accounting, master, records, reports, sales, security
from nova.services.common import BusinessError, business_today
from nova.services.overview import diagnostics, hierarchy


def project(session):
    return session.scalar(select(Project.id))


def journal(session, actor, token):
    return accounting.create_voucher(session, actor, project(session), business_today(), 'Journal', 'Test journal',
      [accounting.line(accounting.account(session, '1100'), debit=10000), accounting.line(accounting.account(session, '3000'), credit=10000)], token)


def test_login_logout_and_no_plain_passwords(db):
    factory, actors = db
    with factory.begin() as s:
        security.set_password(s, actors['Admin'], actors['Admin'], 'Private Test Passphrase')
    token, error = security.authenticate(factory, 'admin@demo.local', 'Private Test Passphrase')
    assert token and error is None
    assert security.session_user(factory, token).id == actors['Admin']
    with factory() as s:
        hashed = s.get(Credential, actors['Admin']).password_hash
        assert hashed.startswith('$argon2id$') and 'Private Test' not in hashed
    security.logout(factory, token)
    assert security.session_user(factory, token) is None


def test_lockout_inactive_and_password_reset_revoke_sessions(db):
    factory, actors = db
    with factory.begin() as s:
        security.set_password(s, actors['Admin'], actors['Accountant'], 'Accountant Test Passphrase')
    for _ in range(5):
        assert security.authenticate(factory, 'accountant@demo.local', 'wrong')[0] is None
    assert 'locked' in security.authenticate(factory, 'accountant@demo.local', 'Accountant Test Passphrase')[1]
    with factory.begin() as s:
        security.set_password(s, actors['Admin'], actors['Accountant'], 'Another Test Passphrase')
    token, _ = security.authenticate(factory, 'accountant@demo.local', 'Another Test Passphrase')
    assert token
    with factory.begin() as s:
        s.get(User, actors['Accountant']).active = False
    assert security.session_user(factory, token) is None
    assert security.authenticate(factory, 'accountant@demo.local', 'Another Test Passphrase')[0] is None


def test_numbering_continues_pending_rejected_and_edits(db):
    factory, actors = db
    with factory.begin() as s:
        v1, v2 = journal(s, actors['Accountant'], 'seq:1'), journal(s, actors['Accountant'], 'seq:2')
        n1, n2, identity = v1.number, v2.number, v1.id
        assert int(n2.split('-')[1]) == int(n1.split('-')[1]) + 1
        rows = [accounting.line(accounting.account(s, '1100'), debit=15000), accounting.line(accounting.account(s, '3000'), credit=15000)]
        records.edit_voucher(s, actors['Accountant'], v1.id, business_today(), 'Edited journal', rows)
        assert v1.id == identity and v1.number == n1
        records.cancel_pending(s, actors['Accountant'], v1.id, 'Mistake')
        v3 = journal(s, actors['Accountant'], 'seq:3')
        assert int(v3.number.split('-')[1]) == int(n2.split('-')[1]) + 1


def test_sequential_numbers_are_unique_under_concurrency(db):
    factory, actors = db
    def create(i):
        with factory.begin() as s:
            return journal(s, actors['Accountant'], f'parallel:{i}').number
    with ThreadPoolExecutor(max_workers=3) as pool:
        numbers = list(pool.map(create, range(6)))
    values = sorted(int(n.split('-')[1]) for n in numbers)
    assert len(set(numbers)) == 6
    assert values == list(range(values[0], values[0] + 6))


def test_delete_only_unused_and_retire_account_code(db):
    factory, actors = db
    with factory.begin() as s:
        unit = s.scalar(select(Unit).where(Unit.status == 'Available'))
        identity = unit.id
        records.delete_master(s, actors['Admin'], Unit, unit.id)
    with factory() as s:
        assert s.get(Unit, identity) is None
    with factory.begin() as s:
        used = s.scalar(select(Unit).where(Unit.status == 'Booked'))
        with pytest.raises(BusinessError, match='used'):
            records.delete_master(s, actors['Admin'], Unit, used.id)
        a = master.save_account(s, actors['Admin'], code='9999', name='Temporary expense', kind='Expense')
        records.delete_master(s, actors['Admin'], Account, a.id)
    with factory.begin() as s, pytest.raises(BusinessError, match='retired'):
        master.save_account(s, actors['Admin'], code='9999', name='Reuse', kind='Expense')


from nova.models import Unit


def test_hierarchy_totals_and_no_duplicate_count(db):
    factory, actors = db
    with factory.begin() as s:
        records.ensure_account_groups(s)
        h = hierarchy(s, balance_sheet=True)
        bs, _ = reports.financials(s, paisa=True)
        for kind in ('Asset', 'Liability', 'Equity'):
            root = h.loc[(h['Type'] == kind) & (h['Level'] == 0), 'Amount'].sum()
            assert root == bs.loc[bs['Type'] == kind, 'Amount'].sum()
        assert 'Current assets' in ''.join(h['Account'])
        assert 'Furniture and fixtures' in ''.join(h['Account'])
        assert diagnostics(s).empty


def test_financial_year_audit_and_closure_rules(db):
    factory, actors = db
    with factory.begin() as s:
        year = records.save_year(s, actors['Admin'], 'Past year', date(2024, 7, 1), date(2025, 6, 30),
                                 status='Audited', auditor='External Reviewer', audited_on=business_today())
        with pytest.raises(BusinessError, match='overlap'):
            records.save_year(s, actors['Admin'], 'Overlap', date(2025, 1, 1), date(2025, 12, 31))
        with pytest.raises(BusinessError, match='marked audited'):
            accounting.create_voucher(s, actors['Accountant'], project(s), date(2025, 1, 1), 'Journal', 'Closed review',
              [accounting.line(accounting.account(s, '1100'), debit=100), accounting.line(accounting.account(s, '3000'), credit=100)], 'audited')


def test_pending_invoice_edit_and_posted_cancellation(db):
    factory, actors = db
    with factory.begin() as s:
        party = s.scalar(select(Party.id).where(Party.kind == 'Vendor'))
        i = sales.create_invoice(s, actors['Accountant'], project(s), party, 'Purchase', 'EDIT-1', business_today(), business_today(),
                                  '1000', accounting.account(s, '5000'), 'Original', 'edit:invoice')
        original_id, voucher_id = i.id, i.voucher_id
        number = s.get(Voucher, i.voucher_id).number
        records.edit_invoice(s, actors['Accountant'], i.id, 'EDIT-1', business_today(), business_today(), '500', 'Corrected')
        assert i.id == original_id and s.get(Voucher, voucher_id).number == number
        accounting.approve(s, actors['Approver'], voucher_id)
    with factory.begin() as s:
        reversal = records.void_invoice(s, actors['Accountant'], original_id, business_today(), 'Cancelled service', 'cancel:invoice')
        accounting.approve(s, actors['Approver'], reversal.id)
    with factory() as s:
        assert s.get(Invoice, original_id).status == 'Rejected'
        assert original_id not in set(reports.invoice_balances(s)['Invoice ID'])


def test_pending_booking_and_receipt_edit_keep_document_ids(db):
    factory, actors = db
    with factory.begin() as s:
        customer = s.scalar(select(Party.id).where(Party.kind == 'Customer'))
        unit = s.scalar(select(Unit.id).where(Unit.status == 'Available'))
        b = sales.create_booking(s, actors['Accountant'], unit, customer, business_today(), '1000', '100', 3, business_today(), 'edit:booking')
        b_id, b_number, v_id = b.id, b.number, b.voucher_id
        records.edit_booking(s, actors['Accountant'], b.id, business_today(), '1200', '200', 5, business_today())
        assert b.id == b_id and b.number == b_number and b.voucher_id == v_id
        assert s.scalar(select(func.sum(Installment.amount)).where(Installment.booking_id == b.id)) == 120000
        accounting.approve(s, actors['Approver'], b.voucher_id)
        r = sales.receive(s, actors['Accountant'], b.id, accounting.account(s, '1100'), business_today(), '100', 'Receipt', 'edit:receipt')
        rid, rn = r.id, r.number
    with factory.begin() as s:
        records.edit_pending_payment(s, actors['Accountant'], rid, business_today(), '200', 'Corrected receipt')
        assert s.get(Voucher, rid).number == rn
        assert sales.booking_paid(s, b_id, True) == 20000


def test_account_edit_cycle_and_identity(db):
    factory, actors = db
    with factory.begin() as s:
        records.ensure_account_groups(s)
        group = s.scalar(select(Account).where(Account.code == '1001'))
        root = s.scalar(select(Account).where(Account.code == '100'))
        with pytest.raises(BusinessError, match='cycle'):
            records.edit_account(s, actors['Admin'], root.id, root.name, group.id, True)
        furniture = s.scalar(select(Account).where(Account.code == '1400'))
        original = furniture.id
        records.edit_account(s, actors['Admin'], furniture.id, 'Office furniture', furniture.parent_id, True)
        assert furniture.id == original and furniture.code == '1400'


def test_itemized_invoice_and_amount_validation(db):
    factory, actors = db
    with factory.begin() as s:
        vendor = s.scalar(select(Party.id).where(Party.kind == 'Vendor'))
        invoice = sales.create_invoice(s, actors['Accountant'], project(s), vendor, 'Purchase', 'ITEM-1', business_today(), business_today(),
          '1000', accounting.account(s, '5000'), 'Two services', 'item:1', items=[{'description': 'Service A', 'amount': 60000}, {'description': 'Service B', 'amount': 40000}])
        from nova.models import InvoiceItem
        assert s.scalar(select(func.sum(InvoiceItem.amount)).where(InvoiceItem.invoice_id == invoice.id)) == invoice.amount
        with pytest.raises(BusinessError, match='equal'):
            records.validate_invoice_items([{'description': 'Wrong total', 'amount': 9999}], 10000)


def test_auto_account_codes_keep_separate_sequence(db):
    factory, actors = db
    with factory.begin() as s:
        a = master.save_account(s, actors['Admin'], code='', name='Expense A', kind='Expense')
        b = master.save_account(s, actors['Admin'], code='', name='Expense B', kind='Expense')
        assert a.code == 'AC-0001' and b.code == 'AC-0002'


def test_fresh_app_requires_login_and_no_business_seeding():
    from streamlit.testing.v1 import AppTest
    from nova.config import ROOT
    from nova.db import session_factory
    app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
    assert not app.exception and not app.sidebar.radio
    assert any(i.label == 'Password' for i in app.text_input)
    with session_factory()() as s:
        assert s.scalar(select(func.count()).select_from(Project)) == 0
        assert s.scalar(select(func.count()).select_from(Voucher)) == 0


def test_new_voucher_add_row_and_dashboard_views():
    from tests.helpers import login_app
    app = login_app()
    for view in ('Project dashboard', 'Balance sheet dashboard', 'Consolidated financial dashboard'):
        next(r for r in app.radio if r.label == 'Dashboard view').set_value(view).run()
        assert not app.exception
    app.sidebar.radio[0].set_value('Vouchers').run()
    next(r for r in app.radio if r.label == 'Voucher section').set_value('New Voucher').run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 2
    next(b for b in app.button if b.label == 'Add Row').click().run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 3
    assert next(b for b in app.button if b.label == 'Submit for approval').disabled


def test_login_session_revoked_on_password_reset(db):
    factory, actors = db
    with factory.begin() as s:
        security.set_password(s, actors['Admin'], actors['Accountant'], 'Original Test Password')
    token, _ = security.authenticate(factory, 'accountant@demo.local', 'Original Test Password')
    with factory.begin() as s:
        security.set_password(s, actors['Admin'], actors['Accountant'], 'Replacement Test Password')
    assert security.session_user(factory, token) is None
    assert security.authenticate(factory, 'accountant@demo.local', 'Original Test Password')[0] is None
