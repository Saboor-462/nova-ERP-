import re
from sqlalchemy import select
from nova.models import Account, Booking, DocumentSequence, Voucher
from nova.services.common import lock

PREFIXES = {'Journal': 'JV', 'Payment': 'PV', 'Cash Transfer': 'TR', 'Receipt': 'RC', 'Reversal': 'RV',
            'Booking': 'BV', 'Purchase Invoice': 'PI', 'Sale Invoice': 'SI', 'Dealer Invoice': 'DI',
            'Settlement': 'ST', 'Transfer': 'TF', 'Cancellation': 'CN', 'Import': 'IM'}


def ensure_row(session, model, values):
    if session.bind.dialect.name == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert
    session.execute(insert(model).values(**values).on_conflict_do_nothing(index_elements=['id']))


def next_number(session, prefix):
    ensure_row(session, DocumentSequence, {'id': prefix, 'value': 0})
    row = lock(session, DocumentSequence, prefix)
    # When a legacy DB contains sequential numbers, continue beyond them; random legacy numbers remain unchanged.
    column = Account.code if prefix == 'AC' else Booking.number if prefix == 'BK' else Voucher.number
    numbers = session.scalars(select(column).where(column.like(prefix + '-%'))).all()
    maximum = max((int(m.group(1)) for n in numbers if (m := re.fullmatch(re.escape(prefix) + r'-(\d{4,})', n))), default=0)
    row.value = max(row.value, maximum) + 1
    session.flush()
    return f'{prefix}-{row.value:04d}'
