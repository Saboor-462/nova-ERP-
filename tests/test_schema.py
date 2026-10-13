import pytest
from sqlalchemy import inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.dialects import postgresql
from nova.db import initialize, make_engine, session_factory
from nova.migrations import SCHEMA_VERSION
from nova.models import Base, Booking, Setting
from nova.seed import bootstrap


def test_new_database_is_current(db):
    factory, _ = db
    with factory() as session:
        assert session.get(Setting, 'schema_version').value == SCHEMA_VERSION


@pytest.mark.parametrize('statement', [
    "UPDATE units SET status = 'Sold'",
    "UPDATE parties SET kind = 'Friend'",
    "UPDATE users SET role = 'Root'",
    "UPDATE bookings SET down_payment = total + 1",
    "UPDATE bookings SET commission = -1",
    "UPDATE vouchers SET reversal_of = id",
    "UPDATE invoices SET due = '2000-01-01'",
])
def test_constraints_reject_invalid_rows(db, statement):
    factory, _ = db
    with pytest.raises(IntegrityError):
        with factory.begin() as session:
            session.execute(text(statement))


def test_one_active_booking_per_unit(db):
    factory, _ = db
    with factory() as session:
        booking = session.scalar(select(Booking).where(Booking.status == 'Active'))
    with pytest.raises(IntegrityError):
        with factory.begin() as session:
            session.execute(update(Booking).where(Booking.status == 'Active', Booking.id != booking.id).values(unit_id=booking.unit_id))
    with factory.begin() as session:
        # Rejected/cancelled bookings may share a unit with a live booking.
        session.execute(update(Booking).where(Booking.id != booking.id).values(status='Cancelled', unit_id=booking.unit_id))


def test_upgrade_from_version_1(tmp_path):
    engine = make_engine(f'sqlite:///{tmp_path / "old.db"}')
    initialize(engine)
    with session_factory(engine).begin() as session:
        bootstrap(session)
    added = ['ux_bookings_active_unit', 'ix_vouchers_created_by', 'ix_audit_log_actor_id']
    with engine.begin() as connection:
        for name in added:
            connection.execute(text(f'DROP INDEX {name}'))
        connection.execute(update(Setting).where(Setting.key == 'schema_version').values(value='1'))
    initialize(engine)
    names = {i['name'] for t in ('bookings', 'vouchers', 'audit_log') for i in inspect(engine).get_indexes(t)}
    assert set(added) <= names
    with session_factory(engine)() as session:
        assert session.get(Setting, 'schema_version').value == SCHEMA_VERSION
    engine.dispose()


def test_postgresql_ddl_compiles():
    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        str(CreateTable(table).compile(dialect=dialect))
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=dialect))
