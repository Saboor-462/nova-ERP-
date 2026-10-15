"""Approval-controlled corrections to posted invoices, with immutable request snapshots."""
import json
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select

from nova.models import Invoice, InvoiceCorrection, InvoiceItem, InvoicePayment, Line, Voucher
from nova.services import accounting
from nova.services.common import BusinessError, audit, check_date, existing, lock, money, require


def invoice_snapshot(session, invoice):
    items = session.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)
                            .order_by(InvoiceItem.sequence)).all()
    return {'reference': invoice.reference, 'date': invoice.date.isoformat(), 'due': invoice.due.isoformat(),
            'amount': int(invoice.amount), 'description': invoice.description,
            'items': [{'description': item.description, 'amount': int(item.amount)} for item in items]}


def pending_correction(session, invoice_id):
    return session.scalar(select(InvoiceCorrection).where(InvoiceCorrection.invoice_id == invoice_id,
                                                         InvoiceCorrection.status == 'Pending'))


def ensure_no_pending_correction(session, invoice_id):
    if pending_correction(session, invoice_id):
        raise BusinessError('Resolve the pending invoice correction before recording payments, reversals, or invoice cancellation.')


def latest_correction_date(session, invoice_id):
    return session.scalar(select(func.max(InvoiceCorrection.effective_on))
                          .where(InvoiceCorrection.invoice_id == invoice_id, InvoiceCorrection.status == 'Approved'))


def latest_invoice_activity(session, invoice):
    payment_ids = select(InvoicePayment.voucher_id).where(InvoicePayment.invoice_id == invoice.id)
    payment_date = session.scalar(select(func.max(Voucher.date))
                                  .where(Voucher.status.in_(['Pending', 'Posted']),
                                         Voucher.id.in_(payment_ids) | Voucher.reversal_of.in_(payment_ids)))
    return max(value for value in (invoice.date, latest_correction_date(session, invoice.id), payment_date) if value)


def _check_payment_workflows(session, invoice_id):
    payment_ids = select(InvoicePayment.voucher_id).where(InvoicePayment.invoice_id == invoice_id)
    if session.scalar(select(Voucher.id).where(Voucher.status == 'Pending',
                                              Voucher.id.in_(payment_ids) | Voucher.reversal_of.in_(payment_ids)).limit(1)):
        raise BusinessError('Resolve pending settlements and settlement reversals before requesting or approving an invoice correction.')


def _posted_invoice(session, invoice_id):
    invoice = lock(session, Invoice, invoice_id)
    original = lock(session, Voucher, invoice.voucher_id)
    if invoice.status != 'Active' or original.status != 'Posted':
        raise BusinessError('Only an active, approved invoice can receive a correction.')
    if session.scalar(select(Voucher.id).where(Voucher.reversal_of == original.id,
                                              Voucher.status != 'Rejected').limit(1)):
        raise BusinessError('Resolve the invoice cancellation before requesting or approving a correction.')
    return invoice, original


def _values(invoice, before, reference, due, amount, description, items):
    from nova.services.records import validate_invoice_items

    reference = str(reference or '').strip()
    description = str(description or '').strip()
    amount = money(amount)
    if not reference or len(reference) > 100 or not description or amount <= 0:
        raise BusinessError('A reference of up to 100 characters, description, and positive amount are required.')
    if type(due) is not date or due < invoice.date:
        raise BusinessError('The due date must be on or after the original invoice date.')
    items = before['items'] if items is None else items
    if not isinstance(items, list) or any(not isinstance(item, dict) or
                                         not isinstance(item.get('description'), str) or
                                         type(item.get('amount')) is not int for item in items):
        raise BusinessError('Provide valid invoice item descriptions and whole-paisa amounts.')
    items = [{'description': item['description'].strip(), 'amount': item['amount']} for item in items]
    validate_invoice_items(items, amount)
    return {'reference': reference, 'date': invoice.date.isoformat(), 'due': due.isoformat(),
            'amount': amount, 'description': description, 'items': items}


def _check_reference(session, invoice, reference):
    if session.scalar(select(Invoice.id).where(Invoice.id != invoice.id, Invoice.party_id == invoice.party_id,
                                              Invoice.kind == invoice.kind, Invoice.reference == reference,
                                              Invoice.status == 'Active').limit(1)):
        raise BusinessError('This party already has an active invoice with that reference.')


def _check_balance(session, invoice, amount):
    from nova.services.sales import invoice_paid

    if amount < invoice_paid(session, invoice.id, include_pending=True):
        raise BusinessError('The corrected total cannot be less than the settled amount. Resolve the settlements first.')


def _check_effective_date(session, invoice, effective_on):
    check_date(session, effective_on)
    if effective_on < latest_invoice_activity(session, invoice):
        raise BusinessError('The correction date cannot predate the invoice, its latest approved correction, or its latest settlement activity.')


def _decode_snapshot(value):
    try:
        data = json.loads(value)
        if not isinstance(data, dict) or set(data) != {'reference', 'date', 'due', 'amount', 'description', 'items'}:
            raise ValueError
        if type(data['amount']) is not int:
            raise ValueError
        return data
    except (TypeError, ValueError):
        raise BusinessError('The correction snapshot is invalid. Reject this request and create a new correction.') from None


def request_correction(session, actor, invoice_id, effective_on, reference, due, amount, description, reason, token, items=None):
    require(session, actor, 'entry')
    if not isinstance(token, str) or not token.strip() or len(token) > 100:
        raise BusinessError('A valid correction request token is required.')
    previous = session.scalar(select(InvoiceCorrection).where(InvoiceCorrection.token == token))
    if previous:
        if previous.created_by != actor or previous.invoice_id != invoice_id:
            raise BusinessError('This correction request token belongs to another user or invoice.')
        return previous
    invoice, original = _posted_invoice(session, invoice_id)
    ensure_no_pending_correction(session, invoice.id)
    _check_payment_workflows(session, invoice.id)
    _check_effective_date(session, invoice, effective_on)
    reason = str(reason or '').strip()
    if not reason:
        raise BusinessError('A correction reason is required.')
    before = invoice_snapshot(session, invoice)
    after = _values(invoice, before, reference, due, amount, description, items)
    if after == before:
        raise BusinessError('Change at least one invoice value before submitting a correction.')
    _check_reference(session, invoice, after['reference'])
    _check_balance(session, invoice, after['amount'])
    correction = InvoiceCorrection(invoice_id=invoice.id, token=token, effective_on=effective_on, reason=reason,
                                   before_data=json.dumps(before, sort_keys=True), after_data=json.dumps(after, sort_keys=True),
                                   created_by=actor)
    session.add(correction)
    audit(session, actor, 'invoice_correction_requested', correction,
          {'invoice_id': invoice.id, 'invoice_number': original.number, 'effective_on': effective_on,
           'reason': reason, 'before': before, 'after': after})
    return correction


def _adjustment_rows(session, invoice, original, difference):
    rows = session.scalars(select(Line).where(Line.voucher_id == original.id)).all()
    if len(rows) != 2:
        raise BusinessError('This invoice requires a separately reviewed accounting correction because its original posting has more or fewer than two lines.')
    amount = abs(difference)
    return [accounting.line(row.account_id,
                           debit=amount if (bool(row.debit) == (difference > 0)) else 0,
                           credit=amount if (bool(row.credit) == (difference > 0)) else 0,
                           party_id=row.party_id, description=f'Correction to {invoice.reference}') for row in rows]


def decide_correction(session, actor, correction_id, accepted, review_reason=''):
    require(session, actor, 'approve')
    if type(accepted) is not bool:
        raise BusinessError('Choose approval or rejection for this correction.')
    selected = existing(session, InvoiceCorrection, correction_id)
    invoice = lock(session, Invoice, selected.invoice_id)
    correction = lock(session, InvoiceCorrection, correction_id)
    if correction.status != 'Pending':
        raise BusinessError('Only pending invoice corrections can be reviewed.')
    if correction.created_by == actor:
        raise BusinessError('Another authorized user must review your invoice correction.')
    review_reason = str(review_reason or '').strip()
    if not accepted:
        if not review_reason:
            raise BusinessError('A rejection reason is required.')
        correction.status = 'Rejected'
        correction.reviewed_by, correction.reviewed_at = actor, datetime.now(timezone.utc)
        correction.review_reason = review_reason
        audit(session, actor, 'invoice_correction_rejected', correction,
              {'invoice_id': invoice.id, 'reason': review_reason})
        return correction
    invoice, original = _posted_invoice(session, invoice.id)
    require(session, correction.created_by, 'entry')
    _check_payment_workflows(session, invoice.id)
    _check_effective_date(session, invoice, correction.effective_on)
    before, after = _decode_snapshot(correction.before_data), _decode_snapshot(correction.after_data)
    if invoice_snapshot(session, invoice) != before:
        raise BusinessError('The invoice changed after this request. Reject it and submit a new correction.')
    try:
        proposed = _values(invoice, before, after['reference'], date.fromisoformat(after['due']),
                           Decimal(after['amount']) / 100, after['description'], after['items'])
    except (TypeError, ValueError) as exc:
        if isinstance(exc, BusinessError):
            raise
        raise BusinessError('The proposed correction values are invalid. Reject this request and submit it again.') from None
    if proposed != after or after == before:
        raise BusinessError('The proposed correction snapshot is inconsistent. Reject this request and submit it again.')
    _check_reference(session, invoice, after['reference'])
    _check_balance(session, invoice, after['amount'])
    difference = after['amount'] - before['amount']
    voucher = None
    if difference:
        voucher = accounting.create_voucher(session, correction.created_by, invoice.project_id, correction.effective_on,
                                             f'{invoice.kind} Invoice', f'Invoice correction {original.number}: {correction.reason}',
                                             _adjustment_rows(session, invoice, original, difference),
                                             'invoice-correction:' + correction.id)
        correction.voucher_id = voucher.id
        accounting.approve(session, actor, voucher.id)
    invoice.reference, invoice.due = after['reference'], date.fromisoformat(after['due'])
    invoice.amount, invoice.description = after['amount'], after['description']
    session.execute(delete(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id))
    for sequence, item in enumerate(after['items'], 1):
        session.add(InvoiceItem(invoice_id=invoice.id, sequence=sequence, **item))
    correction.status = 'Approved'
    correction.reviewed_by, correction.reviewed_at = actor, datetime.now(timezone.utc)
    correction.review_reason = review_reason
    audit(session, actor, 'invoice_correction_approved', correction,
          {'invoice_id': invoice.id, 'invoice_number': original.number, 'effective_on': correction.effective_on,
           'reason': correction.reason, 'review_reason': review_reason, 'before': before, 'after': after,
           'adjustment_voucher': voucher.number if voucher else None})
    return correction
