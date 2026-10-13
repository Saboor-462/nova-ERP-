from datetime import date, timedelta
from sqlalchemy import select
from nova.migrations import SCHEMA_VERSION
from nova.models import Account, Party, Project, Setting, Unit, User
from nova.services.accounting import account, approve, create_voucher, line
from nova.services.common import business_today
from nova.services.master import save_party, save_project, save_unit
from nova.services.sales import create_booking, create_invoice, pay_invoice, receive

ACCOUNTS = [
    ('100', 'Assets', 'Asset', None, True, False),
    ('1100', 'Cash in hand', 'Asset', '100', False, True),
    ('1110', 'Operating bank', 'Asset', '100', False, True),
    ('1200', 'Customer receivables', 'Asset', '100', False, False),
    ('1300', 'Project inventory / development assets', 'Asset', '100', False, False),
    ('200', 'Liabilities', 'Liability', None, True, False),
    ('2000', 'Vendor / contractor payable', 'Liability', '200', False, False),
    ('2100', 'Customer booking advances / obligations', 'Liability', '200', False, False),
    ('2200', 'Customer refunds payable', 'Liability', '200', False, False),
    ('2300', 'Dealer commission payable', 'Liability', '200', False, False),
    ('300', 'Equity', 'Equity', None, True, False),
    ('3000', 'Owner capital', 'Equity', '300', False, False),
    ('400', 'Income', 'Income', None, True, False),
    ('4000', 'Recognized sales / service income', 'Income', '400', False, False),
    ('500', 'Expenses', 'Expense', None, True, False),
    ('5000', 'Project expenses', 'Expense', '500', False, False),
    ('5100', 'Office expenses', 'Expense', '500', False, False),
    ('5200', 'Dealer commission expense', 'Expense', '500', False, False),
]


def bootstrap(session, mode='demo', admin_email='', sample=True):
    if mode == 'demo' and session.bind.dialect.name != 'sqlite':
        raise ValueError('Sample data is only seeded into the local SQLite demo database.')
    if not session.get(Setting, 'schema_version'):
        session.add(Setting(key='schema_version', value=SCHEMA_VERSION))
    if not session.scalar(select(Account.id).limit(1)):
        ids = {}
        for code, name, kind, parent, is_group, is_cash in ACCOUNTS:
            obj = Account(code=code, name=name, kind=kind, parent_id=ids.get(parent), is_group=is_group, is_cash=is_cash)
            session.add(obj)
            session.flush()
            ids[code] = obj.id
    if not sample:
        if mode == 'production' and admin_email:
            if '@' not in admin_email:
                raise ValueError('Set a valid ADMIN_EMAIL for production initialization.')
            if not session.scalar(select(User.id).where(User.email == admin_email)):
                session.add(User(email=admin_email, name='Administrator', role='Admin'))
        from nova.services.records import ensure_account_groups
        ensure_account_groups(session)
        if not session.get(Setting, 'demo_seed_complete'):
            session.add(Setting(key='demo_seed_complete', value='1'))
        return
    if mode == 'production':
        if not admin_email or '@' not in admin_email:
            raise ValueError('Set ADMIN_EMAIL before production initialization.')
        if not session.scalar(select(User.id).limit(1)):
            session.add(User(email=admin_email, name='Administrator', role='Admin'))
        return
    if session.get(Setting, 'demo_seed_complete') or session.scalar(select(Project.id).limit(1)):
        return
    users = {}
    for role in ('Admin', 'Accountant', 'Approver', 'Sales', 'Viewer'):
        obj = User(email=f'{role.lower()}@demo.local', name=f'Demo {role}', role=role)
        session.add(obj)
        session.flush()
        users[role] = obj.id
    actor = users['Admin']
    project = save_project(session, actor, number='NOVA-01', name='Nova Business Center — SAMPLE', owner='Sample Company',
                           area='Multan', description='Fictional test records, not extracted financial balances.', terms='Pilot installment policy.')
    customers = [save_party(session, actor, kind='Customer', name=f'Sample Customer {i}', phone='0300-0000000', city='Multan') for i in range(1, 4)]
    vendor = save_party(session, actor, kind='Vendor', name='Sample Building Supplies')
    dealer = save_party(session, actor, kind='Dealer', name='Sample Dealer')
    save_party(session, actor, kind='Landowner', name='Sample Landowner')
    units = [save_unit(session, actor, project_id=project.id, number=f'S-{i:02}', price='5000000', area='500 sq ft',
                       floor='Ground' if i <= 3 else 'First', category='Commercial', feature='Corner' if i == 1 else 'Standard') for i in range(1, 7)]
    today = business_today()
    booked_on = today - timedelta(days=100)
    capital = create_voucher(session, actor, project.id, booked_on, 'Journal', 'Sample opening capital',
                              [line(account(session, '1100'), debit=200_000_000), line(account(session, '1110'), debit=1_000_000_000),
                               line(account(session, '3000'), credit=1_200_000_000)], 'seed:capital')
    approve(session, actor, capital.id, demo=True)
    for i in range(2):
        booking = create_booking(session, actor, units[i].id, customers[i].id, booked_on, '5000000', '1000000', 8,
                                  booked_on + timedelta(days=30), f'seed:booking:{i}', dealer.id, '100000')
        approve(session, actor, booking.voucher_id, demo=True)
        receipt = receive(session, actor, booking.id, account(session, '1110'), booked_on + timedelta(days=1),
                           '1500000' if i == 0 else '1000000', 'Sample customer collection', f'seed:receipt:{i}')
        approve(session, actor, receipt.id, demo=True)
    invoice = create_invoice(session, actor, project.id, vendor.id, 'Purchase', 'SAMPLE-INV-001', today - timedelta(days=10),
                               today + timedelta(days=20), '250000', account(session, '5000'), 'Sample materials expense', 'seed:invoice')
    approve(session, actor, invoice.voucher_id, demo=True)
    payment = pay_invoice(session, actor, invoice.id, account(session, '1110'), today, '100000', 'seed:payment')
    approve(session, actor, payment.id, demo=True)
    create_invoice(session, actor, project.id, vendor.id, 'Purchase', 'SAMPLE-INV-002', today, today + timedelta(days=30),
                   '75000', account(session, '5100'), 'Sample invoice waiting for approval', 'seed:pending-invoice')
