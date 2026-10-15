"""Numbered, repeatable schema upgrades for databases created by an earlier release."""
import json
import re
from sqlalchemy import CheckConstraint, DDL, inspect, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import AddConstraint, CreateTable
from nova.diagnostics import log_failure
from nova.models import VOUCHER_BALANCE_DDL, Base, Invoice, Setting, Voucher

SCHEMA_VERSION = '5'


class MigrationError(RuntimeError):
    """Upgrade failure whose message is fixed text, safe to show users; details go to the server log."""


# Check constraints on columns that a later step adds.
LATER_CHECKS = {'ck_invoices_status': ('invoices', 'status')}


def _add_missing_checks(connection):
    present = set(connection.scalars(text('SELECT conname FROM pg_constraint')))
    inspector = inspect(connection)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint) and constraint.name and constraint.name not in present:
                needed = LATER_CHECKS.get(constraint.name)
                if needed and needed[1] not in {c['name'] for c in inspector.get_columns(needed[0])}:
                    continue
                connection.execute(AddConstraint(constraint))


def _to_2(connection):
    # Existing rows must already satisfy the new rules; a violation aborts the whole upgrade.
    for table in (t for t in Base.metadata.sorted_tables if t.name not in ('invoices', 'vouchers')):
        if not inspect(connection).has_table(table.name):
            continue
        for index in table.indexes:
            index.create(connection, checkfirst=True)
    if connection.dialect.name != 'postgresql':
        return  # SQLite cannot add CHECK constraints in place; the demo database keeps the service-level checks.
    for table in (Invoice.__table__, Voucher.__table__):
        for index in table.indexes:
            if index.dialect_options['postgresql']['where'] is None:  # Partial indexes belong to version 3.
                index.create(connection, checkfirst=True)
    _add_missing_checks(connection)
    for statement in VOUCHER_BALANCE_DDL:
        connection.execute(DDL(statement))


def _rebuild_sqlite(connection, table):
    """SQLite cannot drop a UNIQUE constraint: copy the table into the current definition (foreign keys are off)."""
    old_columns = {row[1] for row in connection.exec_driver_sql(f'PRAGMA table_info("{table.name}")')}
    shared = ', '.join(f'"{c.name}"' for c in table.columns if c.name in old_columns)
    temporary = f'_nova_new_{table.name}'
    ddl = str(CreateTable(table).compile(dialect=connection.dialect))
    ddl = re.sub(rf'^\s*CREATE TABLE "?{table.name}"?', f'CREATE TABLE "{temporary}"', ddl, count=1)
    connection.exec_driver_sql(ddl)
    connection.exec_driver_sql(f'INSERT INTO "{temporary}" ({shared}) SELECT {shared} FROM "{table.name}"')
    connection.exec_driver_sql(f'DROP TABLE "{table.name}"')
    connection.exec_driver_sql(f'ALTER TABLE "{temporary}" RENAME TO "{table.name}"')


def _restore_reversal_links(connection):
    # Release 0.1.0 unlinked rejected reversal attempts; their audit entry still names the original voucher.
    rows = connection.execute(text(
        "SELECT v.id, a.detail FROM vouchers v JOIN audit_log a ON a.entity_id = v.id AND a.entity = 'vouchers' "
        "AND a.action = 'reverse_request' WHERE v.kind = 'Reversal' AND v.status = 'Rejected' AND v.reversal_of IS NULL")).all()
    for voucher_id, detail in rows:
        try:
            number = json.loads(detail).get('original')
        except (TypeError, ValueError, AttributeError):
            continue
        original = connection.scalar(text('SELECT id FROM vouchers WHERE number = :number'), {'number': number})
        if original and original != voucher_id:
            connection.execute(text('UPDATE vouchers SET reversal_of = :original WHERE id = :id'), {'original': original, 'id': voucher_id})


def _to_3(connection):
    # Invoices gain a status so a rejected invoice is kept while its reference can be reused;
    # vouchers.reversal_of uniqueness applies only to pending/posted reversals.
    if connection.dialect.name == 'postgresql':
        connection.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'Active' NOT NULL"))
        inspector = inspect(connection)
        for table, columns in (('invoices', {'party_id', 'reference', 'kind'}), ('vouchers', {'reversal_of'})):
            for constraint in inspector.get_unique_constraints(table):
                if set(constraint['column_names']) == columns:
                    connection.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT "{constraint["name"]}"'))
    else:
        _rebuild_sqlite(connection, Invoice.__table__)
        _rebuild_sqlite(connection, Voucher.__table__)
    connection.execute(text("UPDATE invoices SET status = 'Rejected' WHERE status <> 'Rejected' AND voucher_id IN "
                            "(SELECT id FROM vouchers WHERE status = 'Rejected')"))
    _restore_reversal_links(connection)
    if connection.dialect.name == 'postgresql':
        _add_missing_checks(connection)
    for table in (Invoice.__table__, Voucher.__table__):
        for index in table.indexes:
            index.create(connection, checkfirst=True)


def _to_4(connection):
    columns = {c['name'] for c in inspect(connection).get_columns('vouchers')}
    for name, size in [('payment_mode', 40), ('payment_type', 60)]:
        if name not in columns:
            connection.execute(text(f"ALTER TABLE vouchers ADD COLUMN {name} VARCHAR({size}) NOT NULL DEFAULT ''"))
    # Additive tables only: existing identities and document numbers are never rewritten.
    for name in ('credentials', 'login_sessions', 'login_attempts', 'document_sequences', 'financial_years', 'retired_codes', 'invoice_items'):
        Base.metadata.tables[name].create(connection, checkfirst=True)


def _to_5(connection):
    # Store correction requests separately; existing invoices and vouchers remain unchanged.
    Base.metadata.tables['invoice_corrections'].create(connection, checkfirst=True)


STEPS = {'1': _to_2, '2': _to_3, '3': _to_4, '4': _to_5}


def stored_version(connection):
    return connection.scalar(select(Setting.value).where(Setting.key == 'schema_version'))


def _run_steps(connection):
    row = connection.execute(select(Setting.value).where(Setting.key == 'schema_version').with_for_update()).first()
    if row is None:
        return  # New database: tables were created at the current version.
    version = row.value
    while version != SCHEMA_VERSION:
        if version not in STEPS:
            raise MigrationError(f'Unsupported schema version {version}; this release expects {SCHEMA_VERSION}.')
        try:
            STEPS[version](connection)
        except DBAPIError as exc:
            log_failure(f'Schema upgrade from version {version} failed', exc)
            raise MigrationError(f'Schema upgrade from version {version} failed because existing data violates a new rule. '
                               'No changes were applied. See the server log for details.') from None
        version = str(int(version) + 1)
    connection.execute(update(Setting).where(Setting.key == 'schema_version').values(value=version))


def _upgrade_sqlite(bind):
    with bind.connect() as connection:
        if stored_version(connection) in (None, SCHEMA_VERSION):
            return
        connection.rollback()
        # Table rebuilds need foreign keys off, which SQLite only accepts outside a transaction;
        # then one explicit transaction makes the whole upgrade atomic.
        raw = connection.connection.driver_connection
        previous = raw.isolation_level
        raw.isolation_level = None
        try:
            connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            try:
                _run_steps(connection)
                if connection.exec_driver_sql('PRAGMA foreign_key_check').first():
                    raise MigrationError('Schema upgrade stopped: existing rows reference missing records. No changes were applied.')
                connection.exec_driver_sql('COMMIT')
            except BaseException:
                if raw.in_transaction:
                    raw.execute('ROLLBACK')
                raise
        finally:
            connection.exec_driver_sql('PRAGMA foreign_keys=ON')
            raw.isolation_level = previous
            connection.rollback()


def needs_upgrade(bind):
    with bind.connect() as connection:
        version = stored_version(connection)
    return version is not None and version != SCHEMA_VERSION


def upgrade(bind):
    if bind.dialect.name == 'sqlite':
        return _upgrade_sqlite(bind)
    with bind.begin() as connection:
        _run_steps(connection)
