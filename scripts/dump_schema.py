"""Regenerate docs/SCHEMA_POSTGRESQL.sql from the models: python -m scripts.dump_schema"""
from sqlalchemy import create_mock_engine
from sqlalchemy.dialects import postgresql
from nova.config import ROOT
from nova.migrations import SCHEMA_VERSION
from nova.models import Base


def main():
    statements = []
    dialect = postgresql.dialect(paramstyle='named')  # Emits '%' literally, not driver-escaped '%%'.
    engine = create_mock_engine('postgresql://', lambda sql, *_, **__: statements.append(str(sql.compile(dialect=dialect)).strip()))
    Base.metadata.create_all(engine, checkfirst=False)
    header = f'-- Schema version {SCHEMA_VERSION}; reference DDL only. Use scripts.init_db for initialization and upgrades.\n'
    target = ROOT / 'docs/SCHEMA_POSTGRESQL.sql'
    target.write_text(header + ''.join(f'\n{s};\n' for s in statements), encoding='utf-8', newline='\n')
    print(f'Wrote {target}')


if __name__ == '__main__':
    main()
