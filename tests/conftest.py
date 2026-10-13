import pytest
from sqlalchemy import select
from nova import config
from nova.db import engine, initialize, make_engine, session_factory
from nova.models import User
from nova.seed import bootstrap


@pytest.fixture(autouse=True)
def isolated_configuration(tmp_path, monkeypatch):
    """No test may reach the real data/demo.db, a .env value, or a Streamlit secrets file."""
    monkeypatch.setattr(config, 'DEMO_DATABASE', tmp_path / 'demo' / 'demo.db')
    monkeypatch.setattr(config, 'streamlit_secrets', lambda: {})
    for name in ('APP_MODE', 'DATABASE_URL', 'ADMIN_EMAIL'):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / 'demo').mkdir()
    engine.cache_clear()
    yield
    engine.cache_clear()


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f'sqlite:///{tmp_path / "test.db"}')
    initialize(engine)
    factory = session_factory(engine)
    with factory.begin() as session:
        bootstrap(session)
    with factory() as session:
        actors = {u.role: u.id for u in session.scalars(select(User)).all()}
    yield factory, actors
    engine.dispose()
