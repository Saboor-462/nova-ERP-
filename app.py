import logging
from functools import lru_cache
import streamlit as st
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from nova.auth import identify, render_account_controls
from nova.config import ConfigError, settings
from nova.db import initialize, session_factory
from nova.diagnostics import log_failure
from nova.migrations import SCHEMA_VERSION, MigrationError
from nova.models import Setting
from nova.seed import bootstrap
from nova.ui import admin, masters, reporting, transactions

st.set_page_config(page_title='Nova ERP', page_icon='🏢', layout='wide', initial_sidebar_state='expanded')
from nova.branding import theme, LOGO
theme()
logging.basicConfig(level=logging.INFO)


@lru_cache(maxsize=1)
def prepare_demo():
    # A demo database from an older release is not upgraded here; scripts.init_db backs it up first.
    initialize(upgrade_existing=False)
    with session_factory().begin() as session:
        schema = session.get(Setting, 'schema_version')
        if schema is None or schema.value == SCHEMA_VERSION:
            bootstrap(session, sample=False)


try:
    config = settings()
    if config['mode'] == 'demo':
        prepare_demo()
    factory = session_factory()
    with factory() as session:
        schema = session.get(Setting, 'schema_version')
        if not schema or schema.value != SCHEMA_VERSION:
            st.error(f'Database schema {schema.value if schema else "(none)"} needs version {SCHEMA_VERSION}. '
                     'Stop the app and run: python -m scripts.init_db (it backs up a local database first). See AUDIT_REPORT.md.')
            st.stop()
except ConfigError as exc:
    st.error(f'Configuration error: {exc}')
    st.stop()
except MigrationError as exc:
    st.error(str(exc))  # Fixed text only; database details go to the sanitized server log.
    st.stop()
except (ValueError, SQLAlchemyError) as exc:
    log_failure('Startup configuration or database initialization failed', exc)
    st.error('Database setup is incomplete. Check DATABASE_URL and run python -m scripts.init_db. See docs/SETUP.md.')
    st.stop()

actor = identify(factory, config, render_sidebar=False)

st.markdown(
    '''<style>
    [data-testid="stSidebar"] .st-key-nova_sidebar_layout,
    [data-testid="stSidebar"] .st-key-nova_sidebar_layout > [data-testid="stVerticalBlock"] {
        min-height: calc(100dvh - 4rem);
        display: flex;
        flex-direction: column;
    }

    [data-testid="stSidebar"] .st-key-nova_sidebar_footer {
        margin-top: auto;
        padding-top: 1rem;
    }

    [data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
        padding-top: .25rem !important;
        padding-bottom: .25rem !important;
        min-height: 2rem !important;
        height: auto !important;
    }

    [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
        padding-top: 0 !important;
    }

    [data-testid="stSidebar"] .st-key-nova_sidebar_navigation,
    [data-testid="stSidebar"] .st-key-nova_sidebar_navigation > [data-testid="stVerticalBlock"] {
        gap: .4rem;
    }

    [data-testid="stSidebar"] .st-key-nova_sidebar_navigation [data-testid="stButton"] button {
        width: 100% !important;
        min-height: 44px;
        justify-content: flex-start;
        padding: 10px 14px;
        background: #13283d !important;
        color: #ffffff !important;
        border: 1px solid #cba334 !important;
        border-radius: 9px;
    }

    [data-testid="stSidebar"] .st-key-nova_sidebar_navigation [data-testid="stButton"] button p {
        width: 100%;
        margin: 0;
        color: #ffffff !important;
        text-align: left;
        white-space: normal;
        overflow-wrap: anywhere;
    }

    [data-testid="stSidebar"] .st-key-nova_sidebar_navigation [data-testid="stButton"] button:hover {
        background: #203a52 !important;
        border-color: #e4c36f !important;
    }

    [data-testid="stSidebar"] .st-key-nova_sidebar_navigation [data-testid="stButton"] button:focus-visible {
        outline: 2px solid #e4c36f;
        outline-offset: 3px;
    }
    </style>''',
    unsafe_allow_html=True,
)

groups = ['Dashboard', 'Reports', 'Vouchers', 'Chart of Accounts', 'Clients', 'Projects', 'Units', 'Allotments',
          'Invoices', 'Transfers & Cancellations', 'CRM / Leads', 'Cash / Bank', 'Bulk Entries', 'Financial Years', 'Administration']


def select_page(page_name):
    st.session_state['nova_navigation_page'] = page_name


if 'nova_navigation_page' not in st.session_state:
    st.session_state['nova_navigation_page'] = st.session_state.get('nova_navigation', 'Dashboard')
if st.session_state['nova_navigation_page'] not in groups:
    st.session_state['nova_navigation_page'] = 'Dashboard'
page = st.session_state['nova_navigation_page']

st.markdown(
    f'''<style>
    [data-testid="stSidebar"] .st-key-nova_sidebar_navigation .st-key-nova_navigation_{groups.index(page)} button {{
        background: #25435c !important;
        border-color: #e4c36f !important;
        box-shadow: inset 3px 0 0 #e4c36f;
    }}

    [data-testid="stSidebar"] .st-key-nova_sidebar_navigation .st-key-nova_navigation_{groups.index(page)} button p {{
        font-weight: 700;
    }}
    </style>''',
    unsafe_allow_html=True,
)

with st.sidebar:
    with st.container(key='nova_sidebar_layout'):
        st.image(str(LOGO), width=125)
        st.caption('Navigation')
        with st.container(key='nova_sidebar_navigation'):
            for index, label in enumerate(groups):
                st.button(
                    label,
                    key=f'nova_navigation_{index}',
                    width='stretch',
                    on_click=select_page,
                    args=(label,),
                )

        with st.container(key='nova_sidebar_footer'):
            render_account_controls(factory, config, actor)

if config['mode'] == 'demo':
    st.caption('Local database · Email/password login · PKR · Pakistan time')

routes = {
    'Dashboard': lambda: reporting.dashboard(factory, actor),
    'Reports': lambda: reporting.report_page(factory, actor),
    'Vouchers': lambda: transactions.vouchers(factory, actor, False),
    'Chart of Accounts': lambda: masters.accounts(factory, actor),
    'Clients': lambda: masters.parties(factory, actor),
    'Projects': lambda: masters.projects(factory, actor),
    'Units': lambda: masters.units(factory, actor),
    'Allotments': lambda: transactions.bookings(factory, actor),
    'Invoices': lambda: transactions.invoices(factory, actor),
    'Transfers & Cancellations': lambda: transactions.events(factory, actor, False),
    'CRM / Leads': lambda: masters.leads(factory, actor),
    'Cash / Bank': lambda: admin.cash_bank(factory, actor),
    'Bulk Entries': lambda: admin.bulk_entries(factory, actor),
    'Financial Years': lambda: admin.financial_years(factory, actor),
    'Administration': lambda: admin.administration(factory, actor),
}

try:
    routes[page]()
except SQLAlchemyError as exc:
    log_failure('Page load failed', exc)
    st.error('Unable to load this page. Check the database connection and refresh.')
