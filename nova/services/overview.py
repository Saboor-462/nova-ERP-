from sqlalchemy import func, select
import pandas as pd
from nova.models import Account, Booking, Line, Project, Unit, Voucher
from nova.services import reports, sales


def hierarchy(session, project_id=None, start=None, end=None, balance_sheet=False):
    accounts = session.scalars(select(Account).order_by(Account.code)).all()
    own = {a.id: {'opening': 0, 'debit': 0, 'credit': 0} for a in accounts}
    for l, v, _ in reports.entries(session, project_id, end=end):
        if start and v.date < start and not balance_sheet:
            own[l.account_id]['opening'] += l.debit - l.credit
        else:
            own[l.account_id]['debit'] += l.debit
            own[l.account_id]['credit'] += l.credit
    children = {}
    for a in accounts:
        children.setdefault(a.parent_id, []).append(a)
    totals, visiting = {}, set()
    def aggregate(a):
        if a.id in visiting:
            raise ValueError('Account hierarchy contains a cycle.')
        if a.id in totals:
            return totals[a.id]
        visiting.add(a.id)
        t = dict(own[a.id])
        for child in children.get(a.id, []):
            c = aggregate(child)
            for key in t:
                t[key] += c[key]
        visiting.remove(a.id)
        totals[a.id] = t
        return t
    rows = []
    for a in accounts:
        aggregate(a)
    bs, _ = reports.financials(session, project_id, end=end, paisa=True)
    earnings = int(bs.loc[bs['Account'] == 'Accumulated earnings (computed)', 'Amount'].sum())
    def walk(a, depth):
        if balance_sheet and a.kind not in ('Asset', 'Liability', 'Equity'):
            return
        t = totals[a.id]
        signed = t['opening'] + t['debit'] - t['credit']
        value = signed if a.kind in ('Asset', 'Expense') else -signed
        if balance_sheet and a.kind == 'Equity' and a.parent_id is None:
            value += earnings
        rows.append({'Account Code': a.code, 'Account': ('  ' * depth) + a.name, 'Type': a.kind, 'Level': depth,
                     'Group': a.is_group, 'Opening Debit': max(t['opening'], 0), 'Opening Credit': max(-t['opening'], 0),
                     'Debit': t['debit'], 'Credit': t['credit'], 'Closing Debit': max(signed, 0),
                     'Closing Credit': max(-signed, 0), 'Amount': value})
        for child in children.get(a.id, []):
            walk(child, depth + 1)
        if balance_sheet and a.kind == 'Equity' and a.parent_id is None:
            rows.append({'Account Code': '', 'Account': '  Accumulated earnings', 'Type': 'Equity', 'Level': depth + 1,
                         'Group': False, 'Opening Debit': 0, 'Opening Credit': 0, 'Debit': 0, 'Credit': 0,
                         'Closing Debit': max(-earnings, 0), 'Closing Credit': max(earnings, 0), 'Amount': earnings})
    for a in children.get(None, []):
        walk(a, 0)
    return pd.DataFrame(rows)


def project_summary(session, project_id=None, start=None, end=None):
    query = select(Project)
    if project_id:
        query = query.where(Project.id == project_id)
    rows = []
    for project in session.scalars(query.order_by(Project.number)).all():
        units = session.scalars(select(Unit).where(Unit.project_id == project.id)).all()
        bquery = select(Booking).join(Unit).join(Voucher, Booking.voucher_id == Voucher.id).where(Unit.project_id == project.id,
                          Booking.status == 'Active', Voucher.status == 'Posted')
        if end:
            bquery = bquery.where(Booking.date <= end)
        bookings = session.scalars(bquery).all()
        tb = reports.trial_balance(session, project.id, end=end, paisa=True)
        by_code = {r['Account Code']: int(r['Closing Debit'] - r['Closing Credit']) for _, r in tb.iterrows()}
        _, pnl = reports.financials(session, project.id, start, end, paisa=True)
        cash = reports.cashflow(session, project.id, start, end, paisa=True)
        paid = sum(sales.booking_paid(session, b.id, through=end) for b in bookings)
        cash_accounts = session.scalars(select(Account.code).where(Account.is_cash == True)).all()
        rows.append({'Project Code': project.number, 'Project': project.name, 'Units': len(units), 'Available': sum(u.status == 'Available' for u in units),
           'Reserved / Booked': sum(u.status == 'Booked' for u in units), 'Approved Bookings': len(bookings),
           'Booked Sales': sum(b.total for b in bookings), 'Booking Collections': paid,
           'Receivables': by_code.get('1200', 0), 'Payables': -sum(by_code.get(c, 0) for c in ('2000', '2200', '2300')),
           'Cash & Bank': sum(by_code.get(c, 0) for c in cash_accounts),
           'Revenue': int(pnl.loc[pnl['Type'] == 'Income', 'Amount'].sum()), 'Expenses': int(pnl.loc[pnl['Type'] == 'Expense', 'Amount'].sum()),
           'Cash Inflow': int(cash['Inflow'].sum()) if not cash.empty else 0, 'Cash Outflow': int(cash['Outflow'].sum()) if not cash.empty else 0})
    return pd.DataFrame(rows)


def diagnostics(session, project_id=None, end=None):
    rows = []
    tb = reports.trial_balance(session, project_id, end=end, paisa=True)
    difference = int(tb['Closing Debit'].sum() - tb['Closing Credit'].sum())
    if difference:
        rows.append({'Alert': 'Trial balance mismatch', 'Difference (paisa)': difference, 'Action': 'Inspect posted voucher lines.'})
    bs, _ = reports.financials(session, project_id, end=end, paisa=True)
    difference = int(bs.loc[bs['Type'] == 'Asset', 'Amount'].sum() - bs.loc[bs['Type'].isin(['Liability', 'Equity']), 'Amount'].sum())
    if difference:
        rows.append({'Alert': 'Balance sheet mismatch', 'Difference (paisa)': difference, 'Action': 'Inspect financial account classifications and postings.'})
    expected = int(reports.installments(session, project_id, end, paisa=True)['Outstanding'].sum())
    invoices = reports.invoice_balances(session, project_id, end, paisa=True)
    expected += int(invoices.loc[invoices['Type'] == 'Sale', 'Outstanding'].sum())
    ar = int(tb.loc[tb['Account Code'] == '1200', 'Closing Debit'].sum() - tb.loc[tb['Account Code'] == '1200', 'Closing Credit'].sum())
    if ar != expected:
        rows.append({'Alert': 'Receivable control / schedules mismatch', 'Difference (paisa)': ar - expected,
                     'Action': 'Review legacy or unallocated entries. Historical schedules use current ownership.'})
    query = select(Voucher, func.count(Line.id), func.coalesce(func.sum(Line.debit - Line.credit), 0)).outerjoin(Line).where(Voucher.status == 'Posted')
    if project_id:
        query = query.where(Voucher.project_id == project_id)
    if end:
        query = query.where(Voucher.date <= end)
    for v, count, net in session.execute(query.group_by(Voucher.id)).all():
        if count < 2 or net:
            rows.append({'Alert': 'Invalid posted voucher ' + v.number, 'Difference (paisa)': int(net), 'Action': 'Review the source voucher; do not patch the database directly.'})
    from nova.models import Installment
    bookings = select(Booking).join(Unit).join(Voucher, Booking.voucher_id == Voucher.id).where(Voucher.status == 'Posted', Booking.status == 'Active')
    if project_id:
        bookings = bookings.where(Unit.project_id == project_id)
    for b in session.scalars(bookings).all():
        scheduled = session.scalar(select(func.coalesce(func.sum(Installment.amount), 0)).where(Installment.booking_id == b.id))
        if scheduled != b.total:
            rows.append({'Alert': 'Booking / schedule mismatch ' + b.number, 'Difference (paisa)': scheduled - b.total,
                         'Action': 'Reconcile the agreed price with the installment schedule.'})
        paid = sales.booking_paid(session, b.id, through=end)
        if paid > b.total:
            rows.append({'Alert': 'Booking overcollection ' + b.number, 'Difference (paisa)': paid - b.total,
                         'Action': 'Review allocations and receipt corrections.'})
    return pd.DataFrame(rows)


def dealer_commissions(session, project_id=None, end=None):
    from nova.models import Party
    totals = {}
    for line, voucher, account in reports.entries(session, project_id, end=end):
        if account.code != '2300':
            continue
        party = session.get(Party, line.party_id) if line.party_id else None
        name = party.name if party else 'Unallocated dealer — review required'
        row = totals.setdefault(name, {'Accrued Commission': 0, 'Commission Paid': 0})
        row['Accrued Commission'] += line.credit
        row['Commission Paid'] += line.debit
    return pd.DataFrame([{'Dealer': name, **row, 'Outstanding': row['Accrued Commission'] - row['Commission Paid']}
                         for name, row in totals.items()], columns=['Dealer', 'Accrued Commission', 'Commission Paid', 'Outstanding'])


def installment_summary(frame):
    rows = []
    if frame.empty:
        return pd.DataFrame()
    for keys, group in frame.groupby(['Project', 'Booking', 'Customer', 'Unit'], sort=False):
        down = group[group['Installment'] == 'Down payment']
        inst = group[group['Installment'] != 'Down payment']
        rows.append({**dict(zip(['Project', 'Booking', 'Customer', 'Unit'], keys)),
            'Down Payment Scheduled': int(down['Amount'].sum()), 'Down Payment Received': int(down['Paid'].sum()),
            'Down Payment Due': int(down['Outstanding'].sum()), 'Installment Amount': int(inst['Amount'].sum()),
            'Installments Received': int(inst['Paid'].sum()), 'Installments Due': int(inst['Outstanding'].sum()),
            'Total Price': int(group['Amount'].sum()), 'Total Received': int(group['Paid'].sum()), 'Outstanding': int(group['Outstanding'].sum())})
    return pd.DataFrame(rows)
