import argparse
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
from sqlalchemy.engine import make_url
from nova.config import settings


def main():
    parser = argparse.ArgumentParser(description='Create a consistent database backup. Does not delete or restore records.')
    parser.add_argument('--output', required=True, help='A new destination path (.db for SQLite, .dump for PostgreSQL).')
    args = parser.parse_args()
    target = Path(args.output).resolve()
    if target.exists():
        raise SystemExit('Destination already exists; choose a new backup filename.')
    target.parent.mkdir(parents=True, exist_ok=True)
    url = make_url(settings()['url'])
    if url.drivername.startswith('sqlite'):
        with sqlite3.connect(url.database) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
    else:
        executable = shutil.which('pg_dump')
        if not executable:
            raise SystemExit('Install PostgreSQL client tools and add pg_dump to PATH.')
        env = dict(os.environ)
        env.update(PGHOST=url.host or '', PGPORT=str(url.port or 5432), PGDATABASE=url.database or '',
                   PGUSER=url.username or '', PGPASSWORD=url.password or '', PGSSLMODE=str(url.query.get('sslmode', 'require')))
        result = subprocess.run([executable, '--format=custom', '--no-owner', '--no-acl', '--file', str(target)], env=env,
                                capture_output=True, text=True)
        if result.returncode:
            target.unlink(missing_ok=True)
            raise SystemExit('Backup failed. Check database access and pg_dump version; credentials were not printed.')
    print(f'Backup created: {target}')


if __name__ == '__main__':
    main()
