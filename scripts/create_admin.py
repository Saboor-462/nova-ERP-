"""Interactive local administrator/password setup. Never seeds financial records."""
from getpass import getpass
from sqlalchemy import select
from sqlalchemy import inspect
from nova.config import settings
from nova.db import engine, initialize, session_factory
from nova.migrations import needs_upgrade
from nova.models import User
from nova.seed import bootstrap
from nova.services.security import set_password


def main():
    cfg = settings()
    bind = engine()
    if 'settings' in inspect(bind).get_table_names() and needs_upgrade(bind):
        raise SystemExit('Run python -m scripts.init_db first; it backs up and upgrades your existing database.')
    initialize()
    email = input('Administrator email: ').strip().lower()
    name = input('Display name: ').strip()
    password = getpass('Password/passphrase (12–128 characters): ')
    if password != getpass('Confirm password: '):
        raise SystemExit('Passwords do not match. No account was changed.')
    if '@' not in email or not name:
        raise SystemExit('A valid email and display name are required.')
    with session_factory().begin() as session:
        bootstrap(session, mode=cfg['mode'], sample=False)
        user = session.scalar(select(User).where(User.email == email))
        if not user:
            user = User(email=email, name=name, role='Admin', active=True)
            session.add(user)
            session.flush()
        elif user.role != 'Admin' or not user.active:
            raise SystemExit('This email belongs to an inactive or non-administrator account. Use another email.')
        set_password(session, user.id, user.id, password)
    print('Administrator password set. Start the app and sign in. No business records were created or reset.')


if __name__ == '__main__':
    main()
