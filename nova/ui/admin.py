from datetime import date
from decimal import ROUND_HALF_UP, Decimal
import pandas as pd
import streamlit as st
from sqlalchemy import select
from nova.models import Account, Audit, Setting, User
from nova.services import imports, master, reports
from nova.services.common import ROLES, business_today, rupees
from nova.ui.common import can, choose, md_escape, mutate, options, table


def administration(factory, actor):
    st.header('Administration')
    if not can(actor, 'users'):
        st.info('Administrator access is required.')
        return
    with factory() as session:
        users = session.scalars(select(User).order_by(User.email)).all()
        closed = session.get(Setting, 'closed_through')
        audits = session.scalars(select(Audit).order_by(Audit.at.desc()).limit(1000)).all()
    table(pd.DataFrame([{'Email': u.email, 'Name': u.name, 'Role': u.role, 'Active': u.active} for u in users]), 'System Users')
    with st.expander('Add / update authorized user'):
        with st.form('save_user'):
            email = st.text_input('Authorized email')
            name = st.text_input('Display name')
            role = st.selectbox('Role', list(ROLES))
            active = st.checkbox('Active', True)
            password = st.text_input('Set/reset local password (12–128 characters; blank keeps existing)', type='password')
            if st.form_submit_button('Save user', type='primary'):
                def save(s):
                    user = master.save_user(s, actor.id, email, name, role, active)
                    if password:
                        from nova.services.security import set_password
                        set_password(s, actor.id, user.id, password)
                    return user
                mutate(factory, save)
    with st.expander('Invoice / voucher business header'):
        with factory() as session:
            current = {k: session.get(Setting, k).value if session.get(Setting, k) else '' for k in ('business_name', 'business_address', 'business_contact', 'business_footer')}
        with st.form('business_header'):
            name = st.text_input('Business name', current['business_name'] or 'NOVA BUSINESS CENTRE')
            address = st.text_area('Business address', current['business_address'])
            contact = st.text_input('Phone / email', current['business_contact'])
            footer = st.text_area('Print footer / terms', current['business_footer'])
            if st.form_submit_button('Save print header'):
                def save_header(s):
                    from nova.services.common import require
                    require(s, actor.id, 'users')
                    for key, value in [('business_name', name), ('business_address', address), ('business_contact', contact), ('business_footer', footer)]:
                        obj = s.get(Setting, key)
                        if obj:
                            obj.value = value
                        else:
                            s.add(Setting(key=key, value=value))
                    s.add(Audit(actor_id=actor.id, action='print_header_updated', entity='settings', entity_id='business_header', detail='Business print header updated'))
                mutate(factory, save_header)
    with st.expander('Close accounting period'):
        st.write('Closed through: ' + (closed.value if closed else 'No closed period'))
        st.caption('Closing is forward-only in the pilot. Pending entries must be resolved first; closed-period entries cannot be posted.')
        with st.form('close_period'):
            through = st.date_input('Close through', business_today())
            confirmed = st.checkbox('I have reviewed the reports and completed the backup for this period.')
            if st.form_submit_button('Close period') and confirmed:
                mutate(factory, lambda s: master.close_period(s, actor.id, through))
    st.subheader('Audit history')
    names = {u.id: u.name for u in users}
    st.caption('Showing the most recent 1,000 audit events. Application users cannot edit these records through the UI.')
    table(pd.DataFrame([{'At (UTC)': str(a.at), 'User': names.get(a.actor_id, a.actor_id), 'Action': a.action, 'Entity': a.entity,
                         'Record ID': a.entity_id, 'Detail': a.detail} for a in audits]), 'Audit History')


def bulk_entries(factory, actor):
    st.header('Bulk entries / Import vouchers')
    if not can(actor, 'entry'):
        st.info('Accounting entry permission is required.')
        return
    template = 'VoucherRef,Date,Project,AccountCode,PartyID,Description,Debit,Credit\nOPEN-001,2026-10-01,NOVA-01,1110,,Opening bank balance,100000,0\nOPEN-001,2026-10-01,NOVA-01,3000,,Opening capital,0,100000\n'
    st.download_button('Download import template', template, 'voucher_import_template.csv', 'text/csv')
    st.caption('Change the sample date/project before use. Rows with the same VoucherRef form one balanced voucher. Imports are atomic and create pending vouchers. Reusing a project/reference skips the existing voucher; it does not update it.')
    file = st.file_uploader('UTF-8 voucher CSV (up to 1,000 rows / 2 MB)', type=['csv'])
    if file:
        try:
            frame = imports.parse_csv(file.getvalue())
        except ValueError as exc:
            st.error(md_escape(exc))
            return
        st.dataframe(frame, hide_index=True, width='stretch')
        if st.button('Validate and import all', type='primary'):
            result = mutate(factory, lambda s: imports.import_vouchers(s, actor.id, frame))
            if result:
                st.write('Vouchers: ' + ', '.join(result))


def cash_bank(factory, actor):
    st.header('Cash / bank reconciliation')
    account_opts = options(factory, Account, lambda a: f'{a.code} · {a.name}', Account.is_cash == True)
    account_id = choose('Cash / bank account', account_opts)
    end = st.date_input('Statement date / As of', business_today())
    if not account_id:
        return
    with factory() as session:
        frame = reports.bankbook(session, account_id, end, paisa=True)
    if frame.empty:
        st.info('No posted entries for this account.')
        return
    book = int(frame['Debit'].sum() - frame['Credit'].sum())
    uncleared = frame.loc[frame['Cleared'] == False]
    adjustment = int(uncleared['Debit'].sum() - uncleared['Credit'].sum())
    statement_input = st.number_input('Closing bank statement balance (PKR, signed)', value=0.0, step=100.0, format='%.2f')
    statement = int((Decimal(str(statement_input)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    c1, c2, c3 = st.columns(3)
    c1.metric('Book balance', f'{rupees(book):,.2f}')
    c2.metric('Adjusted statement balance', f'{rupees(statement + adjustment):,.2f}')
    c3.metric('Difference', f'{rupees(book - statement - adjustment):,.2f}')
    if book - statement - adjustment:
        st.error('Reconciliation difference: review uncleared items, statement balance, and unentered charges.')
    table(reports.to_rupees(frame), 'Cash Bankbook', hide=['Line ID'])
    st.caption('Adjusted statement = statement balance + uncleared receipts − uncleared payments. Clear both legs of bank transfers individually. Enter bank charges/interest as vouchers first.')
    if can(actor, 'entry'):
        with st.form('clear_line'):
            selected = choose('Entry to clear / correct', {r['Line ID']: f'{r["Voucher"]} · Dr {rupees(r["Debit"]):,.2f} / Cr {rupees(r["Credit"]):,.2f}' for _, r in frame.iterrows()})
            on = st.date_input('Actual clearance date', end)
            reference = st.text_input('Statement reference')
            if st.form_submit_button('Save clearance'):
                mutate(factory, lambda s: reports.reconcile(s, actor.id, selected, on, reference))


def financial_years(factory, actor):
    from nova.models import FinancialYear
    from nova.services.records import save_year, delete_master
    st.header('Financial years and audit status')
    with factory() as session:
        years = session.scalars(select(FinancialYear).order_by(FinancialYear.starts.desc())).all()
    table(pd.DataFrame([{'Year': y.name, 'From': str(y.starts), 'To': str(y.ends), 'Audit Status': y.audit_status,
                         'Auditor': y.auditor, 'Audit Date': str(y.audited_on or ''), 'Notes': y.notes} for y in years]), 'Financial Years')
    st.caption('Audit status records an external review; the application does not certify an audit. Audited years block new dated entries until reopened for review.')
    if not can(actor, 'users'):
        return
    selected = choose('Add / edit year', {y.id: y.name for y in years}, optional=True, key='year_edit')
    y = next((y for y in years if y.id == selected), None)
    today = business_today()
    start_year = today.year if today.month >= 7 else today.year - 1
    with st.form('financial_year'):
        name = st.text_input('Year name', y.name if y else f'FY {start_year}-{start_year + 1}')
        starts = st.date_input('Year starts', y.starts if y else date(start_year, 7, 1))
        ends = st.date_input('Year ends', y.ends if y else date(start_year + 1, 6, 30))
        statuses = ['Not audited', 'In review', 'Audited']
        status = st.selectbox('Audit status', statuses, index=statuses.index(y.audit_status) if y else 0)
        auditor = st.text_input('Auditor / reviewer', y.auditor if y else '')
        audited_on = st.date_input('Audit completion date', y.audited_on if y else None)
        notes = st.text_area('Audit notes / reference', y.notes if y else '')
        if st.form_submit_button('Save financial year'):
            if mutate(factory, lambda s: save_year(s, actor.id, name, starts, ends, selected, status, auditor, audited_on, notes)):
                st.rerun()
    if y:
        confirmed = st.checkbox('Delete this unused, unaudited year')
        if st.button('Delete year') and confirmed:
            if mutate(factory, lambda s: delete_master(s, actor.id, FinancialYear, y.id)):
                st.rerun()
