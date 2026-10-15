"""Record controls preserve identifiers and posted history; no cascading financial deletion."""
from sqlalchemy import delete, func, select
from nova.models import (Account, Allocation, Base, Booking, BookingEvent, Credential, FinancialYear, Installment,
                         Invoice, InvoicePayment, Lead, Line, LoginSession, Party, Project, RetiredCode, Unit, User, Voucher)
from nova.services import accounting
from nova.services.common import BusinessError, add_months, audit, business_today, check_date, existing, lock, money, require


def ensure_account_groups(session):
    specifications = [('1001', 'Current assets', 'Asset', '100', True), ('1002', 'Non-current assets', 'Asset', '100', True),
                      ('201', 'Current liabilities', 'Liability', '200', True), ('202', 'Non-current liabilities', 'Liability', '200', True),
                      ('1400', 'Furniture and fixtures', 'Asset', '1002', False), ('1500', 'Property, plant and equipment', 'Asset', '1002', False)]
    for code, name, kind, parent_code, group in specifications:
        if not session.scalar(select(Account.id).where(Account.code == code)):
            parent = session.scalar(select(Account).where(Account.code == parent_code))
            if parent:
                session.add(Account(code=code, name=name, kind=kind, parent_id=parent.id, is_group=group))
                session.flush()
    # Move only original direct-root accounts. Custom hierarchies are left intact.
    for kind, root_code, group_code in [('Asset', '100', '1001'), ('Liability', '200', '201')]:
        root = session.scalar(select(Account).where(Account.code == root_code))
        target = session.scalar(select(Account).where(Account.code == group_code))
        if root and target:
            for a in session.scalars(select(Account).where(Account.parent_id == root.id, Account.is_group == False)).all():
                a.parent_id = target.id


def delete_master(session, actor, model, record_id):
    if model not in (Project, Party, Unit, Account, Lead, FinancialYear):
        raise BusinessError('This record uses an accounting cancellation or user-deactivation workflow.')
    require(session, actor, 'users' if model is FinancialYear else 'master')
    obj = lock(session, model, record_id)
    if model is Account and obj.code in {'100', '1001', '1002', '1100', '1110', '1200', '1300', '200', '201', '202',
                                        '2000', '2100', '2200', '2300', '300', '3000', '400', '4000', '500', '5000', '5100', '5200'}:
        raise BusinessError('A core accounting account cannot be deleted.')
    if model is FinancialYear and (obj.audit_status == 'Audited' or session.scalar(select(Voucher.id).where(Voucher.date.between(obj.starts, obj.ends)))):
        raise BusinessError('An audited year or a year containing transactions cannot be deleted.')
    for table in Base.metadata.sorted_tables:
        for foreign_key in table.foreign_keys:
            if foreign_key.column.table.name == model.__tablename__:
                count = session.scalar(select(func.count()).select_from(table).where(foreign_key.parent == record_id))
                if count:
                    raise BusinessError(f'This record is used by {count} record(s) in {table.name}. Preserve it and use the linked workflow.')
    detail = {c.name: getattr(obj, c.name) for c in model.__table__.columns}
    audit(session, actor, 'delete_unused', obj, detail)
    if model is Account:
        session.add(RetiredCode(id='account:' + obj.code))
    session.delete(obj)


def edit_account(session, actor, record_id, name, parent_id, active):
    require(session, actor, 'master')
    obj = lock(session, Account, record_id)
    if not name.strip():
        raise BusinessError('Account name is required.')
    if parent_id:
        parent = existing(session, Account, parent_id)
        if parent.kind != obj.kind or not parent.is_group:
            raise BusinessError('Parent must be a group of the same account type.')
        seen = {obj.id}
        while parent:
            if parent.id in seen:
                raise BusinessError('An account hierarchy cannot contain a cycle.')
            seen.add(parent.id)
            parent = session.get(Account, parent.parent_id) if parent.parent_id else None
    if not active and obj.code in accounting.CONTROL_ACCOUNTS:
        raise BusinessError('Core control accounts must remain active.')
    before = {'name': obj.name, 'parent_id': obj.parent_id, 'active': obj.active}
    obj.name, obj.parent_id, obj.active = name.strip(), parent_id, bool(active)
    audit(session, actor, 'edit_account', obj, {'before': before, 'after': {'name': name, 'parent_id': parent_id, 'active': active}})


def editable_voucher(session, actor, voucher_id):
    user = require(session, actor, 'entry')
    v = lock(session, Voucher, voucher_id)
    if v.status != 'Pending':
        raise BusinessError('Posted/rejected vouchers are retained. Use an approved reversal or correction workflow.')
    if v.created_by != actor and user.role != 'Admin':
        raise BusinessError('Only the creator or an administrator can edit/cancel a pending voucher.')
    check_date(session, v.date)
    return v


def replace_lines(session, v, rows):
    accounting.validate_lines(session, rows, v.kind)
    before = [dict(account_id=l.account_id, party_id=l.party_id, description=l.description, debit=l.debit, credit=l.credit)
              for l in session.scalars(select(Line).where(Line.voucher_id == v.id)).all()]
    session.execute(delete(Line).where(Line.voucher_id == v.id))
    for row in rows:
        session.add(Line(voucher_id=v.id, **row))
    return before


def edit_voucher(session, actor, voucher_id, on, description, rows, payment_mode='', payment_type=''):
    v = editable_voucher(session, actor, voucher_id)
    if v.kind not in accounting.MANUAL_KINDS:
        raise BusinessError('Use the linked invoice/booking form to edit this voucher.')
    check_date(session, on)
    if not description.strip():
        raise BusinessError('Description is required.')
    before = replace_lines(session, v, rows)
    v.date, v.description, v.payment_mode, v.payment_type = on, description.strip(), payment_mode, payment_type
    audit(session, actor, 'edit_pending_voucher', v, {'before': before, 'after': rows})


def cancel_pending(session, actor, voucher_id, reason):
    v = editable_voucher(session, actor, voucher_id)
    if not reason.strip():
        raise BusinessError('A cancellation reason is required.')
    v.status = 'Rejected'
    b = session.scalar(select(Booking).where(Booking.voucher_id == v.id))
    if b:
        b.status = 'Rejected'
        lock(session, Unit, b.unit_id).status = 'Available'
    i = session.scalar(select(Invoice).where(Invoice.voucher_id == v.id))
    if i:
        i.status = 'Rejected'
    audit(session, actor, 'cancel_pending', v, {'reason': reason, 'number': v.number})


def edit_invoice(session, actor, invoice_id, reference, on, due, amount, description, items=None):
    obj = lock(session, Invoice, invoice_id)
    v = editable_voucher(session, actor, obj.voucher_id)
    check_date(session, on)
    amount = money(amount)
    if amount <= 0 or due < on or not reference.strip() or not description.strip():
        raise BusinessError('Positive amount, reference, description, and valid dates are required.')
    old = {'amount': obj.amount, 'reference': obj.reference, 'date': obj.date, 'due': obj.due, 'description': obj.description}
    rows = session.scalars(select(Line).where(Line.voucher_id == v.id)).all()
    new = [accounting.line(l.account_id, amount if l.debit else 0, amount if l.credit else 0, l.party_id, l.description) for l in rows]
    replace_lines(session, v, new)
    obj.reference, obj.date, obj.due, obj.amount, obj.description = reference.strip(), on, due, amount, description.strip()
    from nova.models import InvoiceItem
    if items is not None:
        validate_invoice_items(items, amount)
        session.execute(delete(InvoiceItem).where(InvoiceItem.invoice_id == obj.id))
        for n, row in enumerate(items, 1):
            session.add(InvoiceItem(invoice_id=obj.id, sequence=n, **row))
    else:
        current = session.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == obj.id)).all()
        if current and sum(i.amount for i in current) != amount:
            raise BusinessError('Update the invoice items to match the edited invoice total.')
    v.date, v.description = on, description.strip()
    audit(session, actor, 'edit_pending_invoice', obj, {'before': old, 'new_amount': amount})


def validate_invoice_items(items, total):
    if len(items) > 100:
        raise BusinessError('An invoice supports up to 100 item rows.')
    for row in items:
        if not str(row['description']).strip() or not isinstance(row['amount'], int) or row['amount'] <= 0:
            raise BusinessError('Each invoice item needs a description and positive amount.')
    if items and sum(row['amount'] for row in items) != total:
        raise BusinessError('Invoice item amounts must equal the invoice total.')


def edit_booking(session, actor, booking_id, on, total, down, count, first_due):
    obj = lock(session, Booking, booking_id)
    v = editable_voucher(session, actor, obj.voucher_id)
    check_date(session, on)
    total, down = money(total), money(down)
    if total <= 0 or down > total or not 1 <= count <= 360 or first_due < on or (total > down and total - down < count):
        raise BusinessError('Check price, down payment, installment count, and dates.')
    if session.scalar(select(Allocation.id).join(Installment).where(Installment.booking_id == obj.id)):
        raise BusinessError('A booking with receipts cannot be amended this way.')
    rows = [accounting.line(accounting.account(session, '1200'), debit=total, party_id=obj.party_id),
            accounting.line(accounting.account(session, '2100'), credit=total, party_id=obj.party_id)]
    if obj.commission:
        rows += [accounting.line(accounting.account(session, '5200'), debit=obj.commission),
                 accounting.line(accounting.account(session, '2300'), credit=obj.commission, party_id=obj.dealer_id)]
    replace_lines(session, v, rows)
    before = {'total': obj.total, 'down': obj.down_payment, 'date': obj.date}
    obj.total, obj.down_payment, obj.date, v.date = total, down, on, on
    session.execute(delete(Installment).where(Installment.booking_id == obj.id))
    if down:
        session.add(Installment(booking_id=obj.id, sequence=0, due=on, amount=down))
    if total > down:
        base, remainder = divmod(total - down, count)
        for index in range(count):
            session.add(Installment(booking_id=obj.id, sequence=index + 1, due=add_months(first_due, index), amount=base + (index < remainder)))
    audit(session, actor, 'edit_pending_booking', obj, {'before': before, 'total': total})


def void_invoice(session, actor, invoice_id, on, reason, token):
    from nova.models import InvoiceCorrection
    from nova.services.invoice_corrections import ensure_no_pending_correction, latest_invoice_activity
    from nova.services.sales import invoice_paid
    require(session, actor, 'entry')
    obj = lock(session, Invoice, invoice_id)
    original = lock(session, Voucher, obj.voucher_id)
    ensure_no_pending_correction(session, obj.id)
    if original.status != 'Posted' or obj.status != 'Active' or invoice_paid(session, obj.id, True):
        raise BusinessError('Only an approved unsettled invoice can be cancelled. Reverse its settlements first if applicable.')
    check_date(session, on)
    if on < max(original.date, latest_invoice_activity(session, obj)) or not reason.strip():
        raise BusinessError('Provide a reason and a cancellation date on or after the invoice and its latest correction or settlement activity.')
    if session.scalar(select(Voucher.id).where(Voucher.reversal_of == original.id, Voucher.status != 'Rejected')):
        raise BusinessError('A cancellation/reversal already exists.')
    correction_vouchers = select(InvoiceCorrection.voucher_id).where(InvoiceCorrection.invoice_id == obj.id,
                                                                    InvoiceCorrection.status == 'Approved',
                                                                    InvoiceCorrection.voucher_id.is_not(None))
    rows = session.scalars(select(Line).join(Voucher, Line.voucher_id == Voucher.id)
                           .where(Voucher.status == 'Posted',
                                  (Line.voucher_id == original.id) | Line.voucher_id.in_(correction_vouchers))).all()
    balances = {}
    for row in rows:
        key = (row.account_id, row.party_id)
        balances[key] = balances.get(key, 0) + row.debit - row.credit
    reversed_rows = [accounting.line(account_id, max(-balance, 0), max(balance, 0), party_id, reason)
                     for (account_id, party_id), balance in balances.items() if balance]
    v = accounting.create_voucher(session, actor, obj.project_id, on, 'Reversal', reason,
                                  reversed_rows, token)
    v.reversal_of = original.id
    audit(session, actor, 'invoice_cancellation_requested', obj, {'voucher': v.number, 'reason': reason})
    return v


def edit_event(session, actor, event_id, on, reason, new_party_id=None, cancel=False):
    user = require(session, actor, 'entry')
    obj = lock(session, BookingEvent, event_id)
    if obj.status != 'Pending' or (obj.created_by != actor and user.role != 'Admin'):
        raise BusinessError('Only your own pending request, or one reviewed by Admin, can be edited/cancelled.')
    check_date(session, on)
    booking = lock(session, Booking, obj.booking_id)
    latest_receipt = session.scalar(select(func.max(Voucher.date)).join(Allocation, Allocation.voucher_id == Voucher.id)
                                    .join(Installment, Allocation.installment_id == Installment.id)
                                    .where(Installment.booking_id == booking.id, Voucher.status == 'Posted'))
    if latest_receipt and on < latest_receipt:
        raise BusinessError('The request date cannot predate the last approved receipt.')
    if on < booking.date or not reason.strip():
        raise BusinessError('Reason and date on or after booking are required.')
    if obj.kind == 'Transfer' and not cancel:
        p = existing(session, Party, new_party_id)
        if p.kind != 'Customer' or p.id == booking.party_id:
            raise BusinessError('Choose a different customer.')
        obj.new_party_id = p.id
    obj.date, obj.reason = on, reason
    if cancel:
        obj.status = 'Rejected'
    audit(session, actor, 'cancel_request' if cancel else 'edit_request', obj, {'date': on, 'reason': reason})


def save_year(session, actor, name, starts, ends, record_id=None, status='Not audited', auditor='', audited_on=None, notes=''):
    require(session, actor, 'users')
    if not name.strip() or ends < starts:
        raise BusinessError('Year name and a valid date range are required.')
    overlaps = select(FinancialYear.id).where(FinancialYear.starts <= ends, FinancialYear.ends >= starts)
    if record_id:
        overlaps = overlaps.where(FinancialYear.id != record_id)
    if session.scalar(overlaps):
        raise BusinessError('Financial years cannot overlap.')
    if status not in ('Not audited', 'In review', 'Audited'):
        raise BusinessError('Choose a valid audit status.')
    if status == 'Audited':
        if not auditor.strip() or not audited_on or audited_on > business_today() or ends > business_today():
            raise BusinessError('Audited status requires a completed year, auditor name, and valid audit date.')
        if session.scalar(select(Voucher.id).where(Voucher.date.between(starts, ends), Voucher.status == 'Pending')) or session.scalar(select(BookingEvent.id).where(BookingEvent.date.between(starts, ends), BookingEvent.status == 'Pending')):
            raise BusinessError('Resolve pending entries/requests in this year before recording it as audited.')
        from nova.models import InvoiceCorrection
        if session.scalar(select(InvoiceCorrection.id).where(InvoiceCorrection.effective_on.between(starts, ends),
                                                            InvoiceCorrection.status == 'Pending')):
            raise BusinessError('Resolve pending invoice corrections in this year before recording it as audited.')
    obj = lock(session, FinancialYear, record_id) if record_id else FinancialYear(name=name, starts=starts, ends=ends)
    if record_id and (starts != obj.starts or ends != obj.ends) and session.scalar(select(Voucher.id).where(Voucher.date.between(obj.starts, obj.ends))):
        raise BusinessError('The date range of a year containing transactions cannot change.')
    obj.name, obj.starts, obj.ends, obj.audit_status, obj.auditor, obj.audited_on, obj.notes = name.strip(), starts, ends, status, auditor.strip(), audited_on, notes
    session.add(obj)
    audit(session, actor, 'save_financial_year', obj, {'name': name, 'audit_status': status, 'auditor': auditor})
    return obj


def edit_pending_payment(session, actor, voucher_id, on, amount, description):
    from nova.services.sales import booking_paid, installment_paid, invoice_paid
    v = editable_voucher(session, actor, voucher_id)
    check_date(session, on)
    amount = money(amount)
    if amount <= 0 or not description.strip():
        raise BusinessError('Positive amount and description are required.')
    lines = session.scalars(select(Line).where(Line.voucher_id == v.id)).all()
    if v.kind == 'Receipt':
        allocations = session.scalars(select(Allocation).where(Allocation.voucher_id == v.id)).all()
        if not allocations:
            raise BusinessError('Receipt has no linked booking allocation.')
        installment = existing(session, Installment, allocations[0].installment_id)
        booking = lock(session, Booking, installment.booking_id)
        old = sum(a.amount for a in allocations)
        if amount > booking.total - booking_paid(session, booking.id, True) + old or on < booking.date:
            raise BusinessError('Receipt amount or date is outside the booking balance/date range.')
        if session.scalar(select(BookingEvent.id).where(BookingEvent.booking_id == booking.id, BookingEvent.status == 'Pending')):
            raise BusinessError('Resolve the pending ownership request first.')
        session.execute(delete(Allocation).where(Allocation.voucher_id == v.id))
        remaining = amount
        for inst in session.scalars(select(Installment).where(Installment.booking_id == booking.id).order_by(Installment.due, Installment.sequence)).all():
            applied = min(remaining, inst.amount - installment_paid(session, inst.id, True))
            if applied:
                session.add(Allocation(installment_id=inst.id, voucher_id=v.id, amount=applied))
                remaining -= applied
            if remaining == 0:
                break
        if remaining:
            raise BusinessError('Receipt allocation could not be completed.')
    elif v.kind == 'Settlement':
        payment = session.scalar(select(InvoicePayment).where(InvoicePayment.voucher_id == v.id))
        if not payment:
            raise BusinessError('Settlement has no linked invoice.')
        invoice = lock(session, Invoice, payment.invoice_id)
        from nova.services.invoice_corrections import ensure_no_pending_correction, latest_correction_date
        ensure_no_pending_correction(session, invoice.id)
        corrected_on = latest_correction_date(session, invoice.id)
        if corrected_on and on < corrected_on:
            raise BusinessError('Settlement cannot predate the latest approved invoice correction.')
        if amount > invoice.amount - invoice_paid(session, invoice.id, True) + payment.amount or on < invoice.date:
            raise BusinessError('Settlement amount or date is outside the invoice balance/date range.')
        payment.amount = amount
    else:
        raise BusinessError('This voucher uses another linked edit form.')
    replace_lines(session, v, [accounting.line(l.account_id, amount if l.debit else 0, amount if l.credit else 0, l.party_id, l.description) for l in lines])
    v.date, v.description = on, description.strip()
    audit(session, actor, 'edit_pending_payment', v, {'amount': amount, 'date': on})
