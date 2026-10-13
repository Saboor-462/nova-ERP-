from sqlalchemy import func, select
from nova.db import session_factory
from nova.models import Booking, Installment, Line, Voucher


def main():
    with session_factory()() as session:
        unbalanced = session.execute(select(Voucher.number, func.sum(Line.debit), func.sum(Line.credit))
                                      .join(Line, Line.voucher_id == Voucher.id).group_by(Voucher.id, Voucher.number)
                                      .having(func.sum(Line.debit) != func.sum(Line.credit))).all()
        schedules = session.execute(select(Booking.number, Booking.total, func.sum(Installment.amount)).join(Installment)
                                     .group_by(Booking.id, Booking.number, Booking.total).having(Booking.total != func.sum(Installment.amount))).all()
    if unbalanced or schedules:
        raise SystemExit(f'Integrity check failed: {len(unbalanced)} unbalanced vouchers; {len(schedules)} inconsistent schedules.')
    print('Integrity check passed: all vouchers and booking schedules balance.')


if __name__ == '__main__':
    main()
