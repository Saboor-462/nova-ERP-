"""Reset the default local Nova ERP demo while preserving its users and accounts."""
import argparse
import os
from datetime import datetime
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4


def reset():
    root = Path(__file__).resolve().parent
    if not (root / 'app.py').exists() or not (root / 'nova/seed.py').exists():
        raise SystemExit('Place reset_demo.py inside nova_erp, beside app.py, and run it there.')
    values = dict(os.environ)
    env_file = root / '.env'
    if env_file.exists():
        for raw in env_file.read_text(encoding='utf-8').splitlines():
            raw = raw.strip()
            if not raw or raw.startswith('#'):
                continue
            if '=' not in raw:
                raise SystemExit('Reset refused: unfamiliar .env format.')
            key, value = raw.split('=', 1)
            values.setdefault(key.strip(), value.strip().strip('\"\''))
    secrets_file = root / '.streamlit/secrets.toml'
    if secrets_file.exists():
        import tomllib
        with secrets_file.open('rb') as handle:
            values.update(tomllib.load(handle).get('erp', {}))
    expected = (root / 'data/demo.db').resolve()
    configured_url = values.get('DATABASE_URL', '')
    if values.get('APP_MODE', 'demo') != 'demo' or (configured_url and configured_url not in (f'sqlite:///{expected}', f'sqlite:///{expected.as_posix()}')):
        raise SystemExit('Reset refused: this tool supports only demo mode with the default local data/demo.db.')
    if not expected.exists():
        raise SystemExit('No local demo database was found. Start the app once, stop it, and retry.')
    source = root / 'nova/seed.py'
    original = source.read_text(encoding='utf-8')
    old_guard = "    if session.scalar(select(Project.id).limit(1)):\n        return\n"
    new_guard = "    if session.get(Setting, 'demo_seed_complete') or session.scalar(select(Project.id).limit(1)):\n        return\n"
    if new_guard in original:
        changed = original
    elif original.count(old_guard) == 1:
        changed = original.replace(old_guard, new_guard, 1)
    else:
        raise SystemExit('Reset refused: seed.py does not match the supported release. No data was removed.')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:6]
    backups = root / 'backups'
    backups.mkdir(exist_ok=True)
    backup_db = backups / f'before-reset-{stamp}.db'
    backup_seed = backups / f'seed-before-reset-{stamp}.py'
    kept = {'users', 'accounts', 'settings', 'credentials', 'document_sequences', 'retired_codes'}
    delete_order = ['login_sessions', 'login_attempts', 'financial_years', 'audit_log', 'bank_clearances', 'attachments', 'receipt_allocations', 'invoice_payments',
                    'booking_events', 'installments', 'bookings', 'invoice_items', 'invoices', 'voucher_lines', 'vouchers',
                    'leads', 'units', 'parties', 'projects']
    known = kept | set(delete_order)
    with sqlite3.connect(expected, timeout=30) as connection:
        present = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if present != known:
            raise SystemExit('Reset refused: unexpected database schema. No data was removed.')
        if connection.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone() != ('4',):
            raise SystemExit('Reset refused: unsupported schema version. Run python -m scripts.init_db first (it backs up and upgrades).')
        with sqlite3.connect(backup_db) as destination:
            connection.backup(destination)
        shutil.copy2(source, backup_seed)
        temporary = source.with_suffix('.reset-tmp')
        temporary.write_text(changed, encoding='utf-8')
        temporary.replace(source)
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('BEGIN IMMEDIATE')
            for name in delete_order:
                connection.execute(f'DELETE FROM "{name}"')
            connection.execute("DELETE FROM settings WHERE key='closed_through'")
            connection.execute("INSERT INTO settings(key,value) VALUES ('demo_seed_complete','1') ON CONFLICT(key) DO UPDATE SET value='1'")
            connection.commit()
        except Exception:
            connection.rollback()
            source.write_text(original, encoding='utf-8')
            raise
    print('Local business records cleared. Users and chart of accounts retained with zero transaction balances.')
    print('Automatic sample seeding is disabled for this database.')
    print(f'Pre-reset database backup: {backup_db}')
    print(f'Pre-reset source backup: {backup_seed}')
    print('Restart run_windows.bat, then add your own project, parties, units, bookings, and invoices.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Clear ALL local business records, including any records you entered. Takes a backup first. Stop Streamlit before running.')
    parser.add_argument('--confirm-clear-demo', action='store_true')
    args = parser.parse_args()
    if not args.confirm_clear_demo:
        parser.error('Stop the app first. To clear all business records with a backup, pass --confirm-clear-demo.')
    reset()
