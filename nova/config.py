import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
# The only database demo mode may use: role switching and sample seeding never touch any other database.
DEMO_DATABASE = ROOT / 'data/demo.db'


class ConfigError(ValueError):
    """Configuration problem whose message is safe to show users (never includes URLs or credentials)."""


def streamlit_secrets():
    try:
        import streamlit as st
        return dict(st.secrets.get('erp', {}))
    except FileNotFoundError as exc:
        # Streamlit raises a FileNotFoundError subclass both for "no secrets file" and for an unreadable file.
        if getattr(exc, 'error_id', None) in (None, 'no-secrets-found'):
            return {}
        raise ConfigError('The Streamlit secrets file could not be read. Check its TOML syntax.') from None
    except (ImportError, RuntimeError):
        return {}


def is_demo_database(url):
    from sqlalchemy.engine import make_url
    try:
        parsed = make_url(url)
    except Exception:
        return False
    if not parsed.drivername.startswith('sqlite') or not parsed.database or parsed.database == ':memory:':
        return False
    return Path(parsed.database).resolve() == DEMO_DATABASE.resolve()


def settings(environ=None, secrets=None):
    values = dict(os.environ if environ is None else environ)
    values.update(streamlit_secrets() if secrets is None else secrets)
    configured_url = str(values.get('DATABASE_URL') or '').strip()
    mode = str(values.get('APP_MODE') or '').strip()
    if not mode:
        if configured_url and not is_demo_database(configured_url):
            raise ConfigError('DATABASE_URL is set but APP_MODE is not. Set APP_MODE=production for a business database.')
        mode = 'demo'
    if mode not in ('demo', 'production'):
        raise ConfigError('APP_MODE must be demo or production.')
    url = configured_url or f'sqlite:///{DEMO_DATABASE}'
    if url.startswith('postgres://'):
        url = 'postgresql+psycopg://' + url[len('postgres://'):]
    elif url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    if mode == 'demo' and not is_demo_database(url):
        raise ConfigError('Demo mode only runs on the local sample database data/demo.db. '
                          'Remove DATABASE_URL for the demo, or set APP_MODE=production for PostgreSQL.')
    if mode == 'production':
        if not url.startswith('postgresql+psycopg://'):
            raise ConfigError('Production mode requires a PostgreSQL DATABASE_URL.')
        from sqlalchemy.engine import make_url
        try:
            parsed = make_url(url)
        except Exception:
            raise ConfigError('DATABASE_URL is not a valid PostgreSQL connection URL.') from None
        if not parsed.host or not parsed.database:
            raise ConfigError('DATABASE_URL must include the database host and name.')
    admin_email = str(values.get('ADMIN_EMAIL') or '').lower().strip()
    if admin_email and '@' not in admin_email:
        raise ConfigError('ADMIN_EMAIL is not a valid email address.')
    auth_method = str(values.get('AUTH_METHOD') or ('password' if mode == 'demo' else 'oidc')).strip()
    if auth_method not in ('password', 'oidc'):
        raise ConfigError('AUTH_METHOD must be password or oidc.')
    return {'mode': mode, 'url': url, 'admin_email': admin_email, 'auth_method': auth_method}
