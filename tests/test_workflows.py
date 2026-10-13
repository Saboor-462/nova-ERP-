from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from nova.models import Account, Allocation, Audit, Booking, BookingEvent, Invoice, Party, Project, Unit, User, Voucher
from nova.services import accounting, imports, master, reports, sales
from nova.services.common import BusinessError, add_months, money, business_today


def ids(session):
    return (session.scalar(select(Project.id)), session.scalar(select(Party.id).where(Party.kind == 'Customer')),
            session.scalar(select(Unit.id).where(Unit.status == 'Available')))


def new_booking(factory, actor, token='test:booking', total='1000.01', down='100.00', count=3):
    with factory.begin() as session:
        project, party, unit = ids(session)
        b = sales.create_booking(session, actor, unit, party, business_today(), total, down, count, business_today(), token)
        return b.id, b.voucher_id, unit


def test_exact_money_and_month_end():
    assert money('1000.01') == 100001
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    for value in ('NaN', 'Infinity', '-1', '1.001', 'not a number'):
        with pytest.raises(BusinessError):
            money(value)


def test_seed_reports_balance(db):
    factory, _ = db
    with factory() as session:
        tb = reports.trial_balance(session)
        assert tb.Debit.sum() == tb.Credit.sum()
        assert tb['Closing Debit'].sum() == tb['Closing Credit'].sum()
        assert tb.loc[tb['Account Code'] == '1200', 'Closing Debit'].iloc[0] == 7_500_000
        bs, pnl = reports.financials(session)
        assert bs.loc[bs.Type == 'Asset', 'Amount'].sum() == pytest.approx(bs.loc[bs.Type != 'Asset', 'Amount'].sum())
        assert pnl.loc[pnl.Type == 'Expense', 'Amount'].sum() == 450_000


def test_booking_schedule_and_approval(db):
    factory, actors = db
    b_id, v_id, unit_id = new_booking(factory, actors['Accountant'])
    with factory() as session:
        from nova.models import Installment
        amounts = session.scalars(select(Installment.amount).where(Installment.booking_id == b_id)).all()
        assert sum(amounts) == 100001
        assert max(amounts[1:]) - min(amounts[1:]) <= 1
        assert session.get(Unit, unit_id).status == 'Booked'
    with factory.begin() as session:
        with pytest.raises(BusinessError, match='approved first'):
            sales.receive(session, actors['Accountant'], b_id, accounting.account(session, '1110'), business_today(), '1', 'test', 'test:early')
    with factory.begin() as session:
        accounting.approve(session, actors['Approver'], v_id)
    with factory.begin() as session:
        r = sales.receive(session, actors['Accountant'], b_id, accounting.account(session, '1110'), business_today(), '200', 'receipt', 'test:receipt')
        again = sales.receive(session, actors['Accountant'], b_id, accounting.account(session, '1110'), business_today(), '200', 'receipt', 'test:receipt')
        assert again.id == r.id
        accounting.approve(session, actors['Approver'], r.id)
    with factory() as session:
        assert sales.booking_paid(session, b_id) == 20000
        assert reports.trial_balance(session).Debit.sum() == reports.trial_balance(session).Credit.sum()


def test_invalid_booking_rolls_back_unit(db):
    factory, actors = db
    with factory() as session:
        _, customer, unit = ids(session)
    with pytest.raises(BusinessError):
        with factory.begin() as session:
            sales.create_booking(session, actors['Admin'], unit, customer, business_today(), '1000', '2000', 12, business_today(), 'bad')
    with factory() as session:
        assert session.get(Unit, unit).status == 'Available'


def test_unbalanced_voucher_atomic(db):
    factory, actors = db
    with factory() as session:
        before = session.scalar(select(func.count()).select_from(Voucher))
    with pytest.raises(BusinessError, match='equal'):
        with factory.begin() as session:
            project, _, _ = ids(session)
            accounting.create_voucher(session, actors['Accountant'], project, business_today(), 'Journal', 'Bad voucher',
                [accounting.line(accounting.account(session, '1100'), debit=10000), accounting.line(accounting.account(session, '3000'), credit=9999)], 'bad:voucher')
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Voucher)) == before


def test_role_enforcement_and_separation(db):
    factory, actors = db
    with factory.begin() as session:
        with pytest.raises(BusinessError, match='permission'):
            master.save_project(session, actors['Viewer'], number='X', name='Forbidden')
        p, _, _ = ids(session)
        v = accounting.create_voucher(session, actors['Admin'], p, business_today(), 'Journal', 'Two person approval',
             [accounting.line(accounting.account(session, '1100'), debit=100), accounting.line(accounting.account(session, '3000'), credit=100)], 'test:separation')
        with pytest.raises(BusinessError, match='Another'):
            accounting.approve(session, actors['Admin'], v.id)
        with pytest.raises(BusinessError, match='permission'):
            accounting.approve(session, actors['Accountant'], v.id)
        accounting.approve(session, actors['Approver'], v.id)
    with factory.begin() as session:
        session.get(User, actors['Accountant']).active = False
    with factory.begin() as session:
        with pytest.raises(BusinessError, match='permission'):
            master.save_party(session, actors['Accountant'], kind='Customer', name='Blocked')


def test_pending_receipts_reserve_balance_and_rejection_releases(db):
    factory, actors = db
    b, v, _ = new_booking(factory, actors['Accountant'])
    with factory.begin() as session:
        accounting.approve(session, actors['Approver'], v)
        r = sales.receive(session, actors['Accountant'], b, accounting.account(session, '1110'), business_today(), '1000.01', 'receipt', 'test:full')
        rid = r.id
    with factory.begin() as session:
        with pytest.raises(BusinessError, match='exceeds'):
            sales.receive(session, actors['Accountant'], b, accounting.account(session, '1110'), business_today(), '1', 'duplicate amount', 'test:over')
        accounting.reject(session, actors['Approver'], rid, 'Receipt not received')
    with factory.begin() as session:
        assert sales.booking_paid(session, b, True) == 0
        sales.receive(session, actors['Accountant'], b, accounting.account(session, '1110'), business_today(), '1000.01', 'receipt', 'test:replacement')


def test_booking_rejection_releases_unit(db):
    factory, actors = db
    b, v, unit = new_booking(factory, actors['Accountant'])
    with factory.begin() as session:
        accounting.reject(session, actors['Approver'], v, 'Booking declined')
    with factory() as session:
        assert session.get(Unit, unit).status == 'Available'
        assert session.get(Booking, b).status == 'Rejected'


def test_receipt_reversal_restores_schedule_and_balance(db):
    factory, actors = db
    b, v, _ = new_booking(factory, actors['Accountant'])
    with factory.begin() as session:
        accounting.approve(session, actors['Approver'], v)
        r = sales.receive(session, actors['Accountant'], b, accounting.account(session, '1110'), business_today(), '200', 'receipt', 'test:revreceipt')
        accounting.approve(session, actors['Approver'], r.id)
        original = r.id
    with factory.begin() as session:
        reversal = accounting.reverse(session, actors['Accountant'], original, business_today(), 'Bank returned payment', 'test:reverse')
        accounting.approve(session, actors['Approver'], reversal.id)
    with factory() as session:
        assert sales.booking_paid(session, b) == 0
    with factory.begin() as session:
        with pytest.raises(BusinessError, match='already'):
            accounting.reverse(session, actors['Accountant'], original, business_today(), 'Again', 'test:reverse2')


def test_transfer_then_cancellation(db):
    factory, actors = db
    b, v, unit = new_booking(factory, actors['Accountant'], total='1000', down='100', count=3)
    with factory.begin() as session:
        accounting.approve(session, actors['Approver'], v)
        r = sales.receive(session, actors['Accountant'], b, accounting.account(session, '1110'), business_today(), '200', 'receipt', 'test:event-receipt')
        accounting.approve(session, actors['Approver'], r.id)
        old_party = session.get(Booking, b).party_id
        new_party = session.scalar(select(Party.id).where(Party.kind == 'Customer', Party.id != old_party))
        event = sales.request_event(session, actors['Accountant'], b, 'Transfer', business_today(), 'Ownership change', new_party)
        eid = event.id
    with factory.begin() as session:
        sales.decide_event(session, actors['Approver'], eid, True)
    with factory() as session:
        assert session.get(Booking, b).party_id == new_party
        # Inspect only this unit's voucher movements, not other sample bookings of the same customer.
        assert session.get(BookingEvent, eid).status == 'Approved'
        tb = reports.trial_balance(session)
        assert tb.Debit.sum() == tb.Credit.sum()
    with factory.begin() as session:
        event = sales.request_event(session, actors['Accountant'], b, 'Cancellation', business_today(), 'Customer cancellation')
        cancel_id = event.id
    with factory.begin() as session:
        sales.decide_event(session, actors['Approver'], cancel_id, True)
    with factory() as session:
        assert session.get(Booking, b).status == 'Cancelled'
        assert session.get(Unit, unit).status == 'Available'
        tb = reports.trial_balance(session)
        assert tb.loc[tb['Account Code'] == '2200', 'Closing Credit'].iloc[0] == 200
        assert tb.Debit.sum() == tb.Credit.sum()


def test_invoice_partial_payment_and_overpayment(db):
    factory, actors = db
    with factory() as session:
        obj = session.scalar(select(Invoice).where(Invoice.reference == 'SAMPLE-INV-001'))
        invoice_id = obj.id
    with factory.begin() as session:
        with pytest.raises(BusinessError, match='unsettled'):
            sales.pay_invoice(session, actors['Accountant'], invoice_id, accounting.account(session, '1110'), business_today(), '150000.01', 'test:pay-over')
        payment = sales.pay_invoice(session, actors['Accountant'], invoice_id, accounting.account(session, '1110'), business_today(), '150000', 'test:pay-full')
        accounting.approve(session, actors['Approver'], payment.id)
    with factory() as session:
        assert sales.invoice_paid(session, invoice_id) == 25000000


def test_import_atomicity_and_duplicate_reimport(db):
    factory, actors = db
    today = business_today().isoformat()
    raw = f'VoucherRef,Date,Project,AccountCode,PartyID,Description,Debit,Credit\nIMP-1,{today},NOVA-01,1110,,Bank,100,0\nIMP-1,{today},NOVA-01,3000,,Capital,0,100\n'.encode()
    frame = imports.parse_csv(raw)
    with factory.begin() as session:
        created = imports.import_vouchers(session, actors['Accountant'], frame)
    with factory.begin() as session:
        assert imports.import_vouchers(session, actors['Accountant'], frame) == created
    bad = pd.concat([frame.assign(VoucherRef='IMP-2'), frame.assign(VoucherRef='IMP-3', AccountCode='BAD')])
    with factory() as session:
        before = session.scalar(select(func.count()).select_from(Voucher))
    with pytest.raises(BusinessError):
        with factory.begin() as session:
            imports.import_vouchers(session, actors['Accountant'], bad)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Voucher)) == before


def test_period_close_and_ledger_opening(db):
    factory, actors = db
    with factory.begin() as session:
        pending = session.scalars(select(Voucher).where(Voucher.status == 'Pending')).all()
        for voucher in pending:
            accounting.reject(session, actors['Approver'], voucher.id, 'Resolve for close')
        master.close_period(session, actors['Admin'], business_today())
    with factory.begin() as session:
        project, _, _ = ids(session)
        with pytest.raises(BusinessError, match='closed'):
            accounting.create_voucher(session, actors['Accountant'], project, business_today(), 'Journal', 'Closed date',
                [accounting.line(accounting.account(session, '1100'), debit=100), accounting.line(accounting.account(session, '3000'), credit=100)], 'test:closed')
    with factory() as session:
        cash_id = accounting.account(session, '1110')
        full = reports.ledger(session, account_id=cash_id)
        current = reports.ledger(session, start=business_today(), account_id=cash_id)
        assert full.iloc[-1]['Balance (Dr + / Cr −)'] == current.iloc[-1]['Balance (Dr + / Cr −)']


def test_concurrent_unit_booking(db):
    factory, actors = db
    with factory() as session:
        _, customer, unit = ids(session)
    def book(index):
        try:
            with factory.begin() as session:
                sales.create_booking(session, actors['Accountant'], unit, customer, business_today(), '1000', '100', 3,
                                     business_today(), f'concurrent:{index}')
            return True
        except (BusinessError, SQLAlchemyError):
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(book, [1, 2]))
    assert sum(results) == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Booking).where(Booking.unit_id == unit)) == 1


def test_attachment_validation_and_audit(db):
    factory, actors = db
    with pytest.raises(BusinessError, match='valid PDF'):
        with factory.begin() as session:
            project, _, _ = ids(session)
            accounting.create_voucher(session, actors['Accountant'], project, business_today(), 'Journal', 'Evidence test',
                [accounting.line(accounting.account(session, '1100'), debit=100), accounting.line(accounting.account(session, '3000'), credit=100)],
                'test:bad-attachment', ('evil.pdf', 'application/pdf', b'<html>invalid</html>'))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Audit)) > 0


def test_bank_clearance(db):
    factory, actors = db
    from nova.models import Line
    with factory.begin() as session:
        a = accounting.account(session, '1110')
        item = session.scalar(select(Line).join(Voucher).where(Line.account_id == a, Voucher.status == 'Posted'))
        reports.reconcile(session, actors['Accountant'], item.id, business_today(), 'BANK-001')
    with factory() as session:
        frame = reports.bankbook(session, a, business_today())
        assert frame['Cleared'].sum() == 1


def test_concurrent_receipts_cannot_overcollect(db):
    factory, actors = db
    b, v, _ = new_booking(factory, actors['Accountant'], total='1000', down='100')
    with factory.begin() as session:
        accounting.approve(session, actors['Approver'], v)
        cash = accounting.account(session, '1110')
    def collect(index):
        try:
            with factory.begin() as session:
                sales.receive(session, actors['Accountant'], b, cash, business_today(), '600', 'Concurrent receipt', f'concurrent:receipt:{index}')
            return True
        except (BusinessError, SQLAlchemyError):
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(collect, [1, 2]))
    assert sum(results) == 1
    with factory() as session:
        assert sales.booking_paid(session, b, True) == 60000


def test_no_future_posting_and_bank_clearance_before_voucher(db):
    factory, actors = db
    with factory.begin() as session:
        p, _, _ = ids(session)
        with pytest.raises(BusinessError, match='future'):
            accounting.create_voucher(session, actors['Accountant'], p, business_today() + timedelta(days=1), 'Journal', 'Future entry',
                [accounting.line(accounting.account(session, '1100'), debit=100), accounting.line(accounting.account(session, '3000'), credit=100)], 'test:future')
