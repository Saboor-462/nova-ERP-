from datetime import date
import pandas as pd
from sqlalchemy import select
from nova.models import Account, Allocation, Booking, Clearance, Installment, Invoice, Line, Party, Project, Unit, Voucher
from nova.services.common import BusinessError, business_today, require, rupees
from nova.services.sales import effective_vouchers

# Report functions compute in integer paisa; rupees are produced only for display/export (paisa=False).
MONEY_COLUMNS = {'Opening Debit', 'Opening Credit', 'Debit', 'Credit', 'Closing Debit', 'Closing Credit', 'Amount', 'Paid',
                 'Outstanding', 'Inflow', 'Outflow', 'Balance (Dr + / Cr −)', 'Net Expense', 'List Price',
                 'Accrued Commission', 'Commission Paid', 'Down Payment Scheduled', 'Down Payment Received', 'Down Payment Due',
                 'Installment Amount', 'Installments Received', 'Installments Due', 'Total Price', 'Total Received',
                 'Booked Sales', 'Booking Collections', 'Receivables', 'Payables', 'Cash & Bank', 'Revenue', 'Expenses', 'Cash Inflow', 'Cash Outflow'}


def to_rupees(frame):
    return frame.assign(**{column: frame[column].map(rupees) for column in frame.columns if column in MONEY_COLUMNS})


def _present(frame, paisa):
    return frame if paisa else to_rupees(frame)


def entries(session, project_id=None, start=None, end=None, account_id=None, party_id=None):
    query = select(Line, Voucher, Account).join(Voucher, Line.voucher_id == Voucher.id).join(Account, Line.account_id == Account.id)
    query = query.where(Voucher.status == 'Posted')
    if project_id:
        query = query.where(Voucher.project_id == project_id)
    if start:
        query = query.where(Voucher.date >= start)
    if end:
        query = query.where(Voucher.date <= end)
    if account_id:
        query = query.where(Line.account_id == account_id)
    if party_id:
        query = query.where(Line.party_id == party_id)
    return session.execute(query.order_by(Voucher.date, Voucher.created_at, Voucher.number, Line.id)).all()


def trial_balance(session, project_id=None, start=None, end=None, paisa=False):
    accounts = session.scalars(select(Account).where(Account.is_group == False).order_by(Account.code)).all()
    totals = {a.id: {'opening': 0, 'debit': 0, 'credit': 0} for a in accounts}
    for entry, voucher, _ in entries(session, project_id=project_id, end=end):
        target = totals[entry.account_id]
        if start and voucher.date < start:
            target['opening'] += entry.debit - entry.credit
        else:
            target['debit'] += entry.debit
            target['credit'] += entry.credit
    rows = []
    for a in accounts:
        t = totals[a.id]
        closing = t['opening'] + t['debit'] - t['credit']
        rows.append({'Account Code': a.code, 'Account': a.name, 'Type': a.kind,
                     'Opening Debit': max(t['opening'], 0), 'Opening Credit': max(-t['opening'], 0),
                     'Debit': t['debit'], 'Credit': t['credit'],
                     'Closing Debit': max(closing, 0), 'Closing Credit': max(-closing, 0)})
    return _present(pd.DataFrame(rows, columns=['Account Code', 'Account', 'Type', 'Opening Debit', 'Opening Credit', 'Debit',
                                                'Credit', 'Closing Debit', 'Closing Credit']), paisa)


def ledger(session, project_id=None, start=None, end=None, account_id=None, party_id=None, paisa=False):
    parties = {p.id: p.name for p in session.scalars(select(Party)).all()}
    projects = {p.id: p.name for p in session.scalars(select(Project)).all()}
    balance, rows = 0, []
    opening = 0
    for item, v, a in entries(session, project_id, None, end, account_id, party_id):
        if start and v.date < start:
            opening += item.debit - item.credit
    balance = opening
    rows.append({'Date': '', 'Voucher': 'Opening balance', 'Voucher ID': '', 'Project': '', 'Account': '', 'Party': '',
                 'Description': '', 'Debit': 0, 'Credit': 0, 'Balance (Dr + / Cr −)': balance})
    for item, v, a in entries(session, project_id, start, end, account_id, party_id):
        balance += item.debit - item.credit
        rows.append({'Date': v.date.isoformat(), 'Voucher': v.number, 'Voucher ID': v.id, 'Project': projects[v.project_id],
                     'Account': a.name, 'Party': parties.get(item.party_id, ''), 'Description': item.description or v.description,
                     'Debit': item.debit, 'Credit': item.credit, 'Balance (Dr + / Cr −)': balance})
    return _present(pd.DataFrame(rows), paisa)


def financials(session, project_id=None, start=None, end=None, paisa=False):
    tb = trial_balance(session, project_id, None, end, paisa=True)
    period = trial_balance(session, project_id, start, end, paisa=True)
    profit_rows = []
    for _, a in period.iterrows():
        if a['Type'] in ('Income', 'Expense'):
            profit_rows.append({'Type': a['Type'], 'Account Code': a['Account Code'], 'Account': a['Account'],
                                'Amount': int(a['Credit'] - a['Debit'] if a['Type'] == 'Income' else a['Debit'] - a['Credit'])})
    columns = ['Type', 'Account Code', 'Account', 'Amount']
    pnl = pd.DataFrame(profit_rows, columns=columns)
    bs_rows = []
    earnings = 0
    for _, a in tb.iterrows():
        signed = int(a['Closing Debit'] - a['Closing Credit'])
        if a['Type'] in ('Income', 'Expense'):
            earnings -= signed
        else:
            bs_rows.append({'Type': a['Type'], 'Account Code': a['Account Code'], 'Account': a['Account'],
                            'Amount': signed if a['Type'] == 'Asset' else -signed})
    bs_rows.append({'Type': 'Equity', 'Account Code': '', 'Account': 'Accumulated earnings (computed)', 'Amount': earnings})
    return _present(pd.DataFrame(bs_rows, columns=columns), paisa), _present(pnl, paisa)


def installments(session, project_id=None, end=None, paisa=False):
    asof = end or business_today()
    query = select(Installment, Booking, Unit, Party, Project).join(Booking, Installment.booking_id == Booking.id)
    query = query.join(Unit, Booking.unit_id == Unit.id).join(Party, Booking.party_id == Party.id).join(Project, Unit.project_id == Project.id)
    query = query.join(Voucher, Booking.voucher_id == Voucher.id).where(Booking.status == 'Active', Voucher.status == 'Posted', Booking.date <= asof)
    if project_id:
        query = query.where(Unit.project_id == project_id)
    paid_rows = session.execute(select(Allocation.installment_id, Allocation.amount)
                                .where(Allocation.voucher_id.in_(effective_vouchers(session, through=asof)))).all()
    totals = {}
    for identity, value in paid_rows:
        totals[identity] = totals.get(identity, 0) + value
    rows = []
    for inst, booking, unit, party, project in session.execute(query.order_by(Installment.due, Installment.sequence)).all():
        paid = totals.get(inst.id, 0)
        outstanding = inst.amount - paid
        rows.append({'Project': project.name, 'Booking': booking.number, 'Customer': party.name, 'Unit': unit.number,
                     'Installment': 'Down payment' if inst.sequence == 0 else str(inst.sequence), 'Due Date': inst.due.isoformat(),
                     'Amount': inst.amount, 'Paid': paid, 'Outstanding': outstanding,
                     'Overdue Days': max(0, (asof - inst.due).days) if outstanding else 0,
                     'Status': 'Paid' if outstanding == 0 else 'Overdue' if inst.due < asof else 'Due'})
    return _present(pd.DataFrame(rows, columns=['Project', 'Booking', 'Customer', 'Unit', 'Installment', 'Due Date', 'Amount', 'Paid',
                                                'Outstanding', 'Overdue Days', 'Status']), paisa)


def invoice_balances(session, project_id=None, end=None, paisa=False, voucher_status='Posted'):
    """Approved, active invoices by default. voucher_status='Pending' lists invoices awaiting approval (nothing settled)."""
    from nova.models import InvoicePayment
    asof = end or business_today()
    paid = {}
    for identity, amount in session.execute(select(InvoicePayment.invoice_id, InvoicePayment.amount)
                                            .where(InvoicePayment.voucher_id.in_(effective_vouchers(session, through=asof)))).all():
        paid[identity] = paid.get(identity, 0) + amount
    query = (select(Invoice, Party, Voucher).join(Party, Invoice.party_id == Party.id).join(Voucher, Invoice.voucher_id == Voucher.id)
             .where(Invoice.date <= asof, Invoice.status == 'Active', Voucher.status == voucher_status))
    if project_id:
        query = query.where(Invoice.project_id == project_id)
    rows = []
    for obj, party, voucher in session.execute(query.order_by(Invoice.date)).all():
        settled = paid.get(obj.id, 0)
        rows.append({'Invoice ID': obj.id, 'Reference': obj.reference, 'Type': obj.kind, 'Party': party.name,
                     'Date': obj.date.isoformat(), 'Due Date': obj.due.isoformat(), 'Amount': obj.amount,
                     'Paid': settled, 'Outstanding': obj.amount - settled, 'Voucher Status': voucher.status})
    return _present(pd.DataFrame(rows, columns=['Invoice ID', 'Reference', 'Type', 'Party', 'Date', 'Due Date', 'Amount', 'Paid',
                                                'Outstanding', 'Voucher Status']), paisa)


def cashflow(session, project_id=None, start=None, end=None, paisa=False):
    rows = []
    for item, voucher, account in entries(session, project_id, start, end):
        if account.is_cash:
            rows.append({'Date': voucher.date.isoformat(), 'Voucher': voucher.number, 'Account': account.name,
                         'Description': voucher.description, 'Inflow': item.debit, 'Outflow': item.credit})
    return _present(pd.DataFrame(rows, columns=['Date', 'Voucher', 'Account', 'Description', 'Inflow', 'Outflow']), paisa)


def reconcile(session, actor, line_id, cleared_on, reference):
    from nova.services.common import audit, check_date, lock
    require(session, actor, 'entry')
    item = lock(session, Line, line_id)
    voucher = session.get(Voucher, item.voucher_id)
    a = session.get(Account, item.account_id)
    check_date(session, cleared_on)
    if not a.is_cash or voucher.status != 'Posted' or cleared_on < voucher.date:
        raise BusinessError('Select a posted cash/bank entry and a clearance date on or after it.')
    obj = session.scalar(select(Clearance).where(Clearance.line_id == line_id))
    if not obj:
        obj = Clearance(line_id=line_id, date=cleared_on, reference=reference)
        session.add(obj)
    else:
        obj.date, obj.reference = cleared_on, reference
    audit(session, actor, 'reconcile', obj, {'line': line_id, 'reference': reference, 'date': cleared_on})


def bankbook(session, account_id, end, paisa=False):
    clearances = {c.line_id: c for c in session.scalars(select(Clearance)).all()}
    rows = []
    for item, v, a in entries(session, end=end, account_id=account_id):
        clearance = clearances.get(item.id)
        cleared = bool(clearance and clearance.date <= end)
        rows.append({'Line ID': item.id, 'Date': v.date.isoformat(), 'Voucher': v.number, 'Description': v.description,
                     'Debit': item.debit, 'Credit': item.credit, 'Cleared': cleared,
                     'Clearance Date': clearance.date.isoformat() if clearance else '', 'Reference': clearance.reference if clearance else ''})
    return _present(pd.DataFrame(rows), paisa)
