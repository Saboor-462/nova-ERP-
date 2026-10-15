from datetime import date
from uuid import uuid4
from nova.services.numbering import next_number
from sqlalchemy import func, select, update
from nova.models import Account, Allocation, Booking, BookingEvent, Installment, Invoice, InvoicePayment, Line, Party, Unit, Voucher
from nova.services.accounting import CONTROL_ACCOUNTS, account, approve, create_voucher, line
from nova.services.common import BusinessError, add_months, audit, check_date, existing, lock, money, require


def effective_vouchers(session, include_pending=False, through=None):
    reversed_ids = select(Voucher.reversal_of).where(Voucher.status == 'Posted', Voucher.reversal_of.is_not(None))
    if through:
        reversed_ids = reversed_ids.where(Voucher.date <= through)
    query = select(Voucher.id).where(Voucher.status.in_(['Posted', 'Pending'] if include_pending else ['Posted']),
                                    Voucher.id.not_in(reversed_ids))
    if through:
        query = query.where(Voucher.date <= through)
    return query


def installment_paid(session, installment_id, include_pending=False, through=None):
    return session.scalar(select(func.coalesce(func.sum(Allocation.amount), 0))
                          .where(Allocation.installment_id == installment_id,
                                 Allocation.voucher_id.in_(effective_vouchers(session, include_pending, through))))


def booking_paid(session, booking_id, include_pending=False, through=None):
    return session.scalar(select(func.coalesce(func.sum(Allocation.amount), 0)).join(Installment)
                          .where(Installment.booking_id == booking_id,
                                 Allocation.voucher_id.in_(effective_vouchers(session, include_pending, through))))


def invoice_paid(session, invoice_id, include_pending=False, through=None):
    return session.scalar(select(func.coalesce(func.sum(InvoicePayment.amount), 0))
                          .where(InvoicePayment.invoice_id == invoice_id,
                                 InvoicePayment.voucher_id.in_(effective_vouchers(session, include_pending, through))))


def create_booking(session, actor, unit_id, party_id, on, total, down_payment, count, first_due,
                   token, dealer_id=None, commission=0):
    require(session, actor, 'entry')
    previous = session.scalar(select(Booking).join(Voucher, Booking.voucher_id == Voucher.id).where(Voucher.token == token))
    if previous:
        return previous
    unit = lock(session, Unit, unit_id)
    customer = existing(session, Party, party_id)
    total, down, commission = money(total), money(down_payment), money(commission)
    if customer.kind != 'Customer' or total <= 0 or down > total:
        raise BusinessError('Choose a customer; price must be positive and down payment cannot exceed it.')
    if count < 1 or count > 360 or first_due < on:
        raise BusinessError('Choose 1–360 installments and a first due date on or after booking.')
    if total > down and total - down < count:
        raise BusinessError('The number of installments exceeds the remaining paisa.')
    if dealer_id and existing(session, Party, dealer_id).kind != 'Dealer':
        raise BusinessError('Select a dealer for the commission.')
    if commission and not dealer_id:
        raise BusinessError('A dealer is required when commission is entered.')
    if unit.status != 'Available':
        raise BusinessError('This unit has already been reserved or booked.')
    # Compare-and-set also protects booking races under SQLite.
    changed = session.execute(update(Unit).where(Unit.id == unit.id, Unit.status == 'Available').values(status='Booked'))
    if changed.rowcount != 1:
        raise BusinessError('Another user has booked this unit. Refresh the list.')
    rows = [line(account(session, '1200'), debit=total, party_id=party_id),
            line(account(session, '2100'), credit=total, party_id=party_id)]
    if commission:
        rows += [line(account(session, '5200'), debit=commission), line(account(session, '2300'), credit=commission, party_id=dealer_id)]
    voucher = create_voucher(session, actor, unit.project_id, on, 'Booking', f'Booking {unit.number}', rows, token)
    obj = Booking(number=next_number(session, 'BK'), unit_id=unit.id, party_id=party_id, dealer_id=dealer_id,
                  date=on, total=total, down_payment=down, commission=commission, voucher_id=voucher.id)
    session.add(obj)
    session.flush()
    if down:
        session.add(Installment(booking_id=obj.id, sequence=0, due=on, amount=down))
    remaining = total - down
    if remaining:
        base, remainder = divmod(remaining, count)
        for i in range(count):
            session.add(Installment(booking_id=obj.id, sequence=i + 1, due=add_months(first_due, i),
                                    amount=base + (1 if i < remainder else 0)))
    audit(session, actor, 'book', obj, {'unit': unit.number, 'total_paisa': total, 'customer': party_id})
    return obj


def check_booking(session, booking_id, on):
    obj = lock(session, Booking, booking_id)
    if obj.status != 'Active' or existing(session, Voucher, obj.voucher_id).status != 'Posted':
        raise BusinessError('The booking must be active and its original voucher approved first.')
    if on < obj.date:
        raise BusinessError('The transaction cannot predate the booking.')
    if session.scalar(select(BookingEvent.id).where(BookingEvent.booking_id == booking_id, BookingEvent.status == 'Pending')):
        raise BusinessError('Resolve the pending transfer/cancellation before recording a receipt.')
    latest = session.scalar(select(func.max(BookingEvent.date)).where(BookingEvent.booking_id == booking_id, BookingEvent.status == 'Approved'))
    if latest and on < latest:
        raise BusinessError('The receipt date cannot predate the latest ownership change.')
    return obj


def receive(session, actor, booking_id, cash_account_id, on, amount, description, token, attachment=None, items=None):
    require(session, actor, 'entry')
    previous = session.scalar(select(Voucher).where(Voucher.token == token))
    if previous:
        return previous
    obj = check_booking(session, booking_id, on)
    cash = existing(session, Account, cash_account_id)
    if not cash.is_cash:
        raise BusinessError('Choose a cash or bank account.')
    amount = money(amount)
    remaining = obj.total - booking_paid(session, obj.id, True)
    if amount <= 0 or amount > remaining:
        raise BusinessError('Receipt exceeds the unallocated balance, including pending receipts, or is zero.')
    unit = existing(session, Unit, obj.unit_id)
    voucher = create_voucher(session, actor, unit.project_id, on, 'Receipt', description,
                              [line(cash.id, debit=amount), line(account(session, '1200'), credit=amount, party_id=obj.party_id)], token, attachment)
    left = amount
    installments = session.scalars(select(Installment).where(Installment.booking_id == obj.id)
                                    .order_by(Installment.due, Installment.sequence).with_for_update()).all()
    for inst in installments:
        available = inst.amount - installment_paid(session, inst.id, True)
        applied = min(left, available)
        if applied:
            session.add(Allocation(installment_id=inst.id, voucher_id=voucher.id, amount=applied))
            left -= applied
        if left == 0:
            break
    if left:
        raise BusinessError('Receipt allocation could not be balanced; refresh and retry.')
    audit(session, actor, 'receipt', obj, {'voucher': voucher.number, 'amount_paisa': amount})
    return voucher


def create_invoice(session, actor, project_id, party_id, kind, reference, on, due, amount, posting_account_id,
                   description, token, attachment=None, items=None):
    require(session, actor, 'entry')
    previous = session.scalar(select(Invoice).join(Voucher, Invoice.voucher_id == Voucher.id).where(Voucher.token == token))
    if previous:
        return previous
    party = existing(session, Party, party_id)
    posting = existing(session, Account, posting_account_id)
    amount = money(amount)
    if amount <= 0 or not reference.strip() or due < on:
        raise BusinessError('Positive amount, invoice reference, and valid due date are required.')
    if posting.code in CONTROL_ACCOUNTS:
        raise BusinessError('Choose an expense, project asset, or income account; control accounts are posted automatically.')
    if session.scalar(select(Invoice.id).where(Invoice.party_id == party_id, Invoice.reference == reference.strip(),
                                               Invoice.kind == kind, Invoice.status == 'Active')):
        raise BusinessError('This party already has an active invoice with this reference. Reject it first to replace it.')
    if kind == 'Purchase':
        if party.kind not in ('Vendor', 'Contractor', 'Landowner') or posting.kind not in ('Expense', 'Asset') or posting.is_cash:
            raise BusinessError('Purchases require a supplier and an expense or non-cash asset account.')
        rows = [line(posting.id, debit=amount), line(account(session, '2000'), credit=amount, party_id=party_id)]
    elif kind == 'Sale':
        if party.kind != 'Customer' or posting.kind != 'Income':
            raise BusinessError('Sales invoices require a customer and an income account.')
        rows = [line(account(session, '1200'), debit=amount, party_id=party_id), line(posting.id, credit=amount)]
    elif kind == 'Dealer':
        if party.kind != 'Dealer' or posting.kind != 'Expense':
            raise BusinessError('Dealer invoices require a dealer and an expense account.')
        rows = [line(posting.id, debit=amount), line(account(session, '2300'), credit=amount, party_id=party_id)]
    else:
        raise BusinessError('Unknown invoice type.')
    voucher = create_voucher(session, actor, project_id, on, f'{kind} Invoice', description, rows, token, attachment)
    obj = Invoice(project_id=project_id, party_id=party_id, kind=kind, reference=reference.strip(), date=on, due=due,
                  amount=amount, description=description, voucher_id=voucher.id)
    session.add(obj)
    if items:
        from nova.services.records import validate_invoice_items
        from nova.models import InvoiceItem
        validate_invoice_items(items, amount)
        session.flush()
        for n, row in enumerate(items, 1):
            session.add(InvoiceItem(invoice_id=obj.id, sequence=n, **row))
    audit(session, actor, 'invoice', obj, {'reference': reference, 'voucher': voucher.number})
    return obj


def pay_invoice(session, actor, invoice_id, cash_account_id, on, amount, token):
    require(session, actor, 'entry')
    previous = session.scalar(select(Voucher).where(Voucher.token == token))
    if previous:
        return previous
    obj = lock(session, Invoice, invoice_id)
    if session.scalar(select(Voucher.id).where(Voucher.reversal_of == obj.voucher_id, Voucher.status != 'Rejected')):
        raise BusinessError('Resolve the pending invoice cancellation before settlement.')
    if obj.status != 'Active' or existing(session, Voucher, obj.voucher_id).status != 'Posted' or on < obj.date:
        raise BusinessError('Approve the invoice first; settlement cannot predate the invoice.')
    from nova.services.invoice_corrections import ensure_no_pending_correction, latest_correction_date
    ensure_no_pending_correction(session, obj.id)
    corrected_on = latest_correction_date(session, obj.id)
    if corrected_on and on < corrected_on:
        raise BusinessError('Settlement cannot predate the latest approved invoice correction.')
    cash = existing(session, Account, cash_account_id)
    if not cash.is_cash:
        raise BusinessError('Select a cash/bank account.')
    amount = money(amount)
    if amount <= 0 or amount > obj.amount - invoice_paid(session, obj.id, True):
        raise BusinessError('Settlement must be positive and cannot exceed the unsettled invoice.')
    if obj.kind == 'Sale':
        rows = [line(cash.id, debit=amount), line(account(session, '1200'), credit=amount, party_id=obj.party_id)]
    else:
        rows = [line(account(session, '2300' if obj.kind == 'Dealer' else '2000'), debit=amount, party_id=obj.party_id),
                line(cash.id, credit=amount)]
    voucher = create_voucher(session, actor, obj.project_id, on, 'Settlement', f'Settlement of {obj.reference}', rows, token)
    session.add(InvoicePayment(invoice_id=obj.id, voucher_id=voucher.id, amount=amount))
    audit(session, actor, 'invoice_settlement', obj, {'voucher': voucher.number, 'amount_paisa': amount})
    return voucher


def request_event(session, actor, booking_id, kind, on, reason, new_party_id=None):
    require(session, actor, 'entry')
    obj = check_booking(session, booking_id, on)
    check_date(session, on)
    if kind not in ('Transfer', 'Cancellation') or not reason.strip():
        raise BusinessError('Valid event type and reason are required.')
    if kind == 'Transfer':
        if not new_party_id or new_party_id == obj.party_id or existing(session, Party, new_party_id).kind != 'Customer':
            raise BusinessError('Choose a different customer for transfer.')
    if booking_paid(session, obj.id, True) != booking_paid(session, obj.id):
        raise BusinessError('Resolve pending receipts before requesting a transfer/cancellation.')
    # A reversal in progress also changes the final refund/receivable position.
    receipt_ids = select(Allocation.voucher_id).join(Installment).where(Installment.booking_id == obj.id)
    if session.scalar(select(Voucher.id).where(Voucher.reversal_of.in_(receipt_ids), Voucher.status == 'Pending')):
        raise BusinessError('Resolve pending receipt reversals first.')
    latest_receipt = session.scalar(select(func.max(Voucher.date)).where(Voucher.id.in_(receipt_ids), Voucher.status == 'Posted'))
    if latest_receipt and on < latest_receipt:
        raise BusinessError('Event date cannot predate the last posted receipt.')
    event = BookingEvent(booking_id=obj.id, kind=kind, new_party_id=new_party_id, old_party_id=obj.party_id,
                         date=on, reason=reason, created_by=actor)
    session.add(event)
    audit(session, actor, 'request_event', event, {'kind': kind, 'booking': obj.number})
    return event


def decide_event(session, actor, event_id, accepted, demo=False):
    require(session, actor, 'approve')
    event = lock(session, BookingEvent, event_id)
    if event.status != 'Pending':
        raise BusinessError('Only pending requests can be decided.')
    if accepted and not demo and event.created_by == actor:
        raise BusinessError('Another authorized user must approve this request.')
    obj = lock(session, Booking, event.booking_id)
    if obj.status != 'Active' or obj.party_id != event.old_party_id:
        raise BusinessError('Booking ownership changed; review this request.')
    if not accepted:
        event.status = 'Rejected'
        audit(session, actor, 'reject_event', event, {})
        return
    check_date(session, event.date)
    paid = booking_paid(session, obj.id)
    outstanding = obj.total - paid
    rows = []
    if event.kind == 'Transfer':
        if outstanding:
            rows += [line(account(session, '1200'), debit=outstanding, party_id=event.new_party_id),
                     line(account(session, '1200'), credit=outstanding, party_id=event.old_party_id)]
        rows += [line(account(session, '2100'), debit=obj.total, party_id=event.old_party_id),
                 line(account(session, '2100'), credit=obj.total, party_id=event.new_party_id)]
        obj.party_id = event.new_party_id
    else:
        rows = [line(account(session, '2100'), debit=obj.total, party_id=obj.party_id)]
        if outstanding:
            rows += [line(account(session, '1200'), credit=outstanding, party_id=obj.party_id)]
        if paid:
            rows += [line(account(session, '2200'), credit=paid, party_id=obj.party_id)]
        # Commission is retained under the pilot policy; cancellation does not silently claw it back.
        obj.status = 'Cancelled'
        lock(session, Unit, obj.unit_id).status = 'Available'
    unit = existing(session, Unit, obj.unit_id)
    # The approver generates and posts the already-approved business event atomically.
    # No extra entry privilege is needed; construct using the request creator, then approve as reviewer.
    voucher = create_voucher(session, event.created_by, unit.project_id, event.date, event.kind,
                              f'{event.kind} {obj.number}: {event.reason}', rows, f'event:{event.id}')
    approve(session, actor, voucher.id, demo=demo)
    event.voucher_id, event.status, event.approved_by = voucher.id, 'Approved', actor
    audit(session, actor, 'approve_event', event, {'paid_paisa': paid, 'outstanding_paisa': outstanding})
