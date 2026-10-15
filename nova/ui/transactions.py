from datetime import date, timedelta
import json
import pandas as pd
import streamlit as st
from sqlalchemy import select
from nova.models import Account, Attachment, Audit, Booking, BookingEvent, Installment, Invoice, Line, Party, Project, Unit, Voucher
from nova.services import accounting, sales
from nova.services.common import BusinessError, business_today, money, rupees
from nova.ui.common import can, choose, md_escape, mutate, options, pdf_bytes, table, token, uploaded


def vouchers(factory, actor, demo):
    from nova.branding import brand_header
    brand_header('Vouchers', 'Balanced accounting entries, approval queues, and document history')
    project_opts = options(factory, Project, lambda p: p.name)
    project_id = choose('Project filter', project_opts, optional=True)
    with factory() as session:
        query = select(Voucher)
        if project_id:
            query = query.where(Voucher.project_id == project_id)
        all_records = session.scalars(query.order_by(Voucher.created_at.desc())).all()
    pending_count = sum(v.status == 'Pending' for v in all_records)
    if pending_count:
        st.error(f'{pending_count} pending voucher(s) awaiting approval.')
    section = st.radio('Voucher section', ['New Voucher', 'Voucher List', 'Pending Vouchers'], index=1, horizontal=True)
    if section == 'New Voucher':
        if can(actor, 'entry'):
            new_voucher(factory, actor)
        else:
            st.info('Your role does not permit accounting entry.')
        return
    status = 'Pending' if section == 'Pending Vouchers' else st.selectbox('Voucher status', ['All', 'Pending', 'Posted', 'Rejected'])
    records = [v for v in all_records if status == 'All' or v.status == status]
    table(pd.DataFrame([{'Voucher ID': v.id, 'Voucher': v.number, 'Date': v.date.isoformat(), 'Project': project_opts.get(v.project_id, ''),
                         'Type': v.kind, 'Description': v.description, 'Status': v.status} for v in records]), 'Vouchers', hide=['Voucher ID'])
    if records:
        selected = choose('Open voucher', {v.id: f'{v.number} · {v.status}' for v in records})
        show_voucher(factory, actor, selected, False)


def show_voucher(factory, actor, voucher_id, demo):
    with factory() as session:
        v = session.get(Voucher, voucher_id)
        rows = session.execute(select(Line, Account, Party).join(Account, Line.account_id == Account.id)
                               .outerjoin(Party, Line.party_id == Party.id).where(Line.voucher_id == voucher_id)).all()
        attachments = session.scalars(select(Attachment).where(Attachment.voucher_id == voucher_id)).all()
        rejection_reason = ''
        reason_label = 'Rejection reason'
        if v.status == 'Rejected':
            decision = session.scalar(
                select(Audit).where(
                    Audit.entity == Voucher.__tablename__,
                    Audit.entity_id == voucher_id,
                    Audit.action.in_(['reject', 'cancel_pending']),
                ).order_by(Audit.at.desc(), Audit.id.desc()).limit(1)
            )
            if decision:
                reason_label = 'Cancellation reason' if decision.action == 'cancel_pending' else 'Rejection reason'
                try:
                    detail = json.loads(decision.detail)
                except (TypeError, json.JSONDecodeError):
                    detail = {}
                if isinstance(detail, dict):
                    rejection_reason = str(detail.get('reason') or '').strip()
    frame = pd.DataFrame([{'Account': f'{a.code} · {a.name}', 'Party': p.name if p else '', 'Description': l.description,
                           'Debit': rupees(l.debit), 'Credit': rupees(l.credit)} for l, a, p in rows])
    st.subheader(v.number)
    st.caption(f'{v.date} · {v.kind} · {v.status} · {md_escape(v.description)}')
    if v.status == 'Rejected':
        if rejection_reason:
            st.warning(f'{reason_label}: {md_escape(rejection_reason)}')
        else:
            st.info('No rejection or cancellation reason was found for this voucher.')
    st.dataframe(frame, hide_index=True, width='stretch')
    st.write(f'Total debit: PKR {rupees(sum(l.debit for l, _, _ in rows)):,.2f} · Total credit: PKR {rupees(sum(l.credit for l, _, _ in rows)):,.2f}')
    from nova.documents import voucher_pdf
    with factory() as session:
        printed = voucher_pdf(session, v.id)
    st.download_button('Download / Print voucher PDF', printed, f'{v.number}.pdf', 'application/pdf', key=f'print:{v.id}')
    st.caption(f'Permanent record ID: {v.id}')
    if v.status == 'Pending':
        st.error('Pending approval — not posted to financial reports.')
    for attachment in attachments if actor.role in ('Admin', 'Accountant', 'Approver') else []:
        st.download_button(f'Attachment: {md_escape(attachment.filename)}', attachment.data, attachment.filename, attachment.mime, key=attachment.id)
    if v.status == 'Pending' and can(actor, 'approve'):
        c1, c2 = st.columns(2)
        if c1.button('Approve voucher', type='primary', key=f'approve:{v.id}'):
            if mutate(factory, lambda s: accounting.approve(s, actor.id, v.id, demo=demo)) is not None:
                st.rerun()
        with c2:
            with st.form(f'reject:{v.id}'):
                reason = st.text_input('Rejection reason')
                if st.form_submit_button('Reject voucher'):
                    if mutate(factory, lambda s: accounting.reject(s, actor.id, v.id, reason)):
                        st.rerun()
    if v.status == 'Pending' and can(actor, 'entry'):
        pending_editor(factory, actor, v, rows)
    if v.status == 'Posted' and can(actor, 'entry') and not v.reversal_of:
        with st.expander('Request reversal'):
            st.caption('Linked bookings and invoices use their business workflows. A reversal requires approval.')
            with st.form(f'reversal:{v.id}'):
                on = st.date_input('Reversal date', business_today())
                reason = st.text_input('Reason for reversal')
                key = f'reversal:{v.id}'
                request_token = token(key)
                if st.form_submit_button('Submit reversal'):
                    mutate(factory, lambda s: accounting.reverse(s, actor.id, v.id, on, reason, request_token), key)


def _cell(value):
    """Editor cells arrive as None/NaN when blank; return trimmed text."""
    if value is None or (isinstance(value, float) and value != value):
        return ''
    text = str(value).strip()
    return '' if text.lower() in ('nan', 'none') else text


def voucher_rows(edited, accounts, parties):
    """Turn the manual voucher grid into accounting lines: blank rows are ignored, partial rows rejected."""
    rows = []
    for number, (_, row) in enumerate(edited.iterrows(), 1):
        account, party, description = _cell(row.get('Account')), _cell(row.get('Party')), _cell(row.get('Description'))
        debit_text, credit_text = _cell(row.get('Debit')) or '0', _cell(row.get('Credit')) or '0'
        try:
            debit, credit = money(debit_text), money(credit_text)
        except BusinessError as exc:
            raise BusinessError(f'Row {number}: {exc}') from None
        if not (account or party or description or debit or credit):
            continue
        if account not in accounts:
            raise BusinessError(f'Row {number}: select an account, or clear the row.')
        if party and party not in parties:
            raise BusinessError(f'Row {number}: select a listed party, or leave Party blank.')
        if bool(debit) == bool(credit):
            raise BusinessError(f'Row {number}: enter either a debit or a credit amount, not both or neither.')
        rows.append(accounting.line(accounts[account], debit, credit, parties.get(party), description))
    return rows


def new_voucher(factory, actor):
    from nova.branding import brand_header
    brand_header('General Payments', 'New voucher · The permanent number is assigned when you save')
    projects = options(factory, Project, lambda p: p.name)
    account_opts = options(factory, Account, lambda a: f'{a.code} · {a.name}',
                           (Account.is_group == False) & (Account.active == True) & Account.code.not_in(['1200', '2100']))
    party_opts = options(factory, Party, lambda p: f'{p.name} · {p.kind} · {p.id[:6]}')
    reverse_accounts = {label: key for key, label in account_opts.items()}
    reverse_parties = {label: key for key, label in party_opts.items()}
    c1, c2, c3 = st.columns(3)
    with c1:
        project = choose('Project', projects, key='manual_project')
    on = c2.date_input('Voucher date', business_today(), key='manual_date')
    kind = c3.selectbox('Select Payment Mode', ['Journal', 'Payment', 'Cash Transfer'], key='manual_kind')
    payment_type = st.selectbox('Select Payment Type', ['Adjustment', 'Cash', 'Bank', 'Cheque', 'Online transfer'], key='manual_payment_type')
    description = st.text_input('Voucher description', key='manual_description')
    initial = pd.DataFrame([{'Account': '', 'Party': '', 'Description': '', 'Debit': '0', 'Credit': '0'} for _ in range(2)])
    base = st.session_state.setdefault('manual_grid', initial)
    edited = st.data_editor(base, num_rows='dynamic', hide_index=True, width='stretch',
                            column_config={'Account': st.column_config.SelectboxColumn(options=list(reverse_accounts), required=True),
                                           'Party': st.column_config.SelectboxColumn(options=[''] + list(reverse_parties))}, key='voucher_editor')
    if st.button('Add Row', key='manual_add_row'):
        st.session_state['manual_grid'] = pd.concat([edited, initial.iloc[:1]], ignore_index=True)
        st.session_state.pop('voucher_editor', None)
        st.rerun()
    debit = credit = 0
    valid_rows, grid_error = [], None
    try:
        valid_rows = voucher_rows(edited, reverse_accounts, reverse_parties)
        debit = sum(r['debit'] for r in valid_rows)
        credit = sum(r['credit'] for r in valid_rows)
    except BusinessError as exc:
        grid_error = str(exc)
    left, right = st.columns(2)
    left.metric('Total debit (PKR)', f'{rupees(debit):,.2f}')
    right.metric('Total credit (PKR)', f'{rupees(credit):,.2f}')
    if grid_error:
        st.warning(md_escape(grid_error))
    elif debit != credit:
        st.error(f'Unbalanced voucher: difference PKR {rupees(abs(debit-credit)):,.2f}.')
    receipt = st.file_uploader('Upload Receipts (PDF / PNG / JPEG, up to 5 MB)', type=['pdf', 'png', 'jpg', 'jpeg'], key='manual_attachment')
    request_token = token('manual')
    if st.button('Submit for approval', type='primary', disabled=not project or bool(grid_error) or len(valid_rows) < 2 or debit != credit):
        result = mutate(factory, lambda s: accounting.create_voucher(s, actor.id, project, on, kind, description, valid_rows, request_token,
                                                                     uploaded(receipt), payment_mode=kind, payment_type=payment_type), 'manual')
        if result:
            st.success(f'Voucher {result.number} saved as Pending. Its number will not change on approval.')
            st.session_state['manual_grid'] = initial
            st.session_state.pop('voucher_editor', None)
    st.caption('Use the plus/delete controls in the grid to add/remove rows. Customer receipts use Allotments → Customer receipt. Booking control accounts cannot be entered through a manual journal.')


def pending_editor(factory, actor, v, displayed_lines):
    from nova.services import records
    if v.created_by != actor.id and actor.role != 'Admin':
        return
    if v.kind in accounting.MANUAL_KINDS:
        with st.expander('Edit pending voucher'):
            accounts = options(factory, Account, lambda a: f'{a.code} · {a.name}', (Account.is_group == False) & (Account.active == True) & Account.code.not_in(['1200', '2100']))
            parties = options(factory, Party, lambda p: f'{p.name} · {p.kind} · {p.id[:6]}')
            frame = pd.DataFrame([{'Account': accounts.get(l.account_id, ''), 'Party': parties.get(l.party_id, ''), 'Description': l.description,
                                   'Debit': str(rupees(l.debit)), 'Credit': str(rupees(l.credit))} for l, _, _ in displayed_lines])
            with st.form('editvoucher:' + v.id):
                on = st.date_input('Edited voucher date', v.date)
                description = st.text_input('Edited description', v.description)
                mode = st.text_input('Payment mode', v.payment_mode or v.kind)
                ptype = st.text_input('Payment type', v.payment_type)
                edited = st.data_editor(frame, num_rows='dynamic', hide_index=True, width='stretch', key='editgrid:' + v.id,
                     column_config={'Account': st.column_config.SelectboxColumn(options=list(accounts.values())),
                                    'Party': st.column_config.SelectboxColumn(options=[''] + list(parties.values()))})
                if st.form_submit_button('Save voucher changes'):
                    def save(s):
                        rows = voucher_rows(edited, {val:key for key,val in accounts.items()}, {val:key for key,val in parties.items()})
                        records.edit_voucher(s, actor.id, v.id, on, description, rows, mode, ptype)
                    if mutate(factory, save):
                        st.rerun()
    elif v.kind in ('Receipt', 'Settlement'):
        with st.expander('Edit pending receipt / settlement'):
            with st.form('editpayment:' + v.id):
                on = st.date_input('Payment date', v.date)
                amount = st.text_input('Payment amount (PKR)', str(rupees(sum(l.debit for l, _, _ in displayed_lines))))
                description = st.text_input('Payment description', v.description)
                if st.form_submit_button('Save payment changes'):
                    if mutate(factory, lambda s: records.edit_pending_payment(s, actor.id, v.id, on, amount, description)):
                        st.rerun()
    else:
        st.caption('Edit this entry in its linked Allotments or Invoices page. The voucher ID/number is retained.')
    with st.expander('Delete / cancel pending voucher'):
        with st.form('cancelpending:' + v.id):
            reason = st.text_input('Cancellation reason')
            confirmed = st.checkbox('Cancel this pending entry; retain its number and history')
            if st.form_submit_button('Cancel pending voucher') and confirmed:
                if mutate(factory, lambda s: records.cancel_pending(s, actor.id, v.id, reason)):
                    st.rerun()


def bookings(factory, actor):
    st.header('Unit allotments / Bookings')
    project_opts = options(factory, Project, lambda p: p.name)
    customer_opts = options(factory, Party, lambda p: f'{p.name} · {p.id[:6]}', Party.kind == 'Customer')
    dealer_opts = options(factory, Party, lambda p: p.name, Party.kind == 'Dealer')
    with factory() as session:
        records = session.execute(select(Booking, Unit, Party, Voucher).join(Unit, Booking.unit_id == Unit.id)
                                  .join(Party, Booking.party_id == Party.id).join(Voucher, Booking.voucher_id == Voucher.id)
                                  .order_by(Booking.date.desc())).all()
        paid = {b.id: sales.booking_paid(session, b.id) for b, _, _, _ in records}
    table(pd.DataFrame([{'Allotment': b.number, 'Project': project_opts.get(u.project_id, ''), 'Unit': u.number, 'Customer': p.name,
                         'Date': b.date.isoformat(), 'Total': rupees(b.total), 'Down Payment Scheduled': rupees(b.down_payment),
                         'Received': rupees(paid[b.id]), 'Outstanding': rupees(b.total - paid[b.id]) if b.status == 'Active' else 0,
                         'Status': b.status, 'Booking Voucher': v.status} for b, u, p, v in records]), 'Allotments')
    if records:
        booking_id = choose('Open booking / booking form', {b.id: f'{b.number} · {u.number} · {p.name}' for b, u, p, _ in records})
        with factory() as session:
            b = session.get(Booking, booking_id)
            customer = session.get(Party, b.party_id)
            unit = session.get(Unit, b.unit_id)
            insts = session.scalars(select(Installment).where(Installment.booking_id == b.id).order_by(Installment.sequence)).all()
            schedule = pd.DataFrame([{'Installment': 'Down payment' if i.sequence == 0 else str(i.sequence), 'Due': i.due.isoformat(),
                                      'Amount': rupees(i.amount), 'Paid': rupees(sales.installment_paid(session, i.id))} for i in insts])
        st.write(f'**{b.number}** · {md_escape(customer.name)} · {md_escape(unit.number)} · {b.status}')
        st.dataframe(schedule, hide_index=True, width='stretch')
        from nova.documents import booking_pdf
        with factory() as session:
            document = booking_pdf(session, b.id)
            booking_voucher = session.get(Voucher, b.voucher_id)
        st.download_button('Download / Print booking form', document, f'{b.number}.pdf', 'application/pdf')
        if can(actor, 'entry') and booking_voucher.status == 'Pending':
            from nova.services import records
            with st.expander('Edit / delete pending booking'):
                with st.form('editbooking:' + b.id):
                    on = st.date_input('Booking date', b.date)
                    total = st.text_input('Agreed price (PKR)', str(rupees(b.total)))
                    down = st.text_input('Down payment (PKR)', str(rupees(b.down_payment)))
                    count = st.number_input('Installment count', 1, 360, max(1, len([i for i in insts if i.sequence])))
                    first = st.date_input('First due date', next((i.due for i in insts if i.sequence), b.date))
                    if st.form_submit_button('Save booking changes'):
                        if mutate(factory, lambda s: records.edit_booking(s, actor.id, b.id, on, total, down, count, first)):
                            st.rerun()
                with st.form('deletebooking:' + b.id):
                    reason = st.text_input('Reason to cancel pending booking')
                    if st.form_submit_button('Delete / cancel booking'):
                        if mutate(factory, lambda s: records.cancel_pending(s, actor.id, b.voucher_id, reason)):
                            st.rerun()
        if can(actor, 'entry') and b.status == 'Active':
            with st.expander('Customer receipt'):
                cash_opts = options(factory, Account, lambda a: f'{a.code} · {a.name}', Account.is_cash == True)
                with st.form('customer_receipt'):
                    cash = choose('Receive into', cash_opts)
                    on = st.date_input('Receipt date', business_today())
                    amount = st.text_input('Amount received (PKR)', '0')
                    description = st.text_input('Receipt description', f'Customer receipt for {b.number}')
                    attachment = st.file_uploader('Receipt evidence', type=['pdf', 'png', 'jpg', 'jpeg'])
                    request_token = token('receipt')
                    if st.form_submit_button('Submit receipt', type='primary') and cash:
                        mutate(factory, lambda s: sales.receive(s, actor.id, b.id, cash, on, amount, description, request_token, uploaded(attachment)), 'receipt')
    if not can(actor, 'entry'):
        return
    with st.expander('New unit allotment'):
        unit_opts = options(factory, Unit, lambda u: f'{project_opts.get(u.project_id, "")} · {u.number} · PKR {rupees(u.price):,.2f}', Unit.status == 'Available')
        with st.form('new_booking'):
            unit = choose('Available unit', unit_opts)
            customer = choose('Customer', customer_opts)
            c1, c2 = st.columns(2)
            on = c1.date_input('Allotment date', business_today())
            first = c2.date_input('First installment date', business_today() + timedelta(days=30))
            total = c1.text_input('Agreed total price (PKR)', '0')
            down = c2.text_input('Down payment scheduled (PKR)', '0')
            count = c1.number_input('Monthly installments', min_value=1, max_value=360, value=12)
            dealer = choose('Dealer (optional)', dealer_opts, optional=True)
            commission = c2.text_input('Dealer commission (PKR)', '0')
            request_token = token('booking')
            st.caption('Down payment creates a due amount. Record the actual money separately as a customer receipt after booking approval.')
            if st.form_submit_button('Create booking', type='primary') and unit and customer:
                mutate(factory, lambda s: sales.create_booking(s, actor.id, unit, customer, on, total, down, count, first, request_token, dealer, commission), 'booking')


def invoice_rows(frame):
    rows = []
    for _, row in frame.iterrows():
        description = _cell(row.get('Description'))
        amount = money(_cell(row.get('Amount (PKR)')) or '0')
        if not description and not amount:
            continue
        if not description or not amount:
            raise BusinessError('Invoice rows need a description and a positive amount.')
        rows.append({'description': description, 'amount': amount})
    return rows


def invoice_settlements(factory, actor, invoice_id):
    from nova.models import InvoicePayment
    from nova.services import records

    with st.expander('Settlement history / cancellation'):
        with factory() as session:
            payments = session.execute(select(InvoicePayment, Voucher)
                                       .join(Voucher, InvoicePayment.voucher_id == Voucher.id)
                                       .where(InvoicePayment.invoice_id == invoice_id)
                                       .order_by(Voucher.date.desc(), Voucher.number)).all()
            payment_ids = [v.id for _, v in payments]
            reversals = session.scalars(select(Voucher).where(Voucher.reversal_of.in_(payment_ids),
                                                             Voucher.status != 'Rejected')).all() if payment_ids else []
        if not payments:
            st.info('No settlements have been recorded for this invoice.')
            return
        reversed_by = {v.reversal_of: v for v in reversals}

        def status(voucher):
            reversal = reversed_by.get(voucher.id)
            if reversal:
                return 'Reversed' if reversal.status == 'Posted' else 'Reversal awaiting approval'
            return 'Rejected / Cancelled' if voucher.status == 'Rejected' else voucher.status

        table(pd.DataFrame([{'Settlement voucher': v.number, 'Date': str(v.date), 'Amount (PKR)': rupees(p.amount),
                             'Status': status(v), 'Reversal voucher': reversed_by[v.id].number if v.id in reversed_by else ''}
                            for p, v in payments]), 'Invoice Settlements', key='invoice_settlements:' + invoice_id)
        if not can(actor, 'entry'):
            return
        from nova.services.invoice_corrections import pending_correction
        with factory() as session:
            correction_pending = pending_correction(session, invoice_id) is not None
        if correction_pending:
            st.info('Resolve the pending invoice correction before changing or reversing settlements.')
            return
        selected = choose('Settlement to cancel / reverse',
                          {v.id: f'{v.number} · PKR {rupees(p.amount):,.2f} · {status(v)}' for p, v in payments},
                          key='invoice_settlement_open:' + invoice_id)
        payment, voucher = next((p, v) for p, v in payments if v.id == selected)
        reversal = reversed_by.get(voucher.id)
        if reversal:
            st.info(f'Reversal {reversal.number}: {reversal.status}. Approve pending reversals from Vouchers to update the invoice balance.'
                    if reversal.status == 'Pending' else f'Settlement reversed by approved voucher {reversal.number}.')
        elif voucher.status == 'Pending':
            if voucher.created_by != actor.id and actor.role != 'Admin':
                st.info('Only the creator or an administrator can cancel this pending settlement.')
                return
            with st.form('cancel_invoice_settlement:' + voucher.id):
                reason = st.text_input('Settlement cancellation reason')
                confirmed = st.checkbox('Cancel this pending settlement and retain its history.')
                if st.form_submit_button('Cancel pending settlement'):
                    if not confirmed:
                        st.warning('Confirm cancellation before continuing.')
                    elif mutate(factory, lambda s: records.cancel_pending(s, actor.id, voucher.id, reason)):
                        st.rerun()
        elif voucher.status == 'Posted':
            st.caption('The settlement remains included in approved balances until the reversal is approved in Vouchers.')
            with st.form('reverse_invoice_settlement:' + voucher.id):
                on = st.date_input('Settlement reversal date', business_today())
                reason = st.text_input('Settlement reversal reason')
                confirmed = st.checkbox('Request a reversal of this settlement and retain its history.')
                key = 'invoice_settlement_reversal:' + voucher.id
                request_token = token(key)
                if st.form_submit_button('Request settlement reversal'):
                    if not confirmed:
                        st.warning('Confirm the reversal request before continuing.')
                    elif mutate(factory, lambda s: accounting.reverse(s, actor.id, voucher.id, on, reason, request_token), key):
                        st.rerun()
        else:
            st.info('This settlement is already rejected or cancelled and is excluded from approved balances.')


def invoice_correction_controls(factory, actor, invoice_id):
    import hashlib
    from decimal import Decimal
    from nova.models import InvoiceCorrection, User
    from nova.services import invoice_corrections as corrections

    with factory() as session:
        invoice = session.get(Invoice, invoice_id)
        original = session.get(Voucher, invoice.voucher_id)
        current = corrections.invoice_snapshot(session, invoice)
        requests = session.scalars(select(InvoiceCorrection).where(InvoiceCorrection.invoice_id == invoice_id)
                                   .order_by(InvoiceCorrection.created_at.desc(), InvoiceCorrection.id.desc())).all()
        names = {u.id: u.name for u in session.scalars(select(User)).all()}
        voucher_ids = [r.voucher_id for r in requests if r.voucher_id]
        voucher_names = {v.id: v.number for v in session.scalars(select(Voucher).where(Voucher.id.in_(voucher_ids))).all()} if voucher_ids else {}
        cancellation = session.scalar(select(Voucher.id).where(Voucher.reversal_of == original.id,
                                                               Voucher.status != 'Rejected').limit(1))
    pending_request = next((r for r in requests if r.status == 'Pending'), None)
    if pending_request:
        st.warning('An invoice correction is awaiting approval. The existing approved values remain in effect; settle or cancel the invoice after this request is resolved.')
    if requests:
        with st.expander('Invoice correction history', expanded=bool(pending_request)):
            table(pd.DataFrame([{'Request ID': r.id, 'Effective Date': str(r.effective_on), 'Status': r.status,
                                 'Requested By': names.get(r.created_by, r.created_by), 'Requested At (UTC)': str(r.created_at),
                                 'Reason': r.reason, 'Reviewed By': names.get(r.reviewed_by, '') if r.reviewed_by else '',
                                 'Reviewed At (UTC)': str(r.reviewed_at or ''), 'Review / Rejection Reason': r.review_reason,
                                 'Adjustment Voucher': voucher_names.get(r.voucher_id, '')} for r in requests]),
                  'Invoice Correction History', key='invoice_correction_history_table:' + invoice_id)
            selected = choose('Correction request details',
                              {r.id: f'{r.created_at} UTC · {r.status} · effective {r.effective_on}' for r in requests},
                              key='invoice_correction_history:' + invoice_id + ':' + (pending_request.id if pending_request else 'history'))
            request = next(r for r in requests if r.id == selected)
            try:
                before, after = json.loads(request.before_data), json.loads(request.after_data)
                if not isinstance(before, dict) or not isinstance(after, dict):
                    raise ValueError

                def display_value(field, value):
                    if field == 'amount':
                        return f'{Decimal(value) / 100:,.2f}'
                    if field == 'items':
                        return '\n'.join(f'{n}. {item["description"]} · PKR {Decimal(item["amount"]) / 100:,.2f}'
                                         for n, item in enumerate(value, 1)) or 'No item rows'
                    return str(value)

                changes = [{'Field': label, 'Before': display_value(field, before[field]),
                            'Proposed / Approved': display_value(field, after[field])}
                           for field, label in [('reference', 'Invoice reference'), ('due', 'Due date'), ('amount', 'Invoice total (PKR)'),
                                                ('description', 'Description'), ('items', 'Item rows')]
                           if before[field] != after[field]]
                st.caption('Saved values for this request. Pending or rejected proposals are not included in approved invoice balances.')
                st.dataframe(pd.DataFrame(changes, columns=['Field', 'Before', 'Proposed / Approved']), hide_index=True, width='stretch')
            except (TypeError, ValueError, KeyError):
                st.error('The saved correction details could not be displayed. An authorized reviewer can reject the request and ask for a new submission.')
            if request.status == 'Pending' and can(actor, 'approve'):
                if request.created_by == actor.id:
                    st.info('Another authorized user must review your invoice correction.')
                else:
                    with st.form('review_invoice_correction:' + request.id):
                        decision = st.selectbox('Correction decision', ['Approve', 'Reject'])
                        reason = st.text_area('Review / rejection reason', help='A reason is required when rejecting a correction.')
                        confirmed = st.checkbox('I have reviewed the original and proposed values.')
                        if st.form_submit_button('Submit correction decision', type='primary'):
                            if not confirmed:
                                st.warning('Confirm that you reviewed the values before submitting a decision.')
                            elif mutate(factory, lambda s: corrections.decide_correction(s, actor.id, request.id, decision == 'Approve', reason)):
                                st.rerun()
    if can(actor, 'entry') and invoice.status == 'Active' and original.status == 'Posted' and not pending_request:
        if cancellation:
            st.info('Resolve the invoice cancellation before requesting a correction.')
        else:
            with st.expander('Request invoice correction'):
                st.caption(f'Original invoice date: {invoice.date}. Its posting and permanent invoice ID are retained. Resolve pending settlements or reversals before submitting a correction.')
                signature = hashlib.sha256(json.dumps(current, sort_keys=True).encode('utf-8')).hexdigest()[:12]
                with st.form('request_invoice_correction:' + invoice_id + ':' + signature):
                    reference = st.text_input('Corrected invoice reference', current['reference'])
                    on = st.date_input('Correction effective date', business_today())
                    due = st.date_input('Corrected due date', invoice.due)
                    amount = st.text_input('Corrected invoice total (PKR)', f'{Decimal(current["amount"]) / 100:.2f}')
                    description = st.text_area('Corrected description', current['description'])
                    item_frame = pd.DataFrame([{'Description': item['description'], 'Amount (PKR)': f'{Decimal(item["amount"]) / 100:.2f}'}
                                               for item in current['items']] or [{'Description': '', 'Amount (PKR)': '0'}])
                    st.caption('Optional item rows must total the corrected invoice amount. Remove all item rows if you want to use only the invoice description.')
                    edited = st.data_editor(item_frame, num_rows='dynamic', hide_index=True, width='stretch',
                                            key='invoice_correction_items:' + invoice_id + ':' + signature)
                    reason = st.text_area('Reason for invoice correction')
                    key = 'invoice_correction_request:' + invoice_id
                    request_token = token(key)
                    if st.form_submit_button('Submit correction for approval', type='primary'):
                        if mutate(factory, lambda s: corrections.request_correction(s, actor.id, invoice_id, on, reference, due,
                                                                                   amount, description, reason, request_token,
                                                                                   items=invoice_rows(edited)), key):
                            st.rerun()
    return bool(pending_request)


def invoices(factory, actor):
    st.header('Purchase, sale, and dealer invoices')
    project_opts = options(factory, Project, lambda p: p.name)
    from nova.services.reports import invoice_balances
    with factory() as session:
        frame = invoice_balances(session)
        pending = invoice_balances(session, voucher_status='Pending')
        # Only approved, active invoices can be settled; rejected invoices stay in history but are not offered.
        records = session.scalars(select(Invoice).join(Voucher, Invoice.voucher_id == Voucher.id)
                                  .where(Invoice.status == 'Active', Voucher.status == 'Posted').order_by(Invoice.date.desc())).all()
        from nova.models import InvoiceCorrection
        correction_queue = session.execute(select(InvoiceCorrection, Invoice, Party)
                                            .join(Invoice, InvoiceCorrection.invoice_id == Invoice.id)
                                            .join(Party, Invoice.party_id == Party.id)
                                            .where(InvoiceCorrection.status == 'Pending')
                                            .order_by(InvoiceCorrection.created_at)).all()
    table(frame, 'Invoice Balances', hide=['Invoice ID'])
    if correction_queue:
        st.subheader('Invoice corrections awaiting approval')
        st.caption('Open the matching invoice below to review its proposed changes. Existing approved values remain in effect until approval.')
        table(pd.DataFrame([{'Reference': i.reference, 'Party': p.name, 'Type': i.kind,
                             'Correction Date': str(r.effective_on), 'Reason': r.reason, 'Status': r.status}
                            for r, i, p in correction_queue]), 'Pending Invoice Corrections')
    if not pending.empty:
        st.subheader('Invoices awaiting approval')
        st.caption('Not included in the balances above until approved.')
        table(pending.drop(columns=['Paid', 'Outstanding']), 'Pending Invoices', hide=['Invoice ID'])
    with factory() as session:
        history = session.execute(select(Invoice, Voucher, Party).join(Voucher, Invoice.voucher_id == Voucher.id).join(Party, Invoice.party_id == Party.id)
                                  .order_by(Invoice.date.desc())).all()
    table(pd.DataFrame([{'Invoice No.': v.number, 'Reference': i.reference, 'Party': p.name, 'Type': i.kind,
                         'Date': str(i.date), 'Amount': rupees(i.amount), 'Status': 'Rejected / Cancelled' if i.status == 'Rejected' else v.status}
                        for i, v, p in history]), 'Invoice History')
    if history:
        selected = choose('Open / print invoice', {i.id: f'{v.number} · {i.reference} · {p.name}' for i, v, p in history}, key='invoice_open')
        obj, v, party = next((i, v, p) for i, v, p in history if i.id == selected)
        from nova.documents import invoice_pdf
        with factory() as session:
            document = invoice_pdf(session, obj.id)
        st.download_button('Download / Print invoice PDF', document, f'{v.number}.pdf', 'application/pdf')
        st.caption(f'Permanent invoice ID: {obj.id} · Voucher ID: {v.id}')
        invoice_settlements(factory, actor, obj.id)
        correction_pending = invoice_correction_controls(factory, actor, obj.id)
        if can(actor, 'entry'):
            from nova.services import records as controls
            if v.status == 'Pending':
                with st.expander('Edit pending invoice'):
                    with st.form('editinvoice:' + obj.id):
                        reference = st.text_input('Invoice reference', obj.reference)
                        on = st.date_input('Invoice date', obj.date)
                        due = st.date_input('Invoice due date', obj.due)
                        amount = st.text_input('Invoice amount (PKR)', str(rupees(obj.amount)))
                        description = st.text_input('Invoice description', obj.description)
                        from nova.models import InvoiceItem
                        with factory() as s:
                            existing_items = s.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == obj.id).order_by(InvoiceItem.sequence)).all()
                        item_frame = pd.DataFrame([{'Description': i.description, 'Amount (PKR)': str(rupees(i.amount))} for i in existing_items] or [{'Description': '', 'Amount (PKR)': '0'}])
                        edited_items = st.data_editor(item_frame, num_rows='dynamic', hide_index=True, width='stretch', key='invoice_edit_items:' + obj.id)
                        if st.form_submit_button('Save invoice changes'):
                            if mutate(factory, lambda s: controls.edit_invoice(s, actor.id, obj.id, reference, on, due, amount, description, invoice_rows(edited_items))):
                                st.rerun()
                with st.expander('Delete / cancel pending invoice'):
                    with st.form('cancelinvoice:' + obj.id):
                        reason = st.text_input('Cancellation reason')
                        if st.form_submit_button('Cancel invoice'):
                            if mutate(factory, lambda s: controls.cancel_pending(s, actor.id, v.id, reason)):
                                st.rerun()
            elif v.status == 'Posted' and obj.status == 'Active' and not correction_pending:
                with st.expander('Cancel posted invoice through reversal'):
                    with st.form('voidinvoice:' + obj.id):
                        on = st.date_input('Cancellation date', business_today())
                        reason = st.text_input('Cancellation reason')
                        request_token = token('voidinvoice:' + obj.id)
                        if st.form_submit_button('Request invoice cancellation'):
                            mutate(factory, lambda s: controls.void_invoice(s, actor.id, obj.id, on, reason, request_token), 'voidinvoice:' + obj.id)
                st.caption('Posted invoices retain their IDs. A cancellation is an offsetting voucher requiring approval. Settled invoices require settlement reversals first.')
    if not can(actor, 'entry'):
        return
    kind = st.selectbox('New invoice type', ['Purchase', 'Sale', 'Dealer'])
    required_parties = ['Vendor', 'Contractor', 'Landowner'] if kind == 'Purchase' else ['Customer'] if kind == 'Sale' else ['Dealer']
    party_opts = options(factory, Party, lambda p: f'{p.name} · {p.kind}', Party.kind.in_(required_parties))
    account_types = ['Expense', 'Asset'] if kind == 'Purchase' else ['Income'] if kind == 'Sale' else ['Expense']
    account_opts = options(factory, Account, lambda a: f'{a.code} · {a.name}',
                           Account.kind.in_(account_types) & (Account.is_group == False) & (Account.is_cash == False) & Account.code.not_in(['1200']))
    with st.expander('New invoice'):
        with st.form('new_invoice'):
            project = choose('Project', project_opts)
            party = choose('Party', party_opts)
            posting = choose('Expense / asset / income account', account_opts)
            c1, c2 = st.columns(2)
            reference = c1.text_input('Invoice reference')
            amount = c2.text_input('Invoice amount (PKR)', '0')
            on = c1.date_input('Invoice date', business_today())
            due = c2.date_input('Due date', business_today() + timedelta(days=30))
            description = st.text_input('Description', key='new_invoice_description')
            st.caption('Optional item rows: use the grid plus/delete controls. Their total must match the invoice amount.')
            item_frame = st.data_editor(pd.DataFrame([{'Description': '', 'Amount (PKR)': '0'}]), num_rows='dynamic', hide_index=True, width='stretch', key='new_invoice_items')
            attachment = st.file_uploader('Invoice document', type=['pdf', 'png', 'jpg', 'jpeg'])
            request_token = token('invoice')
            if st.form_submit_button('Submit invoice', type='primary') and project and party and posting:
                mutate(factory, lambda s: sales.create_invoice(s, actor.id, project, party, kind, reference, on, due, amount, posting, description,
                                                               request_token, uploaded(attachment), items=invoice_rows(item_frame)), 'invoice')
        st.caption('Sale invoices recognize income. Do not invoice a booked unit again; booking revenue recognition needs a separately reviewed policy.')
    if records:
        with st.expander('Settle invoice / collect sale invoice'):
            cash_opts = options(factory, Account, lambda a: a.name, Account.is_cash == True)
            with st.form('settle_invoice'):
                invoice = choose('Invoice', {i.id: f'{i.kind} · {i.reference}' for i in records})
                cash = choose('Cash / bank account', cash_opts)
                on = st.date_input('Settlement date', business_today())
                amount = st.text_input('Settlement amount (PKR)', '0')
                request_token = token('settlement')
                if st.form_submit_button('Submit settlement') and invoice and cash:
                    mutate(factory, lambda s: sales.pay_invoice(s, actor.id, invoice, cash, on, amount, request_token), 'settlement')


def events(factory, actor, demo):
    st.header('Transfers and cancellations')
    with factory() as session:
        bookings = session.scalars(select(Booking).where(Booking.status == 'Active')).all()
        records = session.scalars(select(BookingEvent).order_by(BookingEvent.date.desc())).all()
        all_bookings = {b.id: b.number for b in session.scalars(select(Booking)).all()}
    parties = options(factory, Party, lambda p: p.name, Party.kind == 'Customer')
    table(pd.DataFrame([{'Request ID': e.id, 'Booking': all_bookings.get(e.booking_id, ''), 'Type': e.kind, 'Date': str(e.date),
                         'From': parties.get(e.old_party_id, ''), 'To': parties.get(e.new_party_id, ''), 'Reason': e.reason, 'Status': e.status} for e in records]), 'Booking Events')
    st.info('Pilot policy: transfers move the remaining receivable and booking obligation to the new customer. Cancellation creates a full refund payable for approved receipts; paying the refund is a separate payment voucher. No automatic fees or commission clawback.')
    if can(actor, 'entry') and bookings:
        with st.expander('New transfer / cancellation request'):
            kind = st.selectbox('Request type', ['Transfer', 'Cancellation'])
            with st.form('event_request'):
                booking = choose('Booking', {b.id: b.number for b in bookings})
                new_party = choose('New customer', parties, optional=True) if kind == 'Transfer' else None
                on = st.date_input('Effective date', business_today())
                reason = st.text_input('Reason')
                if st.form_submit_button('Submit request', type='primary'):
                    mutate(factory, lambda s: sales.request_event(s, actor.id, booking, kind, on, reason, new_party))
    editable = [e for e in records if e.status == 'Pending' and (e.created_by == actor.id or actor.role == 'Admin')]
    if can(actor, 'entry') and editable:
        from nova.services.records import edit_event
        with st.expander('Edit / delete pending request'):
            selected = choose('Request to edit', {e.id: f'{e.kind} · {all_bookings[e.booking_id]}' for e in editable}, key='event_edit_id')
            e = next(e for e in editable if e.id == selected)
            with st.form('editevent:' + e.id):
                on = st.date_input('Effective date', e.date)
                reason = st.text_input('Request reason', e.reason)
                party = choose('Transfer to customer', parties, optional=True, key='event_edit_party') if e.kind == 'Transfer' else None
                cancel = st.checkbox('Delete / cancel this pending request')
                if st.form_submit_button('Save request changes'):
                    if mutate(factory, lambda s: edit_event(s, actor.id, e.id, on, reason, party, cancel)):
                        st.rerun()
    pending = [e for e in records if e.status == 'Pending']
    if can(actor, 'approve') and pending:
        with st.form('decide_event'):
            event_id = choose('Pending request', {e.id: f'{e.kind} · {all_bookings[e.booking_id]}' for e in pending})
            decision = st.selectbox('Decision', ['Approve', 'Reject'])
            if st.form_submit_button('Apply decision'):
                mutate(factory, lambda s: sales.decide_event(s, actor.id, event_id, decision == 'Approve', demo))
