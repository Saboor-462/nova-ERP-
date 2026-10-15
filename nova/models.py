from datetime import date, datetime, timezone
from uuid import uuid4
from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DDL, Date, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text,
                        UniqueConstraint, event, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return uuid4().hex


def now():
    return datetime.now(timezone.utc)


def one_of(table, column, values):
    return CheckConstraint(f"{column} IN ({', '.join(repr(v) for v in values)})", name=f'ck_{table}_{column}')


ROLES = ('Admin', 'Accountant', 'Approver', 'Sales', 'Viewer')
PARTY_KINDS = ('Customer', 'Vendor', 'Contractor', 'Dealer', 'Landowner')
ACCOUNT_KINDS = ('Asset', 'Liability', 'Equity', 'Income', 'Expense')
VOUCHER_KINDS = ('Journal', 'Payment', 'Cash Transfer', 'Booking', 'Receipt', 'Reversal', 'Settlement', 'Import',
                 'Purchase Invoice', 'Sale Invoice', 'Dealer Invoice', 'Transfer', 'Cancellation')
LEAD_STAGES = ('New', 'Contacted', 'Interested', 'Booked', 'Lost')


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    __table_args__ = (one_of('users', 'role', ROLES),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Project(Base):
    __tablename__ = 'projects'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    number: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    owner: Mapped[str] = mapped_column(String(150), default='')
    area: Mapped[str] = mapped_column(String(100), default='')
    description: Mapped[str] = mapped_column(Text, default='')
    terms: Mapped[str] = mapped_column(Text, default='')


class Party(Base):
    __tablename__ = 'parties'
    __table_args__ = (one_of('parties', 'kind', PARTY_KINDS),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    relation: Mapped[str] = mapped_column(String(150), default='')
    identity: Mapped[str] = mapped_column(String(80), default='')
    phone: Mapped[str] = mapped_column(String(50), default='')
    email: Mapped[str] = mapped_column(String(200), default='')
    city: Mapped[str] = mapped_column(String(100), default='')
    province: Mapped[str] = mapped_column(String(100), default='')
    address: Mapped[str] = mapped_column(Text, default='')


class Account(Base):
    __tablename__ = 'accounts'
    __table_args__ = (one_of('accounts', 'kind', ACCOUNT_KINDS),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    kind: Mapped[str] = mapped_column(String(20))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey('accounts.id'), index=True)
    is_group: Mapped[bool] = mapped_column(Boolean, default=False)
    is_cash: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Unit(Base):
    __tablename__ = 'units'
    __table_args__ = (UniqueConstraint('project_id', 'number'), CheckConstraint('price >= 0'), one_of('units', 'status', ('Available', 'Booked')))
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    number: Mapped[str] = mapped_column(String(50))
    category: Mapped[str] = mapped_column(String(50), default='Commercial')
    floor: Mapped[str] = mapped_column(String(50), default='Ground')
    feature: Mapped[str] = mapped_column(String(100), default='Standard')
    area: Mapped[str] = mapped_column(String(80), default='')
    reference: Mapped[str] = mapped_column(String(80), default='')
    description: Mapped[str] = mapped_column(Text, default='')
    price: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default='Available', index=True)


class Voucher(Base):
    __tablename__ = 'vouchers'
    __table_args__ = (CheckConstraint("status IN ('Pending', 'Posted', 'Rejected')"), one_of('vouchers', 'kind', VOUCHER_KINDS),
                      CheckConstraint('reversal_of IS NULL OR reversal_of <> id', name='ck_vouchers_not_self_reversal'),
                      # Rejected reversal attempts keep their link; only one pending/posted reversal per original.
                      Index('ux_vouchers_effective_reversal', 'reversal_of', unique=True,
                            postgresql_where=text("status <> 'Rejected'"), sqlite_where=text("status <> 'Rejected'")))
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    number: Mapped[str] = mapped_column(String(60), unique=True)
    token: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(30))
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default='Pending', index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reversal_of: Mapped[str | None] = mapped_column(ForeignKey('vouchers.id'), index=True)
    payment_mode: Mapped[str] = mapped_column(String(40), default='', server_default='')
    payment_type: Mapped[str] = mapped_column(String(60), default='', server_default='')


class Line(Base):
    __tablename__ = 'voucher_lines'
    __table_args__ = (CheckConstraint('debit >= 0 AND credit >= 0'), CheckConstraint('(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)'))
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    voucher_id: Mapped[str] = mapped_column(ForeignKey('vouchers.id'), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey('accounts.id'), index=True)
    party_id: Mapped[str | None] = mapped_column(ForeignKey('parties.id'), index=True)
    description: Mapped[str] = mapped_column(Text, default='')
    debit: Mapped[int] = mapped_column(BigInteger, default=0)
    credit: Mapped[int] = mapped_column(BigInteger, default=0)


class Booking(Base):
    __tablename__ = 'bookings'
    __table_args__ = (CheckConstraint('total > 0'),
                      CheckConstraint('down_payment >= 0 AND down_payment <= total', name='ck_bookings_down_payment'),
                      CheckConstraint('commission >= 0', name='ck_bookings_commission'),
                      one_of('bookings', 'status', ('Active', 'Rejected', 'Cancelled')),
                      # One live booking per unit; rejected/cancelled bookings release the unit.
                      Index('ux_bookings_active_unit', 'unit_id', unique=True,
                            postgresql_where=text("status = 'Active'"), sqlite_where=text("status = 'Active'")))
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    number: Mapped[str] = mapped_column(String(50), unique=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey('units.id'), index=True)
    party_id: Mapped[str] = mapped_column(ForeignKey('parties.id'), index=True)
    dealer_id: Mapped[str | None] = mapped_column(ForeignKey('parties.id'), index=True)
    date: Mapped[date] = mapped_column(Date)
    total: Mapped[int] = mapped_column(BigInteger)
    down_payment: Mapped[int] = mapped_column(BigInteger)
    commission: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(20), default='Active')
    voucher_id: Mapped[str] = mapped_column(ForeignKey('vouchers.id'), unique=True)


class Installment(Base):
    __tablename__ = 'installments'
    __table_args__ = (UniqueConstraint('booking_id', 'sequence'), CheckConstraint('amount > 0'),
                      CheckConstraint('sequence >= 0', name='ck_installments_sequence'))
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    booking_id: Mapped[str] = mapped_column(ForeignKey('bookings.id'), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    due: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[int] = mapped_column(BigInteger)


class Allocation(Base):
    __tablename__ = 'receipt_allocations'
    __table_args__ = (CheckConstraint('amount > 0'),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    installment_id: Mapped[str] = mapped_column(ForeignKey('installments.id'), index=True)
    voucher_id: Mapped[str] = mapped_column(ForeignKey('vouchers.id'), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)


class Invoice(Base):
    __tablename__ = 'invoices'
    __table_args__ = (CheckConstraint('amount > 0'), one_of('invoices', 'kind', ('Purchase', 'Sale', 'Dealer')),
                      one_of('invoices', 'status', ('Active', 'Rejected')), CheckConstraint('due >= date', name='ck_invoices_due'),
                      # A rejected invoice is kept for history; its reference may be reused by a corrected invoice.
                      Index('ux_invoices_active_reference', 'party_id', 'reference', 'kind', unique=True,
                            postgresql_where=text("status = 'Active'"), sqlite_where=text("status = 'Active'")))
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    reference: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    party_id: Mapped[str] = mapped_column(ForeignKey('parties.id'))
    date: Mapped[date] = mapped_column(Date)
    due: Mapped[date] = mapped_column(Date)
    amount: Mapped[int] = mapped_column(BigInteger)
    description: Mapped[str] = mapped_column(Text)
    voucher_id: Mapped[str] = mapped_column(ForeignKey('vouchers.id'), unique=True)
    status: Mapped[str] = mapped_column(String(20), default='Active', server_default='Active')


class InvoicePayment(Base):
    __tablename__ = 'invoice_payments'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    invoice_id: Mapped[str] = mapped_column(ForeignKey('invoices.id'), index=True)
    voucher_id: Mapped[str] = mapped_column(ForeignKey('vouchers.id'), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (CheckConstraint('amount > 0'),)


class InvoiceItem(Base):
    __tablename__ = 'invoice_items'
    __table_args__ = (CheckConstraint('amount > 0'), UniqueConstraint('invoice_id', 'sequence'))
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    invoice_id: Mapped[str] = mapped_column(ForeignKey('invoices.id'), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    amount: Mapped[int] = mapped_column(BigInteger)


class InvoiceCorrection(Base):
    __tablename__ = 'invoice_corrections'
    __table_args__ = (
        one_of('invoice_corrections', 'status', ('Pending', 'Approved', 'Rejected')),
        Index('ux_invoice_corrections_pending', 'invoice_id', unique=True,
              postgresql_where=text("status = 'Pending'"), sqlite_where=text("status = 'Pending'")),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    invoice_id: Mapped[str] = mapped_column(ForeignKey('invoices.id'), index=True)
    token: Mapped[str] = mapped_column(String(100), unique=True)
    effective_on: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    before_data: Mapped[str] = mapped_column(Text)
    after_data: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default='Pending', index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str] = mapped_column(Text, default='')
    voucher_id: Mapped[str | None] = mapped_column(ForeignKey('vouchers.id'), unique=True)


class BookingEvent(Base):
    __tablename__ = 'booking_events'
    __table_args__ = (one_of('booking_events', 'kind', ('Transfer', 'Cancellation')), one_of('booking_events', 'status', ('Pending', 'Approved', 'Rejected')),
                      CheckConstraint("kind <> 'Transfer' OR new_party_id IS NOT NULL", name='ck_booking_events_transfer_party'))
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    booking_id: Mapped[str] = mapped_column(ForeignKey('bookings.id'), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    new_party_id: Mapped[str | None] = mapped_column(ForeignKey('parties.id'), index=True)
    old_party_id: Mapped[str] = mapped_column(ForeignKey('parties.id'), index=True)
    date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default='Pending')
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    voucher_id: Mapped[str | None] = mapped_column(ForeignKey('vouchers.id'), index=True)


class Lead(Base):
    __tablename__ = 'leads'
    __table_args__ = (one_of('leads', 'stage', LEAD_STAGES),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(50))
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    stage: Mapped[str] = mapped_column(String(30), default='New')
    notes: Mapped[str] = mapped_column(Text, default='')
    next_followup: Mapped[date] = mapped_column(Date)


class Attachment(Base):
    __tablename__ = 'attachments'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    voucher_id: Mapped[str] = mapped_column(ForeignKey('vouchers.id'), index=True)
    filename: Mapped[str] = mapped_column(String(180))
    mime: Mapped[str] = mapped_column(String(80))
    data: Mapped[bytes] = mapped_column(LargeBinary)


class Audit(Base):
    __tablename__ = 'audit_log'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text)


class Setting(Base):
    __tablename__ = 'settings'
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Clearance(Base):
    __tablename__ = 'bank_clearances'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    line_id: Mapped[str] = mapped_column(ForeignKey('voucher_lines.id'), unique=True)
    date: Mapped[date] = mapped_column(Date)
    reference: Mapped[str] = mapped_column(String(150))


class Credential(Base):
    __tablename__ = 'credentials'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LoginSession(Base):
    __tablename__ = 'login_sessions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentSequence(Base):
    __tablename__ = 'document_sequences'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, default=0)


class FinancialYear(Base):
    __tablename__ = 'financial_years'
    __table_args__ = (CheckConstraint('ends >= starts'), one_of('financial_years', 'audit_status', ('Not audited', 'In review', 'Audited')))
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    starts: Mapped[date] = mapped_column(Date)
    ends: Mapped[date] = mapped_column(Date)
    audit_status: Mapped[str] = mapped_column(String(30), default='Not audited')
    auditor: Mapped[str] = mapped_column(String(150), default='')
    audited_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default='')


class RetiredCode(Base):
    __tablename__ = 'retired_codes'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    retired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# PostgreSQL only: every voucher's lines must balance when the transaction commits.
# SQLite (demo) relies on validate_lines and scripts.check_integrity.
VOUCHER_BALANCE_DDL = [
    """CREATE OR REPLACE FUNCTION nova_check_voucher_balance() RETURNS trigger AS $$
BEGIN
    IF TG_OP <> 'INSERT' AND EXISTS (SELECT 1 FROM voucher_lines WHERE voucher_id = OLD.voucher_id
                                     HAVING SUM(debit) <> SUM(credit)) THEN
        RAISE EXCEPTION 'Voucher %% is unbalanced', OLD.voucher_id USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP <> 'DELETE' AND EXISTS (SELECT 1 FROM voucher_lines WHERE voucher_id = NEW.voucher_id
                                     HAVING SUM(debit) <> SUM(credit)) THEN
        RAISE EXCEPTION 'Voucher %% is unbalanced', NEW.voucher_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END
$$ LANGUAGE plpgsql""",
    'DROP TRIGGER IF EXISTS trg_voucher_lines_balance ON voucher_lines',
    """CREATE CONSTRAINT TRIGGER trg_voucher_lines_balance AFTER INSERT OR UPDATE OR DELETE ON voucher_lines
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION nova_check_voucher_balance()""",
]
for statement in VOUCHER_BALANCE_DDL:
    event.listen(Line.__table__, 'after_create', DDL(statement).execute_if(dialect='postgresql'))
