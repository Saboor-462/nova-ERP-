import calendar
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from sqlalchemy import select, update
from nova.models import Audit, Setting, User

ROLES = {
    'Admin': {'master', 'entry', 'approve', 'users', 'report'},
    'Accountant': {'master', 'entry', 'report'},
    'Approver': {'approve', 'report'},
    'Sales': {'sales', 'report'},
    'Viewer': {'report'},
}


BUSINESS_TZ = ZoneInfo('Asia/Karachi')


class BusinessError(ValueError):
    pass


def _utcnow():
    return datetime.now(timezone.utc)


def business_today():
    """Today's date in Pakistan, whatever the server's own time zone (Streamlit Cloud runs in UTC)."""
    return _utcnow().astimezone(BUSINESS_TZ).date()


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > Decimal('1000000000000'):
            raise BusinessError('Enter an amount between 0 and 1 trillion PKR.')
        if amount != amount.quantize(Decimal('0.01')):
            raise BusinessError('Amounts must have at most two decimal places.')
        return int(amount * 100)
    except (InvalidOperation, TypeError):
        raise BusinessError('Enter a valid amount.')


def rupees(cents):
    return cents / 100


def require(session, actor_id, permission):
    actor = session.get(User, actor_id)
    if not actor or not actor.active or permission not in ROLES.get(actor.role, set()):
        raise BusinessError('Your account does not have permission for this action.')
    return actor


def audit(session, actor, action, record, detail):
    session.flush()
    session.add(Audit(actor_id=actor, action=action, entity=record.__tablename__, entity_id=record.id, detail=json.dumps(detail, default=str)))


def check_date(session, value):
    if not isinstance(value, date):
        raise BusinessError('A valid transaction date is required.')
    if value > business_today():
        raise BusinessError('Transaction dates cannot be in the future. Future installment due dates are allowed.')
    # Shared period gate allows concurrent PostgreSQL posting but excludes period closure.
    if session.bind.dialect.name == 'sqlite':
        session.execute(update(Setting).where(Setting.key == 'schema_version').values(value=Setting.value))
    else:
        session.scalar(select(Setting).where(Setting.key == 'schema_version').with_for_update(read=True))
    from nova.models import FinancialYear
    if session.scalar(select(FinancialYear.id).where(FinancialYear.starts <= value, FinancialYear.ends >= value, FinancialYear.audit_status == 'Audited')):
        raise BusinessError('This financial year is marked audited. An administrator must reopen its audit status for review before changes.')
    closed = session.get(Setting, 'closed_through')
    if closed and closed.value and value <= date.fromisoformat(closed.value):
        raise BusinessError(f'This period is closed through {closed.value}.')


def add_months(value, count):
    month_index = value.year * 12 + value.month - 1 + count
    year, month0 = divmod(month_index, 12)
    return date(year, month0 + 1, min(value.day, calendar.monthrange(year, month0 + 1)[1]))


def existing(session, model, record_id):
    value = session.get(model, record_id)
    if value is None:
        raise BusinessError('The selected record no longer exists.')
    return value


def lock(session, model, record_id):
    if session.bind.dialect.name == 'sqlite':
        # SQLite has no FOR UPDATE. Acquire its writer lock before reading mutable balances.
        session.execute(update(model).where(model.id == record_id).values(id=record_id))
    value = session.scalar(select(model).where(model.id == record_id).with_for_update())
    if value is None:
        raise BusinessError('The selected record no longer exists.')
    return value
