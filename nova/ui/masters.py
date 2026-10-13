from datetime import date
import pandas as pd
import streamlit as st
from sqlalchemy import select
from nova.models import Account, Lead, Party, Project, Unit
from nova.services import master
from nova.services.common import business_today, rupees
from nova.ui.common import can, choose, mutate, options, table


def delete_form(factory, actor, model, records):
    if not can(actor, 'master') or not records:
        return
    from nova.services.records import delete_master
    with st.expander('Delete unused record'):
        with st.form(f'delete:{model.__name__}'):
            selected = choose('Record to delete', {r.id: getattr(r, 'name', getattr(r, 'number', r.id)) for r in records}, key=f'deleteselect:{model.__name__}')
            confirmed = st.checkbox('Delete this unused record. Linked financial records must be retained.')
            if st.form_submit_button('Delete record') and confirmed:
                if mutate(factory, lambda s: delete_master(s, actor.id, model, selected)):
                    st.rerun()


def edit_form(factory, actor, model, records):
    if not can(actor, 'master') or not records:
        return
    fields = {Project: ['name', 'owner', 'area', 'description', 'terms'],
              Party: ['name', 'relation', 'identity', 'phone', 'email', 'city', 'province', 'address'],
              Unit: ['category', 'floor', 'feature', 'area', 'reference', 'description']}[model]
    with st.expander('Edit record details'):
        selected = choose('Record to edit', {r.id: getattr(r, 'name', getattr(r, 'number', r.id)) for r in records}, key=f'edit:{model.__name__}')
        obj = next(r for r in records if r.id == selected)
        with st.form(f'editform:{model.__name__}:{selected}'):
            values = {}
            for field in fields:
                method = st.text_area if field in ('address', 'description', 'terms') else st.text_input
                values[field] = method(field.replace('_', ' ').title(), getattr(obj, field))
            if st.form_submit_button('Save changes'):
                if mutate(factory, lambda s: master.edit_master(s, actor.id, model, selected, values)):
                    st.rerun()


def projects(factory, actor):
    st.header('Projects')
    with factory() as session:
        records = session.scalars(select(Project).order_by(Project.number)).all()
    table(pd.DataFrame([{'Project ID': p.id, 'Number': p.number, 'Project': p.name, 'Owner': p.owner, 'Area': p.area, 'Description': p.description, 'Booking Terms': p.terms} for p in records]), 'Projects')
    edit_form(factory, actor, Project, records)
    delete_form(factory, actor, Project, records)
    if not can(actor, 'master'):
        return
    with st.expander('Add project'):
        with st.form('add_project', clear_on_submit=True):
            c1, c2 = st.columns(2)
            number = c1.text_input('Project number')
            name = c2.text_input('Project name')
            owner = c1.text_input('Owner')
            area = c2.text_input('Area / location')
            description = st.text_area('Description')
            terms = st.text_area('Booking terms')
            if st.form_submit_button('Save project', type='primary'):
                mutate(factory, lambda s: master.save_project(s, actor.id, number=number, name=name, owner=owner, area=area, description=description, terms=terms))


def parties(factory, actor):
    st.header('Clients, vendors, and dealers')
    kind = st.selectbox('Party type', ['All', 'Customer', 'Vendor', 'Contractor', 'Dealer', 'Landowner'])
    with factory() as session:
        query = select(Party).order_by(Party.name)
        if kind != 'All':
            query = query.where(Party.kind == kind)
        records = session.scalars(query).all()
    table(pd.DataFrame([{'Party ID': p.id, 'Role': p.kind, 'Name': p.name, 'S/O – W/O – D/O': p.relation, 'CNIC / Reference': p.identity,
                         'Phone': p.phone, 'Email': p.email, 'City': p.city, 'Province': p.province, 'Address': p.address} for p in records]), 'Parties')
    edit_form(factory, actor, Party, records)
    delete_form(factory, actor, Party, records)
    if not (can(actor, 'master') or can(actor, 'sales')):
        return
    with st.expander('Add party'):
        with st.form('party', clear_on_submit=True):
            roles = ['Customer'] if actor.role == 'Sales' else ['Customer', 'Vendor', 'Contractor', 'Dealer', 'Landowner']
            p_kind = st.selectbox('Client role', roles)
            c1, c2 = st.columns(2)
            name = c1.text_input('Name')
            relation = c2.text_input('S/O / W/O / D/O')
            identity = c1.text_input('CNIC / reference')
            phone = c2.text_input('Phone')
            email = c1.text_input('Email')
            city = c2.text_input('City')
            province = c1.text_input('Province')
            address = st.text_area('Address')
            if st.form_submit_button('Save party', type='primary'):
                mutate(factory, lambda s: master.save_party(s, actor.id, kind=p_kind, name=name, relation=relation, identity=identity,
                                                           phone=phone, email=email, city=city, province=province, address=address))


def accounts(factory, actor):
    st.header('Chart of accounts')
    with factory() as session:
        records = session.scalars(select(Account).order_by(Account.code)).all()
    lookup = {a.id: f'{a.code} · {a.name}' for a in records}
    table(pd.DataFrame([{'Code': a.code, 'Name': a.name, 'Type': a.kind, 'Parent': lookup.get(a.parent_id, ''),
                         'Group': a.is_group, 'Cash / Bank': a.is_cash, 'Active': a.active} for a in records]), 'Chart of Accounts')
    if not can(actor, 'master'):
        return
    delete_form(factory, actor, Account, records)
    if records:
        from nova.services.records import edit_account
        with st.expander('Edit account / deactivate'):
            selected = choose('Account to edit', lookup, key='edit_account_id')
            obj = next(a for a in records if a.id == selected)
            st.caption(f'Immutable account code: {obj.code} · Record ID: {obj.id}')
            with st.form('edit_account'):
                name = st.text_input('Account name', obj.name)
                parent_options = {None: 'No parent', **{a.id: lookup[a.id] for a in records if a.is_group and a.kind == obj.kind and a.id != obj.id}}
                parent = st.selectbox('New parent group', list(parent_options), index=list(parent_options).index(obj.parent_id) if obj.parent_id in parent_options else 0, format_func=parent_options.get, key=f'edit_account_parent:{obj.id}')
                active = st.checkbox('Active posting account', obj.active)
                if st.form_submit_button('Save account changes'):
                    if mutate(factory, lambda s: edit_account(s, actor.id, selected, name, parent, active)):
                        st.rerun()
    with st.expander('Add account'):
        with st.form('account', clear_on_submit=True):
            c1, c2 = st.columns(2)
            code = c1.text_input('Account code', help='Leave blank for AC-0001 style numbering. Existing codes never change.')
            name = c2.text_input('Account name')
            kind = c1.selectbox('Account type', ['Asset', 'Liability', 'Equity', 'Income', 'Expense'])
            parent = choose('Parent group', {a.id: lookup[a.id] for a in records if a.is_group}, optional=True)
            group = c1.checkbox('Group account (no direct postings)')
            cash = c2.checkbox('Cash / bank account')
            if st.form_submit_button('Save account', type='primary'):
                mutate(factory, lambda s: master.save_account(s, actor.id, code=code, name=name, kind=kind, parent_id=parent, is_group=group, is_cash=cash))
    st.caption('Core account codes are stable because booking and invoice services use them. Opening balances use balanced journal vouchers.')


def units(factory, actor):
    st.header('Units and inventory')
    project_opts = options(factory, Project, lambda p: p.name)
    project_id = choose('Project filter', project_opts, optional=True)
    status = st.selectbox('Status filter', ['All', 'Available', 'Booked'])
    with factory() as session:
        query = select(Unit, Project).join(Project)
        if project_id:
            query = query.where(Unit.project_id == project_id)
        if status != 'All':
            query = query.where(Unit.status == status)
        records = session.execute(query.order_by(Unit.number)).all()
    frame = pd.DataFrame([{'Unit ID': u.id, 'Project': p.name, 'Unit': u.number, 'Category': u.category, 'Floor': u.floor,
                           'Feature': u.feature, 'Area': u.area, 'Price': rupees(u.price), 'Status': u.status, 'Reference': u.reference} for u, p in records])
    if not frame.empty:
        st.bar_chart(frame.groupby('Status').size())
    table(frame, 'Units')
    edit_form(factory, actor, Unit, [u for u, _ in records])
    delete_form(factory, actor, Unit, [u for u, _ in records])
    if not can(actor, 'master'):
        return
    with st.expander('Add unit'):
        with st.form('unit', clear_on_submit=True):
            project = choose('Project', project_opts, key='unit_project')
            c1, c2, c3 = st.columns(3)
            number = c1.text_input('Unit number')
            category = c2.selectbox('Type / category', ['Commercial', 'Residential', 'Plot', 'Office'])
            floor = c3.text_input('Floor', 'Ground')
            area = c1.text_input('Area and unit', placeholder='500 sq ft')
            price = c2.text_input('List price (PKR)', '0')
            feature = c3.text_input('Feature', 'Standard')
            reference = c1.text_input('Reference')
            description = st.text_area('Description')
            if st.form_submit_button('Save unit', type='primary') and project:
                mutate(factory, lambda s: master.save_unit(s, actor.id, project_id=project, number=number, category=category, floor=floor,
                                                          area=area, price=price, feature=feature, reference=reference, description=description))
    with st.expander('Update available unit price'):
        available = options(factory, Unit, lambda u: f'{u.number} · {project_opts.get(u.project_id, "")} · PKR {rupees(u.price):,.2f}', Unit.status == 'Available')
        with st.form('unit_price'):
            unit_id = choose('Available unit', available)
            price = st.text_input('New price (PKR)', '0')
            if st.form_submit_button('Update price') and unit_id:
                mutate(factory, lambda s: master.set_unit_price(s, actor.id, unit_id, price))


def leads(factory, actor):
    st.header('CRM / Leads')
    project_opts = options(factory, Project, lambda p: p.name)
    with factory() as session:
        records = session.scalars(select(Lead).order_by(Lead.next_followup)).all()
    table(pd.DataFrame([{'Lead': l.name, 'Phone': l.phone, 'Project': project_opts.get(l.project_id, ''), 'Stage': l.stage,
                         'Next Follow-up': l.next_followup.isoformat(), 'Notes': l.notes} for l in records]), 'Leads')
    if not (can(actor, 'master') or can(actor, 'sales')):
        return
    delete_form(factory, actor, Lead, records)
    with st.expander('New lead'):
        with st.form('new_lead', clear_on_submit=True):
            name = st.text_input('Lead name')
            phone = st.text_input('Contact phone')
            project = choose('Project', project_opts)
            followup = st.date_input('Next follow-up', business_today())
            notes = st.text_area('Notes')
            if st.form_submit_button('Save lead') and project:
                mutate(factory, lambda s: master.save_lead(s, actor.id, name=name, phone=phone, project_id=project, next_followup=followup, notes=notes))
    if records:
        with st.expander('Update lead'):
            with st.form('update_lead'):
                lead_id = choose('Lead', {l.id: f'{l.name} · {l.phone}' for l in records})
                stage = st.selectbox('Stage', ['New', 'Contacted', 'Interested', 'Booked', 'Lost'])
                notes = st.text_area('Updated notes')
                followup = st.date_input('Next follow-up date', business_today())
                if st.form_submit_button('Update lead'):
                    mutate(factory, lambda s: master.update_lead(s, actor.id, lead_id, stage, notes, followup))
