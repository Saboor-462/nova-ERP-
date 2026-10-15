from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from nova.models import Account, Allocation, Attachment, Booking, BookingEvent, Invoice, Line, Party, Project, Unit, Voucher
from nova.services.common import BusinessError, audit, check_date, existing, lock, require


def account(session, code):
    result = session.scalar(select(Account).where(Account.code == code))
    if not result:
        raise BusinessError(f'Required account {code} is missing.')
    return result.id


def line(account_id, debit=0, credit=0, party_id=None, description=''):
    return dict(account_id=account_id, debit=debit, credit=credit, party_id=party_id, description=description)


# Party control accounts: every line must name a party of these types so sub-ledgers reconcile to the control total.
CONTROL_ACCOUNTS = {
    '1200': ('Customer',),                          # Customer receivables
    '2100': ('Customer',),                          # Customer booking obligations
    '2200': ('Customer',),                          # Customer refunds payable
    '2000': ('Vendor', 'Contractor', 'Landowner'),  # Vendor / contractor payable
    '2300': ('Dealer',),                            # Dealer commission payable
}
# Booking balances change only through their linked workflows, so installment schedules stay consistent.
LINKED_ONLY_ACCOUNTS = ('1200', '2100')
MANUAL_KINDS = ('Journal', 'Payment', 'Cash Transfer', 'Import')


def validate_lines(session, rows, kind=None):
    if len(rows) < 2 or len(rows) > 500:
        raise BusinessError('A voucher requires 2–500 accounting rows.')
    for row in rows:
        debit, credit = row.get('debit', 0), row.get('credit', 0)
        if not isinstance(debit, int) or not isinstance(credit, int) or debit < 0 or credit < 0 or bool(debit) == bool(credit):
            raise BusinessError('Each row must contain a positive debit OR credit, in whole paisa.')
        a = existing(session, Account, row['account_id'])
        if not a.active or a.is_group:
            raise BusinessError('Select an active posting account, not a group.')
        party = existing(session, Party, row['party_id']) if row.get('party_id') else None
        if kind in MANUAL_KINDS and a.code in LINKED_ONLY_ACCOUNTS:
            raise BusinessError(f'Account {a.code} · {a.name} is posted only by booking, receipt, invoice, transfer, and cancellation workflows.')
        # A reversal mirrors its approved original line for line, including entries made before this rule existed.
        if kind != 'Reversal' and a.code in CONTROL_ACCOUNTS:
            allowed = CONTROL_ACCOUNTS[a.code]
            if party is None or party.kind not in allowed:
                raise BusinessError(f'Account {a.code} · {a.name} requires a {" / ".join(allowed)} party on the row.')
    if sum(r['debit'] for r in rows) != sum(r['credit'] for r in rows):
        raise BusinessError('Total debits must equal total credits.')


def create_voucher(session, actor_id, project_id, on, kind, description, rows, token, attachment=None, payment_mode='', payment_type=''):
    require(session, actor_id, 'entry')
    previous = session.scalar(select(Voucher).where(Voucher.token == token))
    if previous:
        if previous.created_by != actor_id:
            raise BusinessError('Duplicate request token belongs to another user.')
        return previous
    existing(session, Project, project_id)
    check_date(session, on)
    if not description.strip() or not token.strip() or len(token) > 100:
        raise BusinessError('Description and a valid request token are required.')
    validate_lines(session, rows, kind)
    from nova.services.numbering import next_number, PREFIXES
    identity = uuid4().hex
    voucher = Voucher(id=identity, number=next_number(session, PREFIXES.get(kind, 'JV')), token=token,
                      kind=kind, project_id=project_id, date=on, description=description.strip(), created_by=actor_id,
                      payment_mode=payment_mode[:40], payment_type=payment_type[:60])
    session.add(voucher)
    session.flush()
    for row in rows:
        session.add(Line(voucher_id=voucher.id, **row))
    if attachment:
        name, mime, data = attachment
        if len(data) > 5 * 1024 * 1024:
            raise BusinessError('Attachments must be 5 MB or smaller.')
        name = Path(name).name[:180]
        signatures = {'application/pdf': b'%PDF', 'image/png': b'\x89PNG', 'image/jpeg': b'\xff\xd8'}
        if mime not in signatures or not data.startswith(signatures[mime]):
            raise BusinessError('Upload a valid PDF, PNG, or JPEG file.')
        session.add(Attachment(voucher_id=voucher.id, filename=name, mime=mime, data=data))
    audit(session, actor_id, 'create', voucher, {'total_paisa': sum(r['debit'] for r in rows)})
    return voucher


def approve(session, actor_id, voucher_id, demo=False):
    require(session, actor_id, 'approve')
    voucher = lock(session, Voucher, voucher_id)
    if voucher.status != 'Pending':
        raise BusinessError('Only pending vouchers can be approved.')
    if not demo and voucher.created_by == actor_id:
        raise BusinessError('Another authorized user must approve your voucher.')
    check_date(session, voucher.date)
    rows = session.scalars(select(Line).where(Line.voucher_id == voucher.id)).all()
    validate_lines(session, [line(r.account_id, r.debit, r.credit, r.party_id, r.description) for r in rows], voucher.kind)
    if voucher.reversal_of and session.scalar(select(Voucher.id).where(Voucher.reversal_of == voucher.reversal_of,
                                                                        Voucher.status == 'Posted', Voucher.id != voucher.id)):
        raise BusinessError('The original voucher has already been reversed.')
    voucher.status = 'Posted'
    voucher.approved_by = actor_id
    if voucher.reversal_of:
        original_invoice = session.scalar(select(Invoice).where(Invoice.voucher_id == voucher.reversal_of))
        if original_invoice:
            original_invoice.status = 'Rejected'
            audit(session, actor_id, 'invoice_cancelled', original_invoice, {'reversal': voucher.number})
    audit(session, actor_id, 'approve', voucher, {'number': voucher.number})


def reject(session, actor_id, voucher_id, reason):
    require(session, actor_id, 'approve')
    voucher = lock(session, Voucher, voucher_id)
    if voucher.status != 'Pending' or not reason.strip():
        raise BusinessError('A pending voucher and rejection reason are required.')
    voucher.status = 'Rejected'
    booking = session.scalar(select(Booking).where(Booking.voucher_id == voucher.id))
    if booking:
        booking.status = 'Rejected'
        lock(session, Unit, booking.unit_id).status = 'Available'
    invoice = session.scalar(select(Invoice).where(Invoice.voucher_id == voucher.id))
    if invoice:
        # Kept for history; its reference becomes available for a corrected invoice.
        invoice.status = 'Rejected'
    audit(session, actor_id, 'reject', voucher, {'reason': reason})


def reverse(session, actor_id, voucher_id, on, reason, token):
    require(session, actor_id, 'entry')
    original = lock(session, Voucher, voucher_id)
    check_date(session, on)
    if original.status != 'Posted' or original.reversal_of or on < original.date:
        raise BusinessError('Select a posted original voucher and a reversal date on or after it.')
    if not reason.strip():
        raise BusinessError('A reversal reason is required.')
    if session.scalar(select(Voucher.id).where(Voucher.reversal_of == original.id, Voucher.status != 'Rejected')):
        raise BusinessError('A reversal already exists for this voucher.')
    # Domain transactions require their own cancellation/transfer workflow.
    for model in (Booking, Invoice, BookingEvent):
        if session.scalar(select(model.id).where(model.voucher_id == original.id)):
            raise BusinessError('This voucher is linked to a booking, invoice, or ownership event; use its business workflow.')
    from nova.models import InvoiceCorrection, InvoicePayment
    from nova.services.invoice_corrections import ensure_no_pending_correction
    if session.scalar(select(InvoiceCorrection.id).where(InvoiceCorrection.voucher_id == original.id).limit(1)):
        raise BusinessError('This voucher belongs to an invoice correction. Use another invoice correction or the invoice cancellation workflow.')
    invoice_ids = session.scalars(select(InvoicePayment.invoice_id).where(InvoicePayment.voucher_id == original.id)).all()
    for invoice_id in sorted(set(invoice_ids)):
        lock(session, Invoice, invoice_id)
        ensure_no_pending_correction(session, invoice_id)
    booking_ids = session.scalars(select(Installment.booking_id).join(Allocation, Allocation.installment_id == Installment.id)
                                   .where(Allocation.voucher_id == original.id)).all()
    for booking_id in set(booking_ids):
        b = lock(session, Booking, booking_id)
        if b.status != 'Active' or session.scalar(select(BookingEvent.id).where(BookingEvent.booking_id == b.id,
                                                                              BookingEvent.status.in_(['Pending', 'Approved']))):
            raise BusinessError('Receipt reversal is blocked after an ownership event or while one is pending.')
    rows = session.scalars(select(Line).where(Line.voucher_id == original.id)).all()
    reversal = create_voucher(session, actor_id, original.project_id, on, 'Reversal', reason,
                              [line(r.account_id, r.credit, r.debit, r.party_id, r.description) for r in rows], token)
    # Rejected attempts keep their link; ux_vouchers_effective_reversal allows one pending/posted reversal.
    reversal.reversal_of = original.id
    audit(session, actor_id, 'reverse_request', reversal, {'original': original.number})
    return reversal


from nova.models import Installment
