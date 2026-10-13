import hashlib
import pandas as pd
from sqlalchemy import select
from nova.models import Account, Party, Project
from nova.services.accounting import create_voucher, line
from nova.services.common import BusinessError, money, require

COLUMNS = ['VoucherRef', 'Date', 'Project', 'AccountCode', 'PartyID', 'Description', 'Debit', 'Credit']


def parse_csv(raw):
    if len(raw) > 2 * 1024 * 1024:
        raise BusinessError('Import files must be 2 MB or smaller.')
    import io
    try:
        frame = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
    except Exception as exc:
        raise BusinessError('The file must be a valid UTF-8 CSV.') from exc
    if not set(COLUMNS).issubset(frame.columns) or frame.empty or len(frame) > 1000:
        raise BusinessError('Use the supplied template; each import must contain 1–1,000 rows.')
    return frame[COLUMNS]


def import_vouchers(session, actor, frame):
    require(session, actor, 'entry')
    if frame.empty or len(frame) > 1000:
        raise BusinessError('Import must contain 1–1,000 rows.')
    results = []
    for reference, group in frame.groupby('VoucherRef', sort=False):
        if not reference.strip() or group['Date'].nunique() != 1 or group['Project'].nunique() != 1:
            raise BusinessError('Every voucher reference needs one project and one date.')
        project = session.scalar(select(Project).where(Project.number == group.iloc[0]['Project']))
        if not project:
            raise BusinessError(f'Unknown project number for {reference}.')
        rows = []
        for _, row in group.iterrows():
            account = session.scalar(select(Account).where(Account.code == row['AccountCode']))
            if not account:
                raise BusinessError(f'Unknown account code in {reference}.')
            if account.code in ('1200', '2100'):
                raise BusinessError('Booking control accounts cannot be imported through manual vouchers. Use linked booking/invoice workflows.')
            party = row['PartyID'].strip() or None
            if party and not session.get(Party, party):
                raise BusinessError(f'Unknown PartyID in {reference}.')
            rows.append(line(account.id, money(row['Debit'].strip() or '0'), money(row['Credit'].strip() or '0'), party, row['Description']))
        from datetime import date
        try:
            on = date.fromisoformat(group.iloc[0]['Date'])
        except ValueError as exc:
            raise BusinessError(f'Date must be YYYY-MM-DD in {reference}.') from exc
        token = 'import:' + hashlib.sha256(f'{project.id}:{reference}'.encode()).hexdigest()
        obj = create_voucher(session, actor, project.id, on, 'Import', f'Imported {reference}', rows, token)
        results.append(obj.number)
    return results
