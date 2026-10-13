import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from sqlalchemy import delete, select
from nova.models import Credential, LoginAttempt, LoginSession, User, now
from nova.services.common import BusinessError, audit, lock, require
from nova.services.numbering import ensure_row

HASHER = PasswordHasher()
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise BusinessError('Use a password or passphrase of 12–128 characters.')
    return HASHER.hash(password)


def set_password(session, actor_id, user_id, password):
    require(session, actor_id, 'users')
    user = lock(session, User, user_id)
    hashed = password_hash(password)
    credential = session.get(Credential, user_id)
    if credential:
        credential.password_hash, credential.changed_at = hashed, now()
    else:
        session.add(Credential(user_id=user_id, password_hash=hashed))
    session.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
    attempt = session.get(LoginAttempt, hashlib.sha256(user.email.encode()).hexdigest())
    if attempt:
        attempt.failures, attempt.locked_until = 0, None
    audit(session, actor_id, 'password_changed', user, {})


def authenticate(factory, email, password):
    email = str(email).strip().lower()[:200]
    key = hashlib.sha256(email.encode()).hexdigest()
    with factory.begin() as session:
        ensure_row(session, LoginAttempt, {'id': key, 'failures': 0})
        attempt = lock(session, LoginAttempt, key)
        if attempt.locked_until and aware(attempt.locked_until) > now():
            return None, 'Sign-in temporarily locked. Try again in 15 minutes.'
        if attempt.locked_until:
            attempt.failures, attempt.locked_until = 0, None
        user = session.scalar(select(User).where(User.email == email))
        credential = session.get(Credential, user.id) if user else None
        valid = False
        try:
            if isinstance(password, str) and len(password) <= 128:
                valid = HASHER.verify(credential.password_hash if credential else DUMMY_HASH, password)
        except (VerificationError, InvalidHashError):
            pass
        if not valid or not user or not user.active or not credential:
            attempt.failures += 1
            if attempt.failures >= 5:
                attempt.locked_until = now() + timedelta(minutes=15)
            return None, 'Email or password is incorrect, or the account is inactive.'
        attempt.failures, attempt.locked_until = 0, None
        if HASHER.check_needs_rehash(credential.password_hash):
            credential.password_hash = HASHER.hash(password)
        raw = secrets.token_urlsafe(48)
        session.add(LoginSession(id=hashlib.sha256(raw.encode()).hexdigest(), user_id=user.id,
                                 expires_at=now() + timedelta(hours=8)))
        audit(session, user.id, 'login', user, {})
        return raw, None


def session_user(factory, raw):
    if not raw or not isinstance(raw, str):
        return None
    with factory() as session:
        row = session.get(LoginSession, hashlib.sha256(raw.encode()).hexdigest())
        if not row or aware(row.expires_at) <= now():
            return None
        user = session.get(User, row.user_id)
        return user if user and user.active else None


def logout(factory, raw):
    if raw:
        with factory.begin() as session:
            session.execute(delete(LoginSession).where(LoginSession.id == hashlib.sha256(raw.encode()).hexdigest()))
