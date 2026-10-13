import argparse
from datetime import datetime
import sqlite3
from uuid import uuid4
from sqlalchemy.engine import make_url
from nova.config import ROOT, ConfigError, settings
from nova.db import engine, initialize, session_factory
from nova.migrations import SCHEMA_VERSION, MigrationError, needs_upgrade
from nova.seed import bootstrap

BACKUP_FOLDER = ROOT / 'backups'


def backup_sqlite(url, folder):
    """Consistent copy of a SQLite database before its schema is upgraded."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'before-upgrade-v{SCHEMA_VERSION}-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}.db'
    with sqlite3.connect(make_url(url).database) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description='Create or upgrade the ERP database. Never deletes records.')
    parser.add_argument('--postgres-backup-done', action='store_true',
                        help='Confirm you created a pg_dump backup (python -m scripts.backup) before a PostgreSQL schema upgrade.')
    args = parser.parse_args(argv)
    try:
        config = settings()
    except ConfigError as exc:
        raise SystemExit(f'Configuration error: {exc}')
    bind = engine()
    from sqlalchemy import inspect
    if 'settings' in inspect(bind).get_table_names() and needs_upgrade(bind):
        if bind.dialect.name == 'sqlite':
            print(f'Pre-upgrade backup created: {backup_sqlite(config["url"], BACKUP_FOLDER)}')
        elif not args.postgres_backup_done:
            raise SystemExit('This database needs a schema upgrade. Back it up first with python -m scripts.backup, '
                             'then rerun with --postgres-backup-done.')
    try:
        initialize()
    except MigrationError as exc:
        raise SystemExit(str(exc))
    with session_factory().begin() as session:
        bootstrap(session, config['mode'], config['admin_email'], sample=False)
    print(f'Database initialized in {config["mode"]} mode at schema version {SCHEMA_VERSION}. No existing transactions were deleted.')


if __name__ == '__main__':
    main()
