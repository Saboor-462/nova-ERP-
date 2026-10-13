"""Regression tests for the audit fixes (AUDIT_REPORT.md). Temporary databases and fictional data only."""
from datetime import date, datetime, timedelta
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import zipfile
import pandas as pd
import pytest
import streamlit
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from streamlit.errors import StreamlitSecretNotFoundError
from streamlit.testing.v1 import AppTest
from nova import config
from nova.config import ROOT, ConfigError, settings, streamlit_secrets as real_streamlit_secrets
from nova.db import engine, initialize, make_engine, session_factory
from nova.diagnostics import log_failure, redact
from nova.migrations import SCHEMA_VERSION, MigrationError
from nova.models import Account, Audit, Booking, Invoice, Line, Party, Project, Setting, User, Voucher
from nova.seed import bootstrap
from nova.services import accounting, imports, master, reports, sales
from nova.services import common
from nova.services.common import BusinessError, business_today
from nova.ui.common import md_escape
from nova.ui.transactions import voucher_rows

V2_SCHEMA = Path(__file__).parent / 'fixtures' / 'schema_v2_sqlite.sql'
PG_URL = 'postgresql+psycopg://erp_user:Sup3rSecretPw@db.example.test:5432/erp?sslmode=require'


# ---------- 1. Configuration and demo isolation ----------

def test_default_configuration_is_local_demo():
    result = settings(environ={}, secrets={})
    assert result['mode'] == 'demo'
    assert config.is_demo_database(result['url'])


@pytest.mark.parametrize('environ, message', [
    ({'DATABASE_URL': PG_URL}, 'APP_MODE is not'),
    ({'APP_MODE': 'demo', 'DATABASE_URL': PG_URL}, 'Demo mode only runs'),
    ({'APP_MODE': 'demo', 'DATABASE_URL': 'sqlite:///C:/elsewhere/real.db'}, 'Demo mode only runs'),
    ({'APP_MODE': 'production'}, 'requires a PostgreSQL'),
    ({'APP_MODE': 'production', 'DATABASE_URL': 'sqlite:///x.db'}, 'requires a PostgreSQL'),
    ({'APP_MODE': 'production', 'DATABASE_URL': 'postgresql://'}, 'host and name'),
    ({'APP_MODE': 'staging'}, 'APP_MODE must be'),
    ({'APP_MODE': 'production', 'DATABASE_URL': PG_URL, 'ADMIN_EMAIL': 'not-an-email'}, 'ADMIN_EMAIL'),
])
def test_invalid_configuration_fails_without_revealing_credentials(environ, message):
    with pytest.raises(ConfigError, match=message) as info:
        settings(environ=environ, secrets={})
    assert 'Sup3rSecretPw' not in str(info.value) and 'erp_user' not in str(info.value)
    assert info.value.__cause__ is None


def test_streamlit_secrets_are_read_and_override_environment():
    result = settings(environ={'APP_MODE': 'demo'}, secrets={'APP_MODE': 'production', 'DATABASE_URL': PG_URL})
    assert result['mode'] == 'production' and result['url'] == PG_URL


class FakeSecrets:
    def __init__(self, outcome):
        self.outcome = outcome

    def get(self, key, default=None):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome.get(key, default)


def test_secrets_reader_handles_missing_valid_and_broken_files(monkeypatch):
    monkeypatch.setattr(streamlit, 'secrets', FakeSecrets(StreamlitSecretNotFoundError('No secrets.', error_id='no-secrets-found')))
    assert real_streamlit_secrets() == {}
    monkeypatch.setattr(streamlit, 'secrets', FakeSecrets({'erp': {'APP_MODE': 'production'}}))
    assert real_streamlit_secrets() == {'APP_MODE': 'production'}
    broken = StreamlitSecretNotFoundError('Bad TOML near password = "x"', error_id='failed-parsing-secrets-file')
    monkeypatch.setattr(streamlit, 'secrets', FakeSecrets(broken))
    with pytest.raises(ConfigError, match='could not be read') as info:
        real_streamlit_secrets()
    assert 'password' not in str(info.value)


def test_sample_seeding_refuses_postgresql():
    pg = create_engine(PG_URL)  # Never connects: the guard runs before any query.
    with Session(pg) as session, pytest.raises(ValueError, match='only seeded into the local SQLite'):
        bootstrap(session)
    pg.dispose()


def test_app_refuses_demo_mode_on_postgresql(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', PG_URL)
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=20).run()
    assert at.error and 'Configuration error' in at.error[0].value
    assert 'Sup3rSecretPw' not in at.error[0].value
    assert not at.sidebar.selectbox, 'Role switching must not be offered'


# ---------- 2. Invoice status and references ----------

def ids(session):
    return (session.scalar(select(Project.id)), session.scalar(select(Party.id).where(Party.kind == 'Vendor')),
            session.scalar(select(Party.id).where(Party.kind == 'Customer')), session.scalar(select(Party.id).where(Party.kind == 'Dealer')))


def test_rejected_invoice_is_kept_and_reference_can_be_reused(db):
    factory, actors = db
    today = business_today()
    with factory.begin() as s:
        project, vendor, _, _ = ids(s)
        first = sales.create_invoice(s, actors['Accountant'], project, vendor, 'Purchase', 'SUP-77', today, today, '500',
                                     accounting.account(s, '5000'), 'Wrong amount', 'inv:first')
        first_id, first_voucher = first.id, first.voucher_id
    with factory.begin() as s, pytest.raises(BusinessError, match='active invoice'):
        sales.create_invoice(s, actors['Accountant'], project, vendor, 'Purchase', 'SUP-77', today, today, '450',
                             accounting.account(s, '5000'), 'Duplicate', 'inv:duplicate')
    with factory.begin() as s:
        accounting.reject(s, actors['Approver'], first_voucher, 'Amount was wrong')
    with factory() as s:
        assert 'SUP-77' not in set(reports.invoice_balances(s)['Reference'])
        assert 'SUP-77' not in set(reports.invoice_balances(s, voucher_status='Pending')['Reference'])
    with factory.begin() as s:
        second = sales.create_invoice(s, actors['Accountant'], project, vendor, 'Purchase', 'SUP-77', today, today, '450',
                                      accounting.account(s, '5000'), 'Corrected', 'inv:second')
        second_voucher = second.voucher_id
    with factory() as s:
        old = s.get(Invoice, first_id)
        assert old.status == 'Rejected' and old.amount == 50000
        assert s.scalar(select(Audit.id).where(Audit.action == 'reject', Audit.entity_id == first_voucher))
        assert list(reports.invoice_balances(s, voucher_status='Pending')['Reference']).count('SUP-77') == 1
    with factory.begin() as s:
        accounting.approve(s, actors['Approver'], second_voucher)
    with factory() as s:
        frame = reports.invoice_balances(s)
        assert frame.loc[frame['Reference'] == 'SUP-77', 'Outstanding'].tolist() == [450.0]
    with factory.begin() as s, pytest.raises(BusinessError, match='Approve the invoice'):
        sales.pay_invoice(s, actors['Accountant'], first_id, accounting.account(s, '1110'), today, '1', 'pay:rejected')
    with pytest.raises(IntegrityError):  # The database still refuses two active invoices with one reference.
        with factory.begin() as s:
            s.execute(update(Invoice).where(Invoice.id == first_id).values(status='Active'))


def test_pending_invoices_are_not_outstanding_balances(db):
    factory, _ = db
    with factory() as s:
        assert 'SAMPLE-INV-002' not in set(reports.invoice_balances(s)['Reference'])
        pending = reports.invoice_balances(s, voucher_status='Pending')
        assert list(pending['Reference']) == ['SAMPLE-INV-002']


# ---------- 3. Pakistan business date ----------

def at_utc(monkeypatch, moment):
    monkeypatch.setattr(common, '_utcnow', lambda: datetime.fromisoformat(moment))


def test_business_date_turns_at_pakistan_midnight(db, monkeypatch):
    factory, actors = db
    at_utc(monkeypatch, '2026-10-10T18:59:59+00:00')
    assert business_today() == date(2026, 10, 10)
    with factory.begin() as s, pytest.raises(BusinessError, match='future'):
        common.check_date(s, date(2026, 10, 11))
    at_utc(monkeypatch, '2026-10-10T19:00:00+00:00')  # 00:00 PKT on 11 October
    assert business_today() == date(2026, 10, 11)
    with factory.begin() as s:
        common.check_date(s, date(2026, 10, 11))
        project = s.scalar(select(Project.id))
        accounting.create_voucher(s, actors['Accountant'], project, date(2026, 10, 11), 'Journal', 'Early morning PKT entry',
                                  [accounting.line(accounting.account(s, '1100'), debit=100),
                                   accounting.line(accounting.account(s, '3000'), credit=100)], 'pkt:midnight')


def test_sample_data_and_period_close_use_pakistan_date(tmp_path, monkeypatch):
    at_utc(monkeypatch, '2026-03-31T20:30:00+00:00')  # 1 April in Pakistan, still 31 March in UTC
    bind = make_engine(f'sqlite:///{tmp_path / "pkt.db"}')
    initialize(bind)
    factory = session_factory(bind)
    with factory.begin() as s:
        bootstrap(s)
    with factory() as s:
        invoice = s.scalar(select(Invoice).where(Invoice.reference == 'SAMPLE-INV-001'))
        assert invoice.date == date(2026, 4, 1) - timedelta(days=10)
        admin = s.scalar(select(User.id).where(User.role == 'Admin'))
    with factory.begin() as s, pytest.raises(BusinessError, match='future'):
        master.close_period(s, admin, date(2026, 4, 2))
    bind.dispose()


def test_no_server_local_dates_remain():
    sources = [p for p in (ROOT / 'nova').rglob('*.py')] + [ROOT / 'app.py']
    offenders = [p.name for p in sources if 'date.today()' in p.read_text(encoding='utf-8')]
    assert offenders == []


# ---------- 4. Integer paisa totals ----------

def test_financial_totals_are_exact_integer_paisa(db):
    factory, actors = db
    with factory.begin() as s:
        project = s.scalar(select(Project.id))
        for i in range(40):  # 0.10 / 0.20 PKR amounts accumulate float error when summed as rupees.
            amount = 10 if i % 2 else 20
            accounting.approve(s, actors['Approver'], accounting.create_voucher(
                s, actors['Accountant'], project, business_today(), 'Journal', f'Small amount {i}',
                [accounting.line(accounting.account(s, '1100'), debit=amount),
                 accounting.line(accounting.account(s, '3000'), credit=amount)], f'cents:{i}').id)
    with factory() as s:
        tb = reports.trial_balance(s, paisa=True)
        bs, pnl = reports.financials(s, paisa=True)
        installments = reports.installments(s, paisa=True)
        shown = reports.trial_balance(s)
    for column in ('Opening Debit', 'Debit', 'Credit', 'Closing Debit', 'Closing Credit'):
        assert tb[column].dtype.kind == 'i'
    assert int(tb['Debit'].sum()) == int(tb['Credit'].sum())
    assert int(tb['Closing Debit'].sum()) == int(tb['Closing Credit'].sum())
    assert bs['Amount'].dtype.kind == 'i' and pnl['Amount'].dtype.kind == 'i' and installments['Paid'].dtype.kind == 'i'
    assets = int(bs.loc[bs.Type == 'Asset', 'Amount'].sum())
    assert assets == int(bs.loc[bs.Type != 'Asset', 'Amount'].sum())
    assert shown['Debit'].tolist() == [value / 100 for value in tb['Debit']]


# ---------- 5. Manual voucher grid ----------

ACCOUNTS = {'1100 · Cash in hand': 'acc-cash', '3000 · Owner capital': 'acc-capital'}
PARTIES = {'Sample Supplier · Vendor · abc123': 'party-1'}


def test_voucher_grid_normalizes_blanks_and_skips_empty_rows():
    frame = pd.DataFrame([
        {'Account': '1100 · Cash in hand', 'Party': '', 'Description': None, 'Debit': '100', 'Credit': None},
        {'Account': '', 'Party': '', 'Description': '', 'Debit': '0', 'Credit': '0'},
        {'Account': None, 'Party': None, 'Description': float('nan'), 'Debit': None, 'Credit': float('nan')},
        {'Account': '3000 · Owner capital', 'Party': None, 'Description': '  Opening  ', 'Debit': '', 'Credit': '100.00'},
    ])
    rows = voucher_rows(frame, ACCOUNTS, PARTIES)
    assert [(r['account_id'], r['debit'], r['credit'], r['description'], r['party_id']) for r in rows] == [
        ('acc-cash', 10000, 0, '', None), ('acc-capital', 0, 10000, 'Opening', None)]


@pytest.mark.parametrize('row, message', [
    ({'Account': '', 'Party': '', 'Description': 'Forgot the account', 'Debit': '5', 'Credit': ''}, 'Row 1: select an account'),
    ({'Account': '1100 · Cash in hand', 'Party': '', 'Description': '', 'Debit': None, 'Credit': None}, 'Row 1: enter either'),
    ({'Account': '1100 · Cash in hand', 'Party': '', 'Description': '', 'Debit': '5', 'Credit': '5'}, 'Row 1: enter either'),
    ({'Account': '1100 · Cash in hand', 'Party': '', 'Description': '', 'Debit': 'abc', 'Credit': ''}, 'Row 1: Enter a valid amount'),
    ({'Account': '1100 · Cash in hand', 'Party': 'Unknown person', 'Description': '', 'Debit': '5', 'Credit': ''}, 'Row 1: select a listed party'),
])
def test_voucher_grid_rejects_incomplete_rows(row, message):
    with pytest.raises(BusinessError, match=message):
        voucher_rows(pd.DataFrame([row]), ACCOUNTS, PARTIES)


# ---------- 6. Period closure ----------

def test_period_close_waits_for_pending_ownership_requests(db):
    factory, actors = db
    today = business_today()
    with factory.begin() as s:
        booking = s.scalar(select(Booking.id).where(Booking.status == 'Active'))
        event_id = sales.request_event(s, actors['Accountant'], booking, 'Cancellation', today, 'Customer request').id
        for voucher in s.scalars(select(Voucher).where(Voucher.status == 'Pending')).all():
            accounting.reject(s, actors['Approver'], voucher.id, 'Resolve before close')
    with factory.begin() as s, pytest.raises(BusinessError, match='transfer and cancellation'):
        master.close_period(s, actors['Admin'], today)
    with factory.begin() as s:
        sales.decide_event(s, actors['Approver'], event_id, False)
    with factory.begin() as s:
        master.close_period(s, actors['Admin'], today)
    with factory.begin() as s, pytest.raises(BusinessError, match='closed'):
        sales.request_event(s, actors['Accountant'], booking, 'Cancellation', today, 'After close')


# ---------- 8. Service-level control-account validation ----------

def test_control_accounts_are_enforced_in_services(db):
    factory, actors = db
    today, actor = business_today(), actors['Accountant']
    with factory.begin() as s:
        project, vendor, customer, dealer = ids(s)
        a = {code: accounting.account(s, code) for code in ('1110', '1200', '2000', '2200', '2300', '3000', '5000')}

        def voucher(kind, rows, token):
            return accounting.create_voucher(s, actor, project, today, kind, 'Control test', rows, token)
        with pytest.raises(BusinessError, match='requires a Vendor'):
            voucher('Payment', [accounting.line(a['2000'], debit=100), accounting.line(a['1110'], credit=100)], 'c1')
        with pytest.raises(BusinessError, match='requires a Vendor'):
            voucher('Payment', [accounting.line(a['2000'], debit=100, party_id=customer), accounting.line(a['1110'], credit=100)], 'c2')
        with pytest.raises(BusinessError, match='requires a Dealer'):
            voucher('Payment', [accounting.line(a['2300'], debit=100, party_id=vendor), accounting.line(a['1110'], credit=100)], 'c3')
        with pytest.raises(BusinessError, match='posted only by'):
            voucher('Journal', [accounting.line(a['1200'], debit=100, party_id=customer), accounting.line(a['3000'], credit=100)], 'c4')
        with pytest.raises(BusinessError, match='control accounts'):
            sales.create_invoice(s, actor, project, vendor, 'Purchase', 'BAD-1', today, today, '10', a['1200'], 'Bad', 'c5')
        frame = pd.DataFrame([{'VoucherRef': 'IMP-9', 'Date': today.isoformat(), 'Project': 'NOVA-01', 'AccountCode': code,
                               'PartyID': '', 'Description': 'x', 'Debit': debit, 'Credit': credit}
                              for code, debit, credit in (('2300', '0', '5'), ('5000', '5', '0'))])
        with pytest.raises(BusinessError, match='requires a Dealer'):
            imports.import_vouchers(s, actor, frame)
        voucher('Payment', [accounting.line(a['2000'], debit=100, party_id=vendor), accounting.line(a['1110'], credit=100)], 'ok1')
        voucher('Payment', [accounting.line(a['2200'], debit=100, party_id=customer), accounting.line(a['1110'], credit=100)], 'ok2')
        voucher('Payment', [accounting.line(a['2300'], debit=100, party_id=dealer), accounting.line(a['1110'], credit=100)], 'ok3')


def test_legacy_untagged_entry_can_still_be_reversed(db):
    factory, actors = db
    today = business_today()
    with factory.begin() as s:
        legacy = Voucher(number='PAY-LEGACY-1', token='legacy:1', kind='Payment', project_id=s.scalar(select(Project.id)), date=today,
                         description='Entered before party tagging was required', status='Posted',
                         created_by=actors['Accountant'], approved_by=actors['Approver'])
        s.add(legacy)
        s.flush()
        s.add_all([Line(voucher_id=legacy.id, account_id=accounting.account(s, '2000'), debit=500),
                   Line(voucher_id=legacy.id, account_id=accounting.account(s, '1110'), credit=500)])
        legacy_id = legacy.id
    with factory.begin() as s:
        reversal = accounting.reverse(s, actors['Accountant'], legacy_id, today, 'Correct legacy entry', 'legacy:reverse')
        accounting.approve(s, actors['Approver'], reversal.id)


# ---------- 10. Reversal history ----------

def test_rejected_reversal_keeps_link_and_only_one_reversal_is_effective(db):
    factory, actors = db
    today = business_today()
    with factory.begin() as s:
        original = accounting.create_voucher(s, actors['Accountant'], s.scalar(select(Project.id)), today, 'Journal', 'To reverse',
                                             [accounting.line(accounting.account(s, '1100'), debit=700),
                                              accounting.line(accounting.account(s, '3000'), credit=700)], 'rev:original')
        accounting.approve(s, actors['Approver'], original.id)
        original_id = original.id
    with factory.begin() as s:
        first = accounting.reverse(s, actors['Accountant'], original_id, today, 'First attempt', 'rev:1').id
        accounting.reject(s, actors['Approver'], first, 'Wrong date')
    with factory.begin() as s:
        second = accounting.reverse(s, actors['Accountant'], original_id, today, 'Replacement', 'rev:2').id
    with factory.begin() as s, pytest.raises(BusinessError, match='already exists'):
        accounting.reverse(s, actors['Accountant'], original_id, today, 'Third', 'rev:3')
    with factory() as s:
        assert s.get(Voucher, first).reversal_of == original_id and s.get(Voucher, first).status == 'Rejected'
        assert s.get(Voucher, second).reversal_of == original_id
    with pytest.raises(IntegrityError):
        with factory.begin() as s:
            s.execute(update(Voucher).where(Voucher.id == first).values(status='Pending'))
    with factory.begin() as s:
        accounting.approve(s, actors['Approver'], second)
    with factory() as s:
        ledger = reports.ledger(s, account_id=accounting.account(s, '1100'), paisa=True)
        assert int(ledger.loc[ledger['Voucher'].isin([s.get(Voucher, v).number for v in (original_id, second)]), 'Debit'].sum()) == 700


# ---------- Permissions ----------

@pytest.mark.parametrize('role, action', [
    ('Viewer', lambda s, a, ids_: accounting.create_voucher(s, a, ids_[0], business_today(), 'Journal', 'x',
                                                             [accounting.line(accounting.account(s, '1100'), debit=1),
                                                              accounting.line(accounting.account(s, '3000'), credit=1)], 'p1')),
    ('Sales', lambda s, a, ids_: accounting.approve(s, a, s.scalar(select(Voucher.id).where(Voucher.status == 'Pending')))),
    ('Accountant', lambda s, a, ids_: master.close_period(s, a, business_today())),
    ('Approver', lambda s, a, ids_: accounting.reverse(s, a, s.scalar(select(Voucher.id).where(Voucher.kind == 'Journal')),
                                                        business_today(), 'x', 'p4')),
    ('Sales', lambda s, a, ids_: sales.create_invoice(s, a, ids_[0], ids_[1], 'Purchase', 'P-1', business_today(), business_today(),
                                                       '1', accounting.account(s, '5000'), 'x', 'p5')),
    ('Viewer', lambda s, a, ids_: master.save_user(s, a, 'new@demo.local', 'New', 'Admin')),
])
def test_permission_failures(db, role, action):
    factory, actors = db
    with factory.begin() as s, pytest.raises(BusinessError, match='permission'):
        action(s, actors[role], ids(s))


# ---------- 7. User-entered text ----------

def test_markdown_escape_neutralizes_links_images_and_formatting():
    hostile = '![x](https://attacker.example/t.png) [click](https://phish.example) **bold** :red[alert] $x$ <b>'
    escaped = md_escape(hostile)
    for fragment in ('![', '](', '**', ':red[', '$x$', '<b>'):
        assert fragment not in escaped
    assert md_escape('Line one\nLine two') == 'Line one Line two'
    assert md_escape(None) == ''


def test_customer_name_is_displayed_literally(monkeypatch):
    monkeypatch.setenv('APP_MODE', 'demo')
    from tests.helpers import login_app
    at = login_app()
    with session_factory().begin() as s:
        s.execute(update(Party).where(Party.kind == 'Customer').values(name='![x](https://attacker.example/t.png)'))
    at.sidebar.radio[0].set_value('Allotments').run()
    assert not at.exception
    rendered = [m.value for m in at.markdown]
    assert any('\\!\\[x\\]\\(https\\:' in value for value in rendered), 'The customer name should be shown, escaped'
    assert not any('![x](' in value for value in rendered)
    engine().dispose()


# ---------- 9. Error handling and logs ----------

def test_logs_and_database_errors_exclude_credentials_and_values(db, caplog):
    message = f'connection to {PG_URL} failed; password=Sup3rSecretPw'
    assert 'Sup3rSecretPw' not in redact(message) and 'db.example.test' in redact(message)
    try:
        raise RuntimeError(message)
    except RuntimeError as exc:
        with caplog.at_level(logging.ERROR, logger='nova'):
            log_failure('Database action failed', exc)
    assert 'Database action failed' in caplog.text and 'Sup3rSecretPw' not in caplog.text
    factory, _ = db
    with pytest.raises(IntegrityError) as info:
        with factory.begin() as s:
            s.add(Project(number='NOVA-01', name='CNIC 35202-1234567-1'))
    assert '35202-1234567-1' not in str(info.value)


# ---------- Schema 2 -> 3 upgrade (SQLite) ----------

def make_v2_database(path, broken=None):
    """A schema-2 (release 0.1.0) database with fictional records, including a rejected invoice and an unlinked rejected reversal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(V2_SCHEMA.read_text(encoding='utf-8'))
    when = '2026-10-01 10:00:00'
    con.executemany('INSERT INTO users VALUES (?,?,?,?,1)', [('u-admin', 'admin@demo.local', 'Demo Admin', 'Admin'),
                    ('u-acct', 'accountant@demo.local', 'Demo Accountant', 'Accountant'), ('u-appr', 'approver@demo.local', 'Demo Approver', 'Approver')])
    con.execute("INSERT INTO projects VALUES ('p1','NOVA-01','Fictional Project','','','','')")
    con.executemany('INSERT INTO accounts VALUES (?,?,?,?,NULL,0,?,1)', [('a1100', '1100', 'Cash in hand', 'Asset', 1),
                    ('a1110', '1110', 'Operating bank', 'Asset', 1), ('a2000', '2000', 'Vendor payable', 'Liability', 0),
                    ('a3000', '3000', 'Owner capital', 'Equity', 0), ('a5000', '5000', 'Project expenses', 'Expense', 0)])
    con.execute("INSERT INTO parties VALUES ('vend','Vendor','Fictional Supplier','','','','','','','')")
    vouchers = [('J1', 'JOU-20261001-J1', 't-j1', 'Journal', '2026-10-01', 'Opening', 'Posted', None),
                ('R1', 'REV-20261002-R1', 't-r1', 'Reversal', '2026-10-02', 'Wrong', 'Rejected', None),
                ('I1', 'PUR-20261003-I1', 't-i1', 'Purchase Invoice', '2026-10-03', 'Rejected invoice', 'Rejected', None),
                ('I2', 'PUR-20261004-I2', 't-i2', 'Purchase Invoice', '2026-10-04', 'Approved invoice', 'Posted', None)]
    con.executemany(f"INSERT INTO vouchers VALUES (?,?,?,?,'p1',?,?,?,'u-acct','u-appr','{when}',?)", vouchers)
    con.executemany('INSERT INTO voucher_lines VALUES (?,?,?,?,?,?,?)', [
        ('l1', 'J1', 'a1100', None, '', 10000, 0), ('l2', 'J1', 'a3000', None, '', 0, 10000),
        ('l3', 'R1', 'a3000', None, '', 10000, 0), ('l4', 'R1', 'a1100', None, '', 0, 10000),
        ('l5', 'I1', 'a5000', None, '', 5000, 0), ('l6', 'I1', 'a2000', 'vend', '', 0, 5000),
        ('l7', 'I2', 'a5000', None, '', 7000, 0), ('l8', 'I2', 'a2000', 'vend', '', 0, 7000)])
    con.executemany("INSERT INTO invoices VALUES (?,?,'Purchase','p1','vend',?,?,?,'x',?)", [
        ('inv1', 'SUP-100', '2026-10-03', '2026-10-30', 5000, 'I1'), ('inv2', 'SUP-200', '2026-10-04', '2026-10-30', 7000, 'I2')])
    con.execute(f"INSERT INTO audit_log VALUES ('aud1','{when}','u-acct','reverse_request','vouchers','R1',?)",
                (json.dumps({'original': 'JOU-20261001-J1'}),))
    con.execute("INSERT INTO settings VALUES ('schema_version','2')")
    if broken == 'check':  # A 0.1.0 demo database upgraded from 0.0.x has no CHECK constraints in SQLite.
        con.execute('PRAGMA ignore_check_constraints=ON')
        con.execute("UPDATE invoices SET due = '2026-09-01' WHERE id = 'inv2'")
    con.commit()
    con.close()


def counts(path):
    with sqlite3.connect(path) as con:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def test_upgrade_v2_to_v3_preserves_records_and_history(tmp_path):
    path = tmp_path / 'v2.db'
    make_v2_database(path)
    before = counts(path)
    bind = make_engine(f'sqlite:///{path}')
    initialize(bind, upgrade_existing=False)  # What the app does: an older database is left untouched.
    with bind.connect() as c:
        assert c.scalar(text("SELECT value FROM settings WHERE key='schema_version'")) == '2'
    initialize(bind)
    initialize(bind)  # Repeatable.
    after = counts(path)
    assert {name: after[name] for name in before} == before
    assert all(count == 0 for name, count in after.items() if name not in before)
    with bind.connect() as c:
        assert c.scalar(text("SELECT value FROM settings WHERE key='schema_version'")) == SCHEMA_VERSION
        assert dict(c.execute(text('SELECT id, status FROM invoices')).all()) == {'inv1': 'Rejected', 'inv2': 'Active'}
        assert c.scalar(text("SELECT reversal_of FROM vouchers WHERE id='R1'")) == 'J1'
        assert c.execute(text('PRAGMA foreign_key_check')).first() is None
        assert c.scalar(text('PRAGMA integrity_check')) == 'ok'
        assert c.scalar(text('PRAGMA foreign_keys')) == 1
        assert {r[2] for r in c.execute(text("PRAGMA foreign_key_list('voucher_lines')"))} == {'vouchers', 'accounts', 'parties'}
        assert not c.scalar(text("SELECT name FROM sqlite_master WHERE name LIKE '_nova_new_%'"))
        names = {r[0] for r in c.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}
        assert {'ux_invoices_active_reference', 'ux_vouchers_effective_reversal', 'ix_vouchers_reversal_of'} <= names
    factory = session_factory(bind)
    today = business_today()
    with factory.begin() as s:
        sales.create_invoice(s, 'u-acct', 'p1', 'vend', 'Purchase', 'SUP-100', today, today, '50', 'a5000', 'Corrected', 'after:upgrade')
        replacement = accounting.reverse(s, 'u-acct', 'J1', today, 'Replacement reversal', 'after:reverse')
        accounting.approve(s, 'u-appr', replacement.id)
    with factory() as s:
        assert s.get(Voucher, 'R1').reversal_of == 'J1'
        assert s.scalar(select(func.count()).select_from(Invoice).where(Invoice.reference == 'SUP-100')) == 2
    bind.dispose()


def test_failed_upgrade_changes_nothing_and_hides_database_details(tmp_path):
    path = tmp_path / 'broken.db'
    make_v2_database(path, broken='check')
    before = counts(path)
    with sqlite3.connect(path) as con:
        schema_before = sorted(con.execute('SELECT name, sql FROM sqlite_master').fetchall(), key=lambda r: r[0])
    bind = make_engine(f'sqlite:///{path}')
    with pytest.raises(MigrationError) as info:
        initialize(bind)
    assert 'CHECK constraint' not in str(info.value) and 'No changes were applied' in str(info.value)
    bind.dispose()
    after = counts(path)
    assert {name: after[name] for name in before} == before
    assert all(count == 0 for name, count in after.items() if name not in before)
    with sqlite3.connect(path) as con:
        assert sorted(con.execute('SELECT name, sql FROM sqlite_master').fetchall(), key=lambda r: r[0]) == schema_before
        assert con.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone() == ('2',)


def test_init_db_backs_up_then_upgrades_existing_demo_database(tmp_path, monkeypatch, capsys):
    from scripts import init_db
    make_v2_database(config.DEMO_DATABASE)
    monkeypatch.setattr(init_db, 'BACKUP_FOLDER', tmp_path / 'upgrade-backups')
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=20).run()  # The app refuses instead of migrating.
    assert at.error and 'needs version' in at.error[0].value
    with sqlite3.connect(config.DEMO_DATABASE) as con:
        assert con.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone() == ('2',)
    engine().dispose()
    engine.cache_clear()
    init_db.main([])
    engine().dispose()
    backups = list((tmp_path / 'upgrade-backups').glob('*.db'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as con:
        assert con.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone() == ('2',)
    with sqlite3.connect(config.DEMO_DATABASE) as con:
        assert con.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone() == (SCHEMA_VERSION,)
        assert con.execute('SELECT COUNT(*) FROM projects').fetchone() == (1,)  # Existing records are preserved: no reset or sample reseeding.
    assert 'Pre-upgrade backup created' in capsys.readouterr().out


def test_init_db_on_empty_demo_database(tmp_path):
    from scripts import init_db
    init_db.main([])
    engine().dispose()
    with sqlite3.connect(config.DEMO_DATABASE) as con:
        assert con.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone() == (SCHEMA_VERSION,)
        assert con.execute('SELECT COUNT(*) FROM projects').fetchone() == (0,)


def test_demo_reset_clears_records_and_does_not_reseed(tmp_path):
    copy = tmp_path / 'app_copy'
    shutil.copytree(ROOT / 'nova', copy / 'nova', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(ROOT / 'app.py', copy / 'app.py')
    shutil.copy2(ROOT / 'reset_demo.py', copy / 'reset_demo.py')
    database = copy / 'data' / 'demo.db'
    database.parent.mkdir()
    bind = make_engine(f'sqlite:///{database}')
    initialize(bind)
    with session_factory(bind).begin() as s:
        bootstrap(s)
    bind.dispose()
    environment = {k: v for k, v in __import__('os').environ.items() if k not in ('APP_MODE', 'DATABASE_URL')}
    result = subprocess.run([sys.executable, str(copy / 'reset_demo.py'), '--confirm-clear-demo'], cwd=copy, env=environment,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(list((copy / 'backups').glob('before-reset-*.db'))) == 1
    bind = make_engine(f'sqlite:///{database}')
    factory = session_factory(bind)
    with factory.begin() as s:
        bootstrap(s)  # What the next app start does.
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Project)) == 0
        assert s.scalar(select(func.count()).select_from(Voucher)) == 0
        assert s.scalar(select(func.count()).select_from(User)) == 5
        assert s.get(Setting, 'demo_seed_complete').value == '1'
    bind.dispose()


# ---------- 11. Release packaging ----------

def test_release_package_contains_source_only(tmp_path):
    from scripts import package_release
    names = [p.relative_to(ROOT).as_posix() for p in package_release.release_files()]
    assert 'app.py' in names and 'nova/models.py' in names
    assert not [n for n in names if n.split('/')[0] in ('data', 'backups', 'references', '.venv')]
    assert not [n for n in names if (n.endswith(('.db', '.db-wal', '.db-shm', '.dump', '.jpeg', '.jpg', '.pdf', 'secrets.toml')) or n == '.env') and n != 'assets/nova_logo.jpeg']
    assert 'assets/nova_logo.jpeg' in names
    target = tmp_path / 'release.zip'
    package_release.main(['--output', str(target)])
    with zipfile.ZipFile(target) as archive:
        assert sorted(archive.namelist()) == sorted(f'nova_erp/{n}' for n in names)
    with pytest.raises(SystemExit, match='outside the project'):
        package_release.main(['--output', str(ROOT / 'inside.zip')])
