from functools import lru_cache
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from nova.config import ROOT, settings
from nova.models import Base


def make_engine(url):
    # hide_parameters keeps customer data out of exception text and logs.
    kwargs = {'pool_pre_ping': True, 'hide_parameters': True}
    if url.startswith('sqlite'):
        kwargs['connect_args'] = {'check_same_thread': False, 'timeout': 30}
    else:
        kwargs.update(pool_size=5, max_overflow=5)
    engine = create_engine(url, **kwargs)
    if url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def configure_sqlite(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA journal_mode=WAL')
    return engine


@lru_cache(maxsize=1)
def engine():
    (ROOT / 'data').mkdir(exist_ok=True)
    return make_engine(settings()['url'])


def session_factory(bind=None):
    return sessionmaker(bind=bind or engine(), expire_on_commit=False)


def initialize(bind=None, upgrade_existing=True):
    """Create missing tables; upgrade an older schema only when asked (scripts.init_db does, after a backup)."""
    from nova.migrations import needs_upgrade, upgrade
    bind = bind or engine()
    from sqlalchemy import inspect
    if 'settings' in inspect(bind).get_table_names() and needs_upgrade(bind):
        if not upgrade_existing:
            return
        upgrade(bind)  # Upgrade first: create_all would add new indexes before their columns exist.
    Base.metadata.create_all(bind)
    upgrade(bind)
