# File map and maintenance guide

| File / folder | Responsibility | Start here for |
|---|---|---|
| `app.py` | Startup, theme, role identification, page navigation | App won't start or wrong page |
| `nova/config.py` | Environment/secret configuration and demo/production mode | Database URL or mode |
| `nova/db.py` | Engine, sessions, SQLite options, table initialization | Connection or transactions |
| `nova/models.py` | Tables, relationships, constraints | Data structure changes |
| `nova/migrations.py` | Schema version and numbered upgrade steps for existing databases | Schema changes |
| `nova/auth.py` | Demo identity selector and production verified-email access | Sign-in/access issues |
| `nova/seed.py` | Core accounts and fictional local examples | First-run sample records |
| `nova/services/common.py` | Money, permissions, locking, audit helpers, date/period checks | Validation or permissions |
| `nova/services/master.py` | Project/party/unit/account/user/lead updates and period closure | Master data and users |
| `nova/services/accounting.py` | Voucher creation, line validation, approvals, rejection, eligible reversals | Accounting postings |
| `nova/services/sales.py` | Booking, receipt allocations, invoices, settlements, transfers, cancellations | Business workflows |
| `nova/services/reports.py` | Ledger, trial balance, financial statements, installments, cashbook | Report totals |
| `nova/services/imports.py` | CSV parsing and atomic batch voucher imports | Import failures |
| `nova/ui/common.py` | Shared forms/actions, tables, exports | Table/export appearance |
| `nova/ui/masters.py` | Project/client/unit/account/lead pages and detail editing | Master screens |
| `nova/ui/transactions.py` | Voucher, allotment, invoice, ownership-event pages | Entry screens |
| `nova/ui/reporting.py` | Dashboard and report navigation/filters | Reports UI |
| `nova/ui/admin.py` | Users/audit, imports, reconciliation UI | Admin and bank screens |
| `scripts/init_db.py` | Explicit database initialization and schema upgrade | New or upgraded production database |
| `scripts/dump_schema.py` | Regenerate `docs/SCHEMA_POSTGRESQL.sql` from the models | After model changes |
| `scripts/backup.py` | Consistent SQLite or pg_dump backup | Backups |
| `scripts/check_integrity.py` | Check voucher and schedule sums | Reconciliation after restore |
| `tests/` | Automated business and app checks | Regression testing |
| `references/` | Original supplied images and hash register | Reference design continuity |
| `docs/REQUIREMENTS.md` | Confirmed scope, decisions, limits | Functional changes |
| `PROJECT_CONTEXT.md`, `CHANGELOG.md` | Persistent project decisions and release history | Continue development later |

## How to report an error

Provide: release version, page name, exact error/traceback from the VS Code terminal, reproduction steps, sample input (with personal data removed), and relevant source file. A screenshot of the affected app page helps. Do not send `.env`, filled `secrets.toml`, access tokens, passwords, or an actual accounts database as routine debugging material.

## How to make a safe change

1. Keep the extracted project in private Git. Commit the working release before editing.
2. Take a separate database backup for schema/accounting changes.
3. Change the service first for rules; change the UI only for presentation.
4. Run `python -m pytest` and the affected manual workflow. For schema changes, test a migration on a restored copy of the database.
5. Update requirements/decisions, CHANGELOG, and the version before packaging the next release.

## Schema evolution

The current schema version is **2** (`SCHEMA_VERSION` in `nova/migrations.py`). `create_all` only creates missing tables; existing databases are changed by the numbered steps in `nova/migrations.py`, which `initialize()` runs inside one transaction. A step that meets existing data violating a new rule aborts with no changes applied. For a schema change: update `nova/models.py`, add the next step to `STEPS` and bump `SCHEMA_VERSION`, run `python -m scripts.dump_schema`, and test the upgrade on a restored copy of the database. Rollback is restore-from-backup. Do not run schema-changing experiments on the active business database.

Schema version 2 adds allowed-value checks (roles, party/account/voucher/invoice/event kinds, unit/booking/event statuses, lead stages), booking amount checks, one active booking per unit, invoice due-date and self-reversal checks, and foreign-key indexes. On PostgreSQL a deferred constraint trigger also rejects any transaction that leaves a voucher's debits and credits unequal. SQLite (demo only) cannot add CHECK constraints to existing tables, so an upgraded demo database gets the new indexes only; a fresh demo database gets everything except the balance trigger.

## Known runtime patterns

- Each action uses `factory.begin()`: database changes and audit records commit together or roll back together.
- Amounts are integer paisa in the database. Float values are used only for presentation and charting.
- Posting and ownership changes lock relevant rows on PostgreSQL. SQLite obtains its writer lock before reading changing balances.
- Voucher idempotency tokens and uniqueness constraints prevent duplicate submissions. CSV project/reference pairs are stable import identities.
- Reports use posted vouchers. Pending receipts and settlements reserve balances so users cannot submit duplicate overpayments while approval is outstanding.
- PDF exports cap output at 2,000 rows; CSV/Excel include all filtered rows. Tables display 100 rows per page, but current report queries still aggregate full matching data.
- This pilot is one company with global project access per role. It does not provide per-branch or per-project permissions, accounting multi-tenancy, or an independent REST API.


## Version 0.2.0 additions

- nova/services/security.py: password hashing, authentication, throttling and server sessions.
- nova/services/numbering.py: immutable sequential document/custom-account codes.
- nova/services/records.py: safe pending edits/cancellations, unused-record deletion and financial-year administration.
- nova/services/overview.py: hierarchy, project/consolidated summary and financial mismatch diagnostics.
- nova/branding.py and assets/: supplied logo, theme and embedded print fonts.
- nova/documents.py: branded A4 voucher, invoice and booking print layouts.
- scripts/create_admin.py and setup_admin_windows.bat: trusted local password setup.
- docs/UPGRADE_0_2_0.md, REFERENCE_COVERAGE.md, TEST_RESULTS_0_2_0.md: current operating and verification records.
