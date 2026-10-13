# Change log

## 0.2.0 — 2026-10-13

- Preserved the uploaded audited code and original fixes; extended schema to version 4 with additive login/sequence/year/item tables and payment fields.
- Added real email/password login, Argon2id password hashes, server sessions, logout/revocation/throttling, and local administrator setup. Removed role-switching access from the interface.
- Fresh initialization now creates only core accounts/groups; no fictitious business records or password are installed.
- Added stable type-specific sequential voucher/booking numbers and optional automatic custom account codes. Existing IDs/codes/document numbers remain unchanged.
- Added pending financial edits/cancellations, safe unused-master deletion, account hierarchy editing, invoice cancellation reversal, and pending ownership-request edits.
- Added Nova branding, configurable print header, itemized invoice rows, embedded print fonts, and professionally rendered A4 invoices/vouchers/booking forms.
- Added current/non-current account groups, furniture/equipment accounts, financial years and external audit status, hierarchy/consolidated financial views, dealer commission/down-payment summaries, filters and red exceptions.
- Added upgrade, coverage and current verification documents, with regression tests for new behaviours.
- Corrected legacy workflow test dates to use Pakistan time. Adapted UI tests to authenticate, recognize deliberate pending alerts, and verify the new interface; preservation assertions still check every original table/record.


## Unreleased — schema version 3 (audit fixes; see AUDIT_REPORT.md)

**Upgrade required:** stop the app, then run `python -m scripts.init_db` (SQLite: automatic pre-upgrade backup; PostgreSQL: back up with `scripts.backup`, then add `--postgres-backup-done`). The app no longer upgrades an existing database at startup.

- Security: demo mode (role switching, self-approval, sample seeding) now runs only on the local `data/demo.db`. Configuration with `DATABASE_URL` but no `APP_MODE`, or demo mode with any other database, stops with a clear error. Streamlit secrets are always read. Production checks the PostgreSQL URL, `ADMIN_EMAIL` format, and that sign-in (`[auth]`) is configured.
- Security: configuration, migration, and database errors show fixed messages; logs remove credentials; SQL parameters are hidden from exceptions; uncaught errors show only their type in the browser.
- Security: customer names, descriptions, filenames, and quoted input are escaped before Markdown display.
- Accounting: control accounts (1200, 2000, 2100, 2200, 2300) require a party of the correct type on every line, enforced in the service layer; manual vouchers and imports cannot post 1200/2100; purchase invoices reject control accounts. Reversals of earlier untagged entries remain possible.
- Accounting: report totals, balance sheet check, dashboard, and bank reconciliation are computed in integer paisa; rupees are produced only for display and export.
- Invoices: new `status` column. A rejected invoice is kept (with its audit history) and its reference can be reused; pending and rejected invoices are excluded from Invoice Balances (pending ones are listed separately) and from settlement choices.
- Reversals: rejected reversal attempts keep their link to the original voucher (links removed by 0.1.0 are restored from the audit log during upgrade); the database allows only one pending/posted reversal per voucher.
- Dates: one Asia/Karachi business-date helper for validation, defaults, reports, period close, and sample data (`tzdata` added to requirements).
- Period close also waits for pending transfer and cancellation requests dated in the period.
- Manual voucher grid: blank cells become zero, empty rows are ignored, partial rows are rejected with the row number, blank descriptions are stored as empty text.
- Added `scripts/package_release.py` (source-only release ZIP) and broader `.gitignore` patterns for databases and archives.
- `reset_demo.py` now requires schema version 3.
- Tests: 44 new regression tests (`tests/test_audit_fixes.py`, `tests/fixtures/schema_v2_sqlite.sql`); test configuration is isolated from the real database and secrets.

## Schema version 2

- Added database-level checks for allowed roles, kinds, statuses and lead stages; booking down payment/commission; invoice due date; installment sequence; transfer party; and voucher self-reversal.
- Added a partial unique index allowing one active booking per unit, and indexes on foreign keys used by joins and reports.
- PostgreSQL: added a deferred constraint trigger that rejects unbalanced vouchers at commit.
- Added `nova/migrations.py` (numbered schema upgrades, run by `scripts.init_db` and demo startup) and `scripts/dump_schema.py`; regenerated `docs/SCHEMA_POSTGRESQL.sql`.

## 0.1.0 — 2026-10-09

- Initial modular Streamlit ERP, screenshot register, and requirements/decision records.
- Connected project, property, customer, booking, installment, receipt, invoice, and general ledger workflows.
- Added balanced vouchers, approval separation in production, atomic imports, receipt/payment reservation checks, and ownership event posting.
- Added dashboard, financial/party/installment reports, exports, cash/bank reconciliation, roles, audit history, and period closure.
- Added Windows setup/run/test scripts, backup/integrity tools, and local automated testing.
- Production database and OIDC testing remain user-environment acceptance steps.
