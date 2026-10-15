from datetime import date
import pandas as pd
import streamlit as st
from sqlalchemy import select
from nova.models import Account, Party, Project, Unit, Voucher
from nova.services import reports
from nova.services.common import business_today, rupees
from nova.ui.common import choose, md_escape, options, table

REPORTS = ['Trial Balance', 'Trial Balance Detail', 'Balance Sheet', 'Balance Sheet Group', 'Profit & Loss', 'Profit & Loss Group',
           'General Ledger', 'Customer Ledger', 'Party Ledger', 'Dealer Ledger', 'Landowner Ledger', 'Cash In / Out',
           'Expense Report', 'Sales Summary', 'Sales Detailed', 'Installment Report', 'Installment Client-wise',
           'Installment Defaulters', 'Invoice Balances', 'Inventory', 'Dealer Commission Summary', 'Project Financial Summary', 'Financial Year Summary', 'Consolidated Balance Sheet', 'Trial Balance Group']


def filters(factory, prefix):
    from nova.models import FinancialYear
    project_opts = options(factory, Project, lambda p: p.name)
    with factory() as session:
        years = session.scalars(select(FinancialYear).order_by(FinancialYear.starts.desc())).all()
    selected = st.selectbox('Financial year', ['Custom dates'] + [y.name for y in years], key=f'{prefix}:year')
    fy = next((y for y in years if y.name == selected), None)
    if fy:
        st.caption(f'Audit status: {fy.audit_status} · Auditor: {md_escape(fy.auditor) or "Not recorded"}')
    today = business_today()
    year = today.year if today.month >= 7 else today.year - 1
    c1, c2, c3 = st.columns(3)
    with c1:
        project = choose('Project', project_opts, optional=True, key=f'{prefix}:project')
    start = c2.date_input('From', fy.starts if fy else date(year, 7, 1), key=f'{prefix}:start:{selected}')
    end = c3.date_input('To / As of', min(fy.ends, today) if fy else today, key=f'{prefix}:end:{selected}')
    if start > end:
        st.error('The From date must be on or before the To date.')
        st.stop()
    return project, start, end


def dashboard(factory, actor):
    import html
    from nova.branding import brand_header
    from nova.services.overview import diagnostics, hierarchy, project_summary
    brand_header('Business overview', 'Property inventory, collections, and approved financial balances')
    project, start, end = filters(factory, 'dashboard')
    view = st.radio('Dashboard view', ['Project dashboard', 'Balance sheet dashboard', 'Consolidated financial dashboard'], horizontal=True)
    show_amounts = st.toggle('Show amounts', value=True, key='dashboard_show_amounts')

    st.markdown(
        '''<style>
        .nova-dashboard-card {
            background: linear-gradient(135deg, #13283d, #1d3c56);
            border: 1px solid #cba33455;
            border-top: 3px solid #cba334;
            border-radius: 14px;
            padding: 20px;
            min-height: 154px;
            margin-bottom: 16px;
            box-sizing: border-box;
        }

        .nova-dashboard-card-label {
            color: #dce6ef;
            font-size: .88rem;
            line-height: 1.5;
            margin-bottom: 14px;
            overflow-wrap: anywhere;
        }

        .nova-dashboard-card-unit {
            color: #e4c36f;
            font-size: .72rem;
            font-weight: 600;
            letter-spacing: .08em;
            min-height: 18px;
        }

        .nova-dashboard-card-value {
            color: #ffffff;
            font-size: clamp(1.15rem, 2vw, 1.85rem);
            font-weight: 700;
            line-height: 1.4;
            font-variant-numeric: tabular-nums;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        </style>''',
        unsafe_allow_html=True,
    )

    def amount_card(container, label, value, count=False):
        unit = '' if count or not show_amounts else 'PKR'
        displayed = f'{value:,}' if count else f'{rupees(value):,.2f}' if show_amounts else 'Hidden'
        container.markdown(
            '<div class="nova-dashboard-card">'
            f'<div class="nova-dashboard-card-label">{html.escape(label)}</div>'
            f'<div class="nova-dashboard-card-unit">{unit}</div>'
            f'<div class="nova-dashboard-card-value">{html.escape(displayed)}</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    with factory() as session:
        summary = project_summary(session, None if view.startswith('Consolidated') else project, start, end)
        alerts = diagnostics(session, None if view.startswith('Consolidated') else project, end)
        pending_query = select(Voucher).where(Voucher.status == 'Pending')
        if project and not view.startswith('Consolidated'):
            pending_query = pending_query.where(Voucher.project_id == project)
        pending = len(session.scalars(pending_query).all())
        bs, pnl = reports.financials(session, None if view.startswith('Consolidated') else project, start, end, paisa=True)
        tree = hierarchy(session, None if view.startswith('Consolidated') else project, end=end, balance_sheet=True)
    if pending:
        st.error(f'{pending} voucher(s) awaiting approval. Pending entries are excluded from posted balances.')
    for _, alert in alerts.iterrows():
        difference = f'PKR {rupees(int(alert["Difference (paisa)"])):,.2f}' if show_amounts else 'Amount hidden'
        st.error(f'{alert["Alert"]}: {difference}. {alert["Action"]}')
    if not summary.empty:
        keys = ['Cash & Bank', 'Receivables', 'Payables', 'Booked Sales', 'Booking Collections', 'Revenue', 'Expenses', 'Approved Bookings']
        for offset in (0, 4):
            cols = st.columns(4)
            for col, key in zip(cols, keys[offset:offset+4]):
                value = int(summary[key].sum())
                amount_card(col, key, value, count=key == 'Approved Bookings')
        if view == 'Project dashboard':
            st.subheader('Inventory and booking status')
            st.bar_chart(summary.set_index('Project')[['Available', 'Reserved / Booked']])
        else:
            assets = int(bs.loc[bs['Type'] == 'Asset', 'Amount'].sum())
            liabilities = int(bs.loc[bs['Type'] == 'Liability', 'Amount'].sum())
            equity = int(bs.loc[bs['Type'] == 'Equity', 'Amount'].sum())
            cols = st.columns(3)
            for col, label, value in zip(cols, ['Total assets', 'Total liabilities', 'Total equity'], [assets, liabilities, equity]):
                amount_card(col, label, value)
            hierarchy_shown = reports.to_rupees(tree[['Account Code', 'Account', 'Type', 'Level', 'Group', 'Amount']])
            if not show_amounts:
                hierarchy_shown['Amount'] = 'Hidden'
            table(hierarchy_shown, 'Account Hierarchy', 'dashboard_hierarchy')
        monetary = ['Booked Sales', 'Booking Collections', 'Receivables', 'Payables', 'Cash & Bank', 'Revenue', 'Expenses', 'Cash Inflow', 'Cash Outflow']
        shown = summary.copy()
        for col in monetary:
            shown[col] = shown[col].map(rupees) if show_amounts else 'Hidden'
        table(shown, 'Project Financial Summary', 'dashboard_project_summary')
    else:
        st.info('Create your first project under Projects. No fictional business data is added automatically.')
    st.caption('Booked sales, received cash, and recognized revenue are different measures. Booking revenue is recognized only through the approved accounting policy. Inventory and booking ownership are current operational records.')


def report_page(factory, actor):
    name = st.selectbox('Report', REPORTS)
    st.header(name)
    project, start, end = filters(factory, 'report')
    if name == 'Consolidated Balance Sheet':
        project = None
        st.caption('Consolidated balances include every project.')
    with factory() as session:
        if name.startswith('Trial Balance'):
            frame = reports.trial_balance(session, project, start, end, paisa=True)
            if name in ('Trial Balance Detail', 'Trial Balance Group'):
                from nova.services.overview import hierarchy
                frame = hierarchy(session, project, start, end).drop(columns=['Amount'])
                st.caption('Group rows are subtotals. Do not add group rows and their children together.')
            st.write(f'Activity debit: **{rupees(int(frame.loc[frame["Group"] == False, "Debit"].sum() if "Group" in frame else frame["Debit"].sum())):,.2f}** · Activity credit: **{rupees(int(frame.loc[frame["Group"] == False, "Credit"].sum() if "Group" in frame else frame["Credit"].sum())):,.2f}**')
        elif name.startswith('Balance Sheet') or name.startswith('Profit & Loss') or name == 'Consolidated Balance Sheet':
            bs, pnl = reports.financials(session, project, start, end, paisa=True)
            frame = bs if name.startswith('Balance') or name == 'Consolidated Balance Sheet' else pnl
            if name.startswith('Balance') or name == 'Consolidated Balance Sheet':
                totals = [int(bs.loc[bs['Type'] == k, 'Amount'].sum()) for k in ('Asset', 'Liability', 'Equity')]
                for col, label, amount in zip(st.columns(3), ['Total assets', 'Total liabilities', 'Total equity'], totals):
                    col.metric(label, f'PKR {rupees(amount):,.2f}')
                if totals[0] != totals[1] + totals[2]:
                    st.error(f'Balance sheet mismatch: PKR {rupees(totals[0] - totals[1] - totals[2]):,.2f}')

            if name == 'Balance Sheet Group':
                from nova.services.overview import hierarchy
                frame = hierarchy(session, project, end=end, balance_sheet=True)[['Account Code', 'Account', 'Type', 'Level', 'Group', 'Amount']]
            elif name.endswith('Group'):
                from nova.services.overview import hierarchy
                frame = hierarchy(session, project, start, end)
                frame = frame[frame['Type'].isin(['Income', 'Expense'])].copy()
                frame['Amount'] = frame.apply(lambda r: int(r['Credit'] - r['Debit']) if r['Type'] == 'Income' else int(r['Debit'] - r['Credit']), axis=1)
                frame = frame[['Account Code', 'Account', 'Type', 'Level', 'Group', 'Amount']]
            st.caption('Balance sheet is cumulative through the As of date. Profit & loss uses the selected From–To period.')
        elif 'Ledger' in name:
            kind = {'Customer Ledger': 'Customer', 'Dealer Ledger': 'Dealer', 'Landowner Ledger': 'Landowner'}.get(name)
            parties = session.scalars(select(Party).where(Party.kind == kind) if kind else select(Party)).all()
            party = choose('Party / client', {p.id: f'{p.name} · {p.kind}' for p in parties}, optional=True, key='ledger_party')
            accounts = session.scalars(select(Account).where(Account.is_group == False).order_by(Account.code)).all()
            preferred = {'Customer Ledger': '1200', 'Dealer Ledger': '2300', 'Landowner Ledger': '2000'}.get(name)
            if preferred:
                acc = next(a.id for a in accounts if a.code == preferred)
                st.caption(f'Control account: {md_escape(next(a.name for a in accounts if a.id == acc))}')
            else:
                acc = choose('Account', {a.id: f'{a.code} · {a.name}' for a in accounts}, optional=False, key='ledger_account')
            frame = reports.ledger(session, project, start, end, acc, party, paisa=True)
            st.caption('Balance is debit-positive and credit-negative. Select the voucher in Vouchers to open its details.')
        elif name == 'Cash In / Out':
            frame = reports.cashflow(session, project, start, end, paisa=True)
        elif name == 'Expense Report':
            frame = pd.DataFrame([{'Date': v.date.isoformat(), 'Voucher': v.number, 'Account': a.name,
                                   'Description': v.description, 'Debit': l.debit, 'Credit': l.credit,
                                   'Net Expense': l.debit - l.credit} for l, v, a in reports.entries(session, project, start, end) if a.kind == 'Expense'])
        elif name.startswith('Installment') or name.startswith('Sales'):
            frame = reports.installments(session, project, end, paisa=True)
            st.caption('Schedules show current active ownership; paid amounts include approved receipts through the As of date. Historical ownership snapshots and surcharges are not computed in this pilot.')
            if name == 'Installment Defaulters':
                frame = frame[frame['Status'] == 'Overdue']
            elif name in ('Installment Client-wise', 'Sales Summary') and not frame.empty:
                from nova.services.overview import installment_summary
                frame = installment_summary(frame)
            elif name == 'Sales Detailed' and not frame.empty:
                frame = frame.groupby(['Project', 'Booking', 'Customer', 'Unit'], as_index=False)[['Amount', 'Paid', 'Outstanding']].sum()
                metadata = session.execute(select(Unit.number, Unit.floor, Unit.category, Unit.feature, Project.name).join(Project)).all()
                for number, floor, category, feature, pname in metadata:
                    mask = (frame['Unit'] == number) & (frame['Project'] == pname)
                    frame.loc[mask, ['Floor', 'Category', 'Feature']] = [floor, category, feature]
        elif name == 'Dealer Commission Summary':
            from nova.services.overview import dealer_commissions
            frame = dealer_commissions(session, project, end)
        elif name == 'Project Financial Summary':
            from nova.services.overview import project_summary
            frame = project_summary(session, project, start, end)
        elif name == 'Financial Year Summary':
            from nova.models import FinancialYear
            rows = []
            for y in session.scalars(select(FinancialYear).order_by(FinancialYear.starts)).all():
                _, pnl = reports.financials(session, project, y.starts, y.ends, paisa=True)
                rows.append({'Year': y.name, 'From': str(y.starts), 'To': str(y.ends), 'Audit Status': y.audit_status,
                             'Revenue': int(pnl.loc[pnl['Type'] == 'Income', 'Amount'].sum()),
                             'Expenses': int(pnl.loc[pnl['Type'] == 'Expense', 'Amount'].sum())})
            frame = pd.DataFrame(rows)
        elif name == 'Invoice Balances':
            frame = reports.invoice_balances(session, project, end, paisa=True)
            st.caption('Approved invoices only. Invoices awaiting approval are listed on the Invoices page; rejected invoices are excluded.')
        else:
            query = select(Unit, Project).join(Project)
            if project:
                query = query.where(Unit.project_id == project)
            frame = pd.DataFrame([{'Project': p.name, 'Unit': u.number, 'Category': u.category, 'Floor': u.floor,
                                   'Feature': u.feature, 'Area': u.area, 'Status': u.status, 'List Price': u.price} for u, p in session.execute(query).all()])
            st.caption('Inventory shows current status; date filters do not reconstruct historic inventory.')
    if name in ('Inventory', 'Sales Detailed') and not frame.empty:
        for column in ('Category', 'Floor', 'Feature', 'Status'):
            if column in frame:
                selected = st.selectbox(column + ' filter', ['All'] + sorted(frame[column].dropna().astype(str).unique()), key=f'reportfilter:{name}:{column}')
                if selected != 'All':
                    frame = frame[frame[column].astype(str) == selected]
    # Totals above were computed in paisa; convert once for display and export.
    table(reports.to_rupees(frame), name, key='report_' + name.replace(' ', '_'), hide=['Invoice ID', 'Voucher ID'])
