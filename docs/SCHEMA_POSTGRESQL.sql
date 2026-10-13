-- Schema version 4; reference DDL only. Use scripts.init_db for initialization and upgrades.

CREATE TABLE users (
	id VARCHAR(32) NOT NULL, 
	email VARCHAR(200) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	role VARCHAR(30) NOT NULL, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_users_role CHECK (role IN ('Admin', 'Accountant', 'Approver', 'Sales', 'Viewer')), 
	UNIQUE (email)
);

CREATE TABLE projects (
	id VARCHAR(32) NOT NULL, 
	number VARCHAR(40) NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	owner VARCHAR(150) NOT NULL, 
	area VARCHAR(100) NOT NULL, 
	description TEXT NOT NULL, 
	terms TEXT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (number)
);

CREATE TABLE parties (
	id VARCHAR(32) NOT NULL, 
	kind VARCHAR(30) NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	relation VARCHAR(150) NOT NULL, 
	identity VARCHAR(80) NOT NULL, 
	phone VARCHAR(50) NOT NULL, 
	email VARCHAR(200) NOT NULL, 
	city VARCHAR(100) NOT NULL, 
	province VARCHAR(100) NOT NULL, 
	address TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_parties_kind CHECK (kind IN ('Customer', 'Vendor', 'Contractor', 'Dealer', 'Landowner'))
);

CREATE TABLE accounts (
	id VARCHAR(32) NOT NULL, 
	code VARCHAR(40) NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	parent_id VARCHAR(32), 
	is_group BOOLEAN NOT NULL, 
	is_cash BOOLEAN NOT NULL, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_accounts_kind CHECK (kind IN ('Asset', 'Liability', 'Equity', 'Income', 'Expense')), 
	UNIQUE (code), 
	FOREIGN KEY(parent_id) REFERENCES accounts (id)
);

CREATE INDEX ix_accounts_parent_id ON accounts (parent_id);

CREATE TABLE settings (
	key VARCHAR(60) NOT NULL, 
	value TEXT NOT NULL, 
	PRIMARY KEY (key)
);

CREATE TABLE login_attempts (
	id VARCHAR(64) NOT NULL, 
	failures INTEGER NOT NULL, 
	locked_until TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE TABLE document_sequences (
	id VARCHAR(40) NOT NULL, 
	value BIGINT NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE financial_years (
	id VARCHAR(32) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	starts DATE NOT NULL, 
	ends DATE NOT NULL, 
	audit_status VARCHAR(30) NOT NULL, 
	auditor VARCHAR(150) NOT NULL, 
	audited_on DATE, 
	notes TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (ends >= starts), 
	CONSTRAINT ck_financial_years_audit_status CHECK (audit_status IN ('Not audited', 'In review', 'Audited')), 
	UNIQUE (name)
);

CREATE TABLE retired_codes (
	id VARCHAR(100) NOT NULL, 
	retired_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE units (
	id VARCHAR(32) NOT NULL, 
	project_id VARCHAR(32) NOT NULL, 
	number VARCHAR(50) NOT NULL, 
	category VARCHAR(50) NOT NULL, 
	floor VARCHAR(50) NOT NULL, 
	feature VARCHAR(100) NOT NULL, 
	area VARCHAR(80) NOT NULL, 
	reference VARCHAR(80) NOT NULL, 
	description TEXT NOT NULL, 
	price BIGINT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (project_id, number), 
	CHECK (price >= 0), 
	CONSTRAINT ck_units_status CHECK (status IN ('Available', 'Booked')), 
	FOREIGN KEY(project_id) REFERENCES projects (id)
);

CREATE INDEX ix_units_project_id ON units (project_id);

CREATE INDEX ix_units_status ON units (status);

CREATE TABLE vouchers (
	id VARCHAR(32) NOT NULL, 
	number VARCHAR(60) NOT NULL, 
	token VARCHAR(100) NOT NULL, 
	kind VARCHAR(30) NOT NULL, 
	project_id VARCHAR(32) NOT NULL, 
	date DATE NOT NULL, 
	description TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_by VARCHAR(32) NOT NULL, 
	approved_by VARCHAR(32), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	reversal_of VARCHAR(32), 
	payment_mode VARCHAR(40) DEFAULT '' NOT NULL, 
	payment_type VARCHAR(60) DEFAULT '' NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (status IN ('Pending', 'Posted', 'Rejected')), 
	CONSTRAINT ck_vouchers_kind CHECK (kind IN ('Journal', 'Payment', 'Cash Transfer', 'Booking', 'Receipt', 'Reversal', 'Settlement', 'Import', 'Purchase Invoice', 'Sale Invoice', 'Dealer Invoice', 'Transfer', 'Cancellation')), 
	CONSTRAINT ck_vouchers_not_self_reversal CHECK (reversal_of IS NULL OR reversal_of <> id), 
	UNIQUE (number), 
	UNIQUE (token), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(created_by) REFERENCES users (id), 
	FOREIGN KEY(approved_by) REFERENCES users (id), 
	FOREIGN KEY(reversal_of) REFERENCES vouchers (id)
);

CREATE INDEX ix_vouchers_date ON vouchers (date);

CREATE INDEX ix_vouchers_approved_by ON vouchers (approved_by);

CREATE UNIQUE INDEX ux_vouchers_effective_reversal ON vouchers (reversal_of) WHERE status <> 'Rejected';

CREATE INDEX ix_vouchers_reversal_of ON vouchers (reversal_of);

CREATE INDEX ix_vouchers_project_id ON vouchers (project_id);

CREATE INDEX ix_vouchers_created_by ON vouchers (created_by);

CREATE INDEX ix_vouchers_status ON vouchers (status);

CREATE TABLE leads (
	id VARCHAR(32) NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	phone VARCHAR(50) NOT NULL, 
	project_id VARCHAR(32) NOT NULL, 
	stage VARCHAR(30) NOT NULL, 
	notes TEXT NOT NULL, 
	next_followup DATE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_leads_stage CHECK (stage IN ('New', 'Contacted', 'Interested', 'Booked', 'Lost')), 
	FOREIGN KEY(project_id) REFERENCES projects (id)
);

CREATE INDEX ix_leads_project_id ON leads (project_id);

CREATE TABLE audit_log (
	id VARCHAR(32) NOT NULL, 
	at TIMESTAMP WITH TIME ZONE NOT NULL, 
	actor_id VARCHAR(32) NOT NULL, 
	action VARCHAR(60) NOT NULL, 
	entity VARCHAR(60) NOT NULL, 
	entity_id VARCHAR(32) NOT NULL, 
	detail TEXT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actor_id) REFERENCES users (id)
);

CREATE INDEX ix_audit_log_actor_id ON audit_log (actor_id);

CREATE INDEX ix_audit_log_at ON audit_log (at);

CREATE TABLE credentials (
	user_id VARCHAR(32) NOT NULL, 
	password_hash VARCHAR(500) NOT NULL, 
	changed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE login_sessions (
	id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(32) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_login_sessions_user_id ON login_sessions (user_id);

CREATE TABLE voucher_lines (
	id VARCHAR(32) NOT NULL, 
	voucher_id VARCHAR(32) NOT NULL, 
	account_id VARCHAR(32) NOT NULL, 
	party_id VARCHAR(32), 
	description TEXT NOT NULL, 
	debit BIGINT NOT NULL, 
	credit BIGINT NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (debit >= 0 AND credit >= 0), 
	CHECK ((debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)), 
	FOREIGN KEY(voucher_id) REFERENCES vouchers (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id), 
	FOREIGN KEY(party_id) REFERENCES parties (id)
);

CREATE INDEX ix_voucher_lines_party_id ON voucher_lines (party_id);

CREATE INDEX ix_voucher_lines_voucher_id ON voucher_lines (voucher_id);

CREATE INDEX ix_voucher_lines_account_id ON voucher_lines (account_id);

CREATE OR REPLACE FUNCTION nova_check_voucher_balance() RETURNS trigger AS $$
BEGIN
    IF TG_OP <> 'INSERT' AND EXISTS (SELECT 1 FROM voucher_lines WHERE voucher_id = OLD.voucher_id
                                     HAVING SUM(debit) <> SUM(credit)) THEN
        RAISE EXCEPTION 'Voucher % is unbalanced', OLD.voucher_id USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP <> 'DELETE' AND EXISTS (SELECT 1 FROM voucher_lines WHERE voucher_id = NEW.voucher_id
                                     HAVING SUM(debit) <> SUM(credit)) THEN
        RAISE EXCEPTION 'Voucher % is unbalanced', NEW.voucher_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_voucher_lines_balance ON voucher_lines;

CREATE CONSTRAINT TRIGGER trg_voucher_lines_balance AFTER INSERT OR UPDATE OR DELETE ON voucher_lines
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION nova_check_voucher_balance();

CREATE TABLE bookings (
	id VARCHAR(32) NOT NULL, 
	number VARCHAR(50) NOT NULL, 
	unit_id VARCHAR(32) NOT NULL, 
	party_id VARCHAR(32) NOT NULL, 
	dealer_id VARCHAR(32), 
	date DATE NOT NULL, 
	total BIGINT NOT NULL, 
	down_payment BIGINT NOT NULL, 
	commission BIGINT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	voucher_id VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (total > 0), 
	CONSTRAINT ck_bookings_down_payment CHECK (down_payment >= 0 AND down_payment <= total), 
	CONSTRAINT ck_bookings_commission CHECK (commission >= 0), 
	CONSTRAINT ck_bookings_status CHECK (status IN ('Active', 'Rejected', 'Cancelled')), 
	UNIQUE (number), 
	FOREIGN KEY(unit_id) REFERENCES units (id), 
	FOREIGN KEY(party_id) REFERENCES parties (id), 
	FOREIGN KEY(dealer_id) REFERENCES parties (id), 
	UNIQUE (voucher_id), 
	FOREIGN KEY(voucher_id) REFERENCES vouchers (id)
);

CREATE INDEX ix_bookings_dealer_id ON bookings (dealer_id);

CREATE INDEX ix_bookings_unit_id ON bookings (unit_id);

CREATE INDEX ix_bookings_party_id ON bookings (party_id);

CREATE UNIQUE INDEX ux_bookings_active_unit ON bookings (unit_id) WHERE status = 'Active';

CREATE TABLE invoices (
	id VARCHAR(32) NOT NULL, 
	reference VARCHAR(100) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	project_id VARCHAR(32) NOT NULL, 
	party_id VARCHAR(32) NOT NULL, 
	date DATE NOT NULL, 
	due DATE NOT NULL, 
	amount BIGINT NOT NULL, 
	description TEXT NOT NULL, 
	voucher_id VARCHAR(32) NOT NULL, 
	status VARCHAR(20) DEFAULT 'Active' NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (amount > 0), 
	CONSTRAINT ck_invoices_kind CHECK (kind IN ('Purchase', 'Sale', 'Dealer')), 
	CONSTRAINT ck_invoices_status CHECK (status IN ('Active', 'Rejected')), 
	CONSTRAINT ck_invoices_due CHECK (due >= date), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(party_id) REFERENCES parties (id), 
	UNIQUE (voucher_id), 
	FOREIGN KEY(voucher_id) REFERENCES vouchers (id)
);

CREATE INDEX ix_invoices_project_id ON invoices (project_id);

CREATE UNIQUE INDEX ux_invoices_active_reference ON invoices (party_id, reference, kind) WHERE status = 'Active';

CREATE TABLE attachments (
	id VARCHAR(32) NOT NULL, 
	voucher_id VARCHAR(32) NOT NULL, 
	filename VARCHAR(180) NOT NULL, 
	mime VARCHAR(80) NOT NULL, 
	data BYTEA NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(voucher_id) REFERENCES vouchers (id)
);

CREATE INDEX ix_attachments_voucher_id ON attachments (voucher_id);

CREATE TABLE installments (
	id VARCHAR(32) NOT NULL, 
	booking_id VARCHAR(32) NOT NULL, 
	sequence INTEGER NOT NULL, 
	due DATE NOT NULL, 
	amount BIGINT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (booking_id, sequence), 
	CHECK (amount > 0), 
	CONSTRAINT ck_installments_sequence CHECK (sequence >= 0), 
	FOREIGN KEY(booking_id) REFERENCES bookings (id)
);

CREATE INDEX ix_installments_booking_id ON installments (booking_id);

CREATE INDEX ix_installments_due ON installments (due);

CREATE TABLE invoice_payments (
	id VARCHAR(32) NOT NULL, 
	invoice_id VARCHAR(32) NOT NULL, 
	voucher_id VARCHAR(32) NOT NULL, 
	amount BIGINT NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (amount > 0), 
	FOREIGN KEY(invoice_id) REFERENCES invoices (id), 
	FOREIGN KEY(voucher_id) REFERENCES vouchers (id)
);

CREATE INDEX ix_invoice_payments_voucher_id ON invoice_payments (voucher_id);

CREATE INDEX ix_invoice_payments_invoice_id ON invoice_payments (invoice_id);

CREATE TABLE invoice_items (
	id VARCHAR(32) NOT NULL, 
	invoice_id VARCHAR(32) NOT NULL, 
	sequence INTEGER NOT NULL, 
	description TEXT NOT NULL, 
	amount BIGINT NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (amount > 0), 
	UNIQUE (invoice_id, sequence), 
	FOREIGN KEY(invoice_id) REFERENCES invoices (id)
);

CREATE INDEX ix_invoice_items_invoice_id ON invoice_items (invoice_id);

CREATE TABLE booking_events (
	id VARCHAR(32) NOT NULL, 
	booking_id VARCHAR(32) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	new_party_id VARCHAR(32), 
	old_party_id VARCHAR(32) NOT NULL, 
	date DATE NOT NULL, 
	reason TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_by VARCHAR(32) NOT NULL, 
	approved_by VARCHAR(32), 
	voucher_id VARCHAR(32), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_booking_events_kind CHECK (kind IN ('Transfer', 'Cancellation')), 
	CONSTRAINT ck_booking_events_status CHECK (status IN ('Pending', 'Approved', 'Rejected')), 
	CONSTRAINT ck_booking_events_transfer_party CHECK (kind <> 'Transfer' OR new_party_id IS NOT NULL), 
	FOREIGN KEY(booking_id) REFERENCES bookings (id), 
	FOREIGN KEY(new_party_id) REFERENCES parties (id), 
	FOREIGN KEY(old_party_id) REFERENCES parties (id), 
	FOREIGN KEY(created_by) REFERENCES users (id), 
	FOREIGN KEY(approved_by) REFERENCES users (id), 
	FOREIGN KEY(voucher_id) REFERENCES vouchers (id)
);

CREATE INDEX ix_booking_events_booking_id ON booking_events (booking_id);

CREATE INDEX ix_booking_events_voucher_id ON booking_events (voucher_id);

CREATE INDEX ix_booking_events_new_party_id ON booking_events (new_party_id);

CREATE INDEX ix_booking_events_old_party_id ON booking_events (old_party_id);

CREATE TABLE bank_clearances (
	id VARCHAR(32) NOT NULL, 
	line_id VARCHAR(32) NOT NULL, 
	date DATE NOT NULL, 
	reference VARCHAR(150) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (line_id), 
	FOREIGN KEY(line_id) REFERENCES voucher_lines (id)
);

CREATE TABLE receipt_allocations (
	id VARCHAR(32) NOT NULL, 
	installment_id VARCHAR(32) NOT NULL, 
	voucher_id VARCHAR(32) NOT NULL, 
	amount BIGINT NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (amount > 0), 
	FOREIGN KEY(installment_id) REFERENCES installments (id), 
	FOREIGN KEY(voucher_id) REFERENCES vouchers (id)
);

CREATE INDEX ix_receipt_allocations_installment_id ON receipt_allocations (installment_id);

CREATE INDEX ix_receipt_allocations_voucher_id ON receipt_allocations (voucher_id);
