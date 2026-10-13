from sqlalchemy import select
from streamlit.testing.v1 import AppTest
from nova.config import ROOT
from nova.db import initialize, session_factory
from nova.models import Credential, User
from nova.seed import bootstrap
from nova.services.security import set_password


def login_app():
    initialize()
    with session_factory().begin() as session:
        bootstrap(session)  # Explicit fictional fixtures only; normal app startup does not seed these.
        admin = session.scalar(select(User).where(User.role == 'Admin'))
        if not session.get(Credential, admin.id):
            set_password(session, admin.id, admin.id, 'Admin Test Password 2026')
    app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
    assert not app.exception
    assert not app.sidebar.radio
    app.text_input(key='login_email').set_value(admin.email)
    app.text_input(key='login_password').set_value('Admin Test Password 2026')
    next(b for b in app.button if b.label == 'Sign in').click().run()
    assert not app.exception
    assert app.sidebar.radio
    return app
