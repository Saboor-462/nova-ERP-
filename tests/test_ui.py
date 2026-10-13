import pytest
from sqlalchemy import func, select
from streamlit.testing.v1 import AppTest
from nova.config import ROOT
from nova.db import engine, session_factory
from nova.models import Project


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Demo mode only runs on the demo database; conftest points that at a temporary file.
    monkeypatch.setenv('APP_MODE', 'demo')
    engine.cache_clear()
    from tests.helpers import login_app
    at = login_app()
    assert not at.exception
    yield at
    engine().dispose()
    engine.cache_clear()


def test_all_menu_and_report_pages(app):
    from nova.ui.reporting import REPORTS
    pages = ['Dashboard', 'Reports', 'Vouchers', 'Chart of Accounts', 'Clients', 'Projects', 'Units', 'Allotments',
             'Invoices', 'Transfers & Cancellations', 'CRM / Leads', 'Cash / Bank', 'Bulk Entries', 'Financial Years', 'Administration']
    for page in pages:
        app.sidebar.radio[0].set_value(page).run()
        assert app.sidebar.radio[0].value == page
        assert not app.exception, f'Runtime error on {page}'
        assert all(('awaiting approval' in x.value or 'Pending approval' in x.value or 'Reconciliation difference' in x.value) for x in app.error), f'Unexpected error on {page}'
    app.sidebar.radio[0].set_value('Reports').run()
    for report in REPORTS:
        next(x for x in app.selectbox if x.label == 'Report').set_value(report).run()
        assert app.header[0].value == report
        assert not app.exception, f'Runtime error on {report}'
        assert not app.error, f'Error message on {report}'
    app.sidebar.radio[0].set_value('Invoices').run()
    for kind in ('Purchase', 'Sale', 'Dealer'):
        next(x for x in app.selectbox if x.label == 'New invoice type').set_value(kind).run()
        assert not app.exception
        assert not app.error


def test_project_creation_through_ui_and_viewer_hiding(app):
    app.sidebar.radio[0].set_value('Projects').run()
    next(x for x in app.text_input if x.label == 'Project number').set_value('UI-001')
    next(x for x in app.text_input if x.label == 'Project name').set_value('UI Test Project')
    next(x for x in app.button if x.label == 'Save project').click().run()
    assert not app.exception
    assert not app.error
    with session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(Project).where(Project.number == 'UI-001')) == 1
        from nova.models import User
        viewer = session.scalar(select(User.id).where(User.role == 'Viewer'))
    from nova.services.security import set_password
    with session_factory().begin() as session:
        from nova.models import User
        admin_id = session.scalar(select(User.id).where(User.role == 'Admin'))
        set_password(session, admin_id, viewer, 'Viewer Test Password 2026')
    next(x for x in app.sidebar.button if x.label == 'Sign out').click().run()
    app.text_input(key='login_email').set_value('viewer@demo.local')
    app.text_input(key='login_password').set_value('Viewer Test Password 2026')
    next(x for x in app.button if x.label == 'Sign in').click().run()
    app.sidebar.radio[0].set_value('Projects').run()
    assert not any(x.label == 'Save project' for x in app.button)
