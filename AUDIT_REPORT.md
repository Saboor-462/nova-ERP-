# Nova ERP audit — findings and fixes

Release 0.1.0 → unreleased (schema version 3). Audit and fixes made on 2026-10-10.

This report lists each confirmed issue, how it was fixed, the files changed, how the fixes were tested, and what still needs a decision. Passing tests show that the listed behaviours work as described in the tested setups. **They do not show that the ERP is secure or ready for production.** Production use still needs the acceptance checks in `docs/SETUP.md` and an accountant's review of the pilot accounting policies.

What I did not touch: your `data/` database, `backups/`, attachments, and any secrets. None were read, migrated, reset or deleted. All testing used temporary SQLite files and a throwaway PostgreSQL 15 cluster, both with fictional data. A source-only backup of the original code is in `..\source_backup_20261010-164012\` (no databases, secrets, backups or reference photos).

---

## Action required before using the app again

The app now refuses to start on your existing `data/demo.db` (schema 2). It shows the command to run instead of migrating by itself.

**Local SQLite (your demo database):**
1. Stop the app.
2. Run `.venv\Scripts\python.exe -m scripts.init_db`.
   - It first writes a consistent copy to `backups\before-upgrade-v3-<time>.db`.
   - It then upgrades the database in a single transaction. If any existing row breaks a new rule, nothing changes, and the details go to the console log.
3. Optional: run `.venv\Scripts\python.exe -m scripts.check_integrity`.
4. Start the app as usual.

To roll back: stop the app, delete `data\demo.db`, `demo.db-wal` and `demo.db-shm`, then copy the backup file to `data\demo.db`. Note that the 0.1.0 code is needed to open a schema-2 database.

**PostgreSQL (production):**
1. Run `python -m scripts.backup --output <new file>.dump`.
2. Run `python -m scripts.init_db --postgres-backup-done`.

The upgrade runs in one transaction. I tested it on PostgreSQL 15.14, but not on Supabase.

**What the migration changes (schema 2 → 3):**
- `invoices`: adds a `status` column (`Active`/`Rejected`), set from each invoice's voucher. The unique rule on (party, reference, type) is replaced by a partial unique index that covers active invoices only.
- `vouchers`: the unique rule on `reversal_of` is replaced by a partial unique index on pending and posted reversals only, plus a plain index. Rejected reversals that 0.1.0 had unlinked get their link back from the audit log.
- On SQLite, both tables are rebuilt, because SQLite cannot drop a UNIQUE constraint. Every row is copied, and foreign keys are checked before the commit.

**Optional check before approving old pending entries.** The new party-tagging rule (fix 8) also applies when a pending voucher is approved. You can run this read-only query yourself, against your own database, to list pending vouchers that will now be refused. Reject and re-enter any it finds.

```sql
SELECT v.number, a.code
FROM vouchers v JOIN voucher_lines l ON l.voucher_id = v.id JOIN accounts a ON a.id = l.account_id
LEFT JOIN parties p ON p.id = l.party_id
WHERE v.status = 'Pending' AND v.kind <> 'Reversal' AND (
  (a.code IN ('1200','2100','2200') AND (p.kind IS NULL OR p.kind <> 'Customer')) OR
  (a.code = '2000' AND (p.kind IS NULL OR p.kind NOT IN ('Vendor','Contractor','Landowner'))) OR
  (a.code = '2300' AND (p.kind IS NULL OR p.kind <> 'Dealer')) OR
  (a.code IN ('1200','2100') AND v.kind IN ('Journal','Payment','Cash Transfer','Import')));
```

---

## Issues and resolutions

### 1. Demo mode could run against a real database without sign-in (High)
**Problem:**
- `APP_MODE` defaulted to `demo`, and Streamlit secrets were read only in some cases.
- Demo mode accepted any database, including PostgreSQL. Anyone opening the app could then choose any real user, including an Admin, approve their own entries, and seed sample records into real books.

**Fix:**
- Configuration always reads Streamlit `[erp]` secrets. They still override environment variables.
- Demo mode is allowed only when the database is the local `data/demo.db`. If `DATABASE_URL` is set without `APP_MODE`, or demo mode is used with any other database, the app stops with a clear configuration error.
- Production mode validates the PostgreSQL URL (host and database name) and the `ADMIN_EMAIL` format, and checks that sign-in (`[auth]`) is configured.
- Two further guards refuse anything other than SQLite even if configuration were bypassed: demo role switching (`auth.py`) and sample seeding (`seed.py`).
- Local SQLite operation is unchanged.

**Files:** `nova/config.py`, `nova/auth.py`, `nova/seed.py`, `app.py`.

### 2. Invoice status and references (Medium)
**Problem:**
- Rejected and pending invoices counted as outstanding.
- A rejected invoice permanently blocked its reference.
- Rejected invoices appeared in the settlement list.

**Fix:**
- Invoices have a `status`. Rejecting an invoice's voucher marks it `Rejected`. The record and its audit trail are kept.
- A corrected invoice may reuse the reference. Duplicates among active invoices are still refused, by the service with a clear message and by the database's partial unique index.
- Invoice Balances (report and page) counts only approved, active invoices. The Invoices page lists pending invoices separately, without balances.
- Settlement offers only approved, active invoices, and the service checks this too.

**Files:** `nova/models.py`, `nova/migrations.py`, `nova/services/accounting.py`, `nova/services/sales.py`, `nova/services/reports.py`, `nova/ui/transactions.py`, `nova/ui/reporting.py`.

### 3. Server date instead of Pakistan date (Medium)
**Problem:** "Today" came from the server clock. On a UTC host, entries dated today were refused as future dates between 00:00 and 04:59 PKT.

**Fix:**
- One helper, `business_today()` in `nova/services/common.py`, uses Asia/Karachi.
- It is used for transaction validation, period close, every default date field, report as-of dates, the fiscal-year default, and sample data.
- `tzdata` is pinned in `requirements.txt`, because Windows has no built-in time-zone database.
- A test checks that no `date.today()` calls remain in the app code.

**Files:** `nova/services/common.py`, `nova/services/master.py`, `nova/services/reports.py`, `nova/seed.py`, `nova/ui/*.py`, `requirements.txt`.

### 4. Money totals added as floating-point rupees (Medium)
**Problem:** Report rows were converted to float rupees before being added up, so totals and the balance-sheet check could drift by fractions of a paisa.

**Fix:**
- All report functions compute in integer paisa. Each takes `paisa=True` to return integers.
- The dashboard, balance-sheet check (now an exact comparison), report groupings and totals, voucher totals and bank reconciliation all add up integers.
- Rupees are produced only for display and export, through `reports.to_rupees`.
- The default output of the report functions is unchanged, so screens and exports look the same.

**Files:** `nova/services/reports.py`, `nova/ui/reporting.py`, `nova/ui/admin.py`, `nova/ui/transactions.py`.

### 5. Manual voucher grid input (Low)
**Problem:** Blank cells in added rows raised "Enter a valid amount", and blank descriptions were stored as the text "None".

**Fix:** The new `voucher_rows()` function:
- treats blank amounts as 0;
- ignores completely empty rows;
- rejects partly filled rows with the row number (missing account, unknown party, both or neither amount, invalid amount);
- stores blank descriptions as empty text.

CSV imports now also trim blank amount cells.

**Files:** `nova/ui/transactions.py`, `nova/services/imports.py`.

### 6. Period close could trap pending ownership requests (Low)
**Problem:** Closing a period checked only pending vouchers. A pending transfer or cancellation dated in the closed period could no longer be approved.

**Fix:**
- Closing now also requires that no transfer or cancellation request dated in the period is still pending.
- Existing protections still apply: posting, approving and creating requests in a closed period are refused.
- A request already trapped by 0.1.0 can still be rejected and re-entered with a current date.

**Files:** `nova/services/master.py`.

### 7. User-entered text displayed as Markdown (Low)
**Problem:** Customer names, descriptions, attachment filenames and some error messages were displayed as Markdown. Stored text could therefore show links, load remote images, or apply formatting.

**Fix:**
- `md_escape()` in `nova/ui/common.py` escapes every punctuation character and joins lines.
- It is applied wherever user text is combined with app formatting: the voucher caption, the booking heading, attachment buttons, the control-account caption, the sidebar user name, and error messages that can quote user input (for example, an import reference).
- App labels keep their formatting.
- Tables and PDFs were already safe.

**Files:** `nova/ui/common.py`, `nova/ui/transactions.py`, `nova/ui/reporting.py`, `nova/ui/admin.py`, `nova/auth.py`.

### 8. Control accounts were protected only by the screens (Low)
**Problem:** The service layer itself did not stop a purchase invoice posting to customer receivables (1200), or payables and refunds being posted with no party.

**Fix:** `validate_lines` enforces these rules on every voucher, including on approval:

| Account | Party required on the line |
|---|---|
| 1200 Customer receivables, 2100 Booking obligations, 2200 Refunds payable | Customer |
| 2000 Vendor/contractor payable | Vendor, Contractor, or Landowner |
| 2300 Dealer commission payable | Dealer |

- Manual vouchers and imports cannot post 1200 or 2100 at all.
- Invoices cannot use a control account as their posting account.
- The linked workflows (booking, receipt, invoice, settlement, transfer, cancellation) already tag parties correctly and work unchanged.
- Reversals are exempt, because they mirror an approved original line for line. Entries made before this rule existed can therefore still be reversed.

**Files:** `nova/services/accounting.py`, `nova/services/sales.py`.

### 9. Error details shown in the browser (Low)
**Problem:** Database and migration errors could show raw details in the page.

**Fix:**
- Configuration and migration errors use fixed, safe messages (`ConfigError`, `MigrationError`).
- Other startup, page and database failures show generic messages.
- Server logs go through `nova/diagnostics.py`, which removes credentials from URLs and from password and token fields.
- The engine runs with `hide_parameters=True`, so customer values never appear in exception text.
- `.streamlit/config.toml` sets `showErrorDetails = "type"`, so uncaught errors show only their type in the browser.

**Files:** `nova/config.py`, `nova/diagnostics.py`, `nova/db.py`, `nova/migrations.py`, `nova/ui/common.py`, `app.py`, `.streamlit/config.toml`, `scripts/init_db.py`.

### 10. Reversal history was erased (Low)
**Problem:** Asking for a new reversal after a rejected one removed the rejected attempt's link to its original voucher.

**Fix:**
- Links are never removed. Rejected attempts keep `reversal_of`.
- The database allows only one pending or posted reversal per voucher, through the partial unique index `ux_vouchers_effective_reversal`.
- `approve()` also refuses a second posted reversal.
- The upgrade restores links that 0.1.0 removed, using the audit log.

**Files:** `nova/models.py`, `nova/migrations.py`, `nova/services/accounting.py`.

### 11. Other observations

**Release packaging:**
- New `scripts/package_release.py` builds a source-only ZIP from an allowlist: code, tests, docs and example config.
- It refuses any database, dump, secrets file, `.env`, photo or PDF, and it must write outside the project folder.
- `.gitignore` now also covers `*.db*`, `*.sqlite*` and `*.zip`.
- The current folder still contains `data/` and `backups/`. Don't zip the folder by hand to share it.

**Duplicate administrator identities (explanation; no change made):**
- Two-person approval only checks that the creator's account ID differs from the approver's.
- An Admin can add a second account on another email they control and approve their own entries.
- Different account IDs therefore don't prove different people. The control depends on who is allowed to manage users.
- Possible mitigations, which need your policy decision:
  - require a second Admin to confirm role changes;
  - stop a user approving within N days of being created or promoted;
  - review the audit log's `save_user` entries regularly.

**Sensitive customer fields (proposal; not implemented, needs your decision):**
- Today every role can see CNIC numbers, phone numbers and addresses on the Clients page, and can download voucher attachments.
- The smallest change consistent with the existing roles would be:
  - show CNIC and address only to roles with `master` (Admin, Accountant);
  - mask CNIC to its last 4 digits for Sales, Approver and Viewer;
  - keep phone numbers visible to Sales, who need them for follow-up;
  - limit attachment downloads to `entry` and `approve` roles.
- Please confirm or adjust this before I implement it.

---

## Tests run and results

All runs used Python 3.14.7 (the project `.venv`; the docs name 3.12), pytest, SQLAlchemy 2.0.54, Streamlit 1.65.0 and pandas 2.2.3.

| Run | Result |
|---|---|
| Existing suite, before any change (baseline) | 33 passed |
| Complete suite after the fixes (`python -m pytest`) | **77 passed** (33 existing + 44 new), 91 warnings |
| New tests run against the original 0.1.0 code (temporary copy) | Failed as expected: invoice reference reuse (IntegrityError), rejected reversal link (`None`), pending invoice counted as outstanding |
| PostgreSQL migration checks on a throwaway PostgreSQL 15.14 cluster (localhost, fictional data; stopped and deleted afterwards) | **19/19 passed** |

**About the warnings:** all 91 are the same pre-existing pandas `FutureWarning` from `safe_csv` (`nova/ui/common.py`), which I left unchanged. A similar warning in the new code was removed.

**Changes to existing tests:**
- `tests/conftest.py` gained an automatic fixture. It points the demo database at a temporary file, ignores `.env` values and Streamlit secrets, and clears the cached engine.
- `tests/test_ui.py` now uses that temporary demo database. It previously pointed `DATABASE_URL` at a temporary file, which the stricter demo rule correctly refuses.
- No assertion was removed or weakened.

**What the new tests cover** (`tests/test_audit_fixes.py`):

- **Configuration**
  - default demo mode;
  - eight invalid configurations, each with no credentials in the message;
  - secrets override environment variables;
  - missing, valid and broken secrets files;
  - seeding refused on PostgreSQL;
  - the app refuses demo mode on PostgreSQL and offers no role switching.
- **Invoices**
  - a rejected invoice is kept, with its audit record;
  - its reference can be reused;
  - an active duplicate is refused by both the service and the database;
  - pending and rejected invoices are excluded from balances;
  - a rejected invoice cannot be settled.
- **Dates**
  - the PKT date changes at exactly 19:00:00 UTC (18:59:59 UTC is still 10 October);
  - sample data and period close use the PKT date;
  - no `date.today()` remains.
- **Money:** report and balance-sheet totals are exact integers after 40 small-amount vouchers, and the display conversion is correct.
- **Voucher grid:** blank values are normalized; five kinds of incomplete row are rejected with the row number.
- **Period close:** refused while a cancellation is pending; allowed once it is rejected; requests in the closed period are then refused.
- **Control accounts:**
  - wrong or missing party refused for 2000 and 2300;
  - 1200 refused in a manual journal;
  - 1200 refused as a purchase invoice account;
  - an untagged import line refused;
  - correct payments accepted;
  - an untagged entry from before the rule can still be reversed.
- **Reversals:**
  - a rejected attempt keeps its link;
  - a replacement is allowed and a third attempt refused;
  - the database refuses a second effective reversal;
  - the ledger nets correctly.
- **Permissions:** six actions by the wrong role are refused.
- **Display:** escaping covers links, images, bold, colour directives, math and HTML. In the running app, a customer named with image syntax is shown escaped.
- **Errors:** credentials are redacted from logs, and database exceptions don't contain the values involved.
- **Migration (SQLite):**
  - schema 2 → 3 with fictional records: row counts kept; statuses and reversal links backfilled; foreign keys and integrity intact; new indexes present; repeatable; a reused reference and a replacement reversal work afterwards;
  - a failing upgrade leaves the schema, rows and version unchanged, with no raw database message;
  - the app refuses a schema-2 demo database instead of migrating it;
  - `init_db` backs up, then upgrades, without reseeding;
  - `init_db` on an empty database.
- **Demo reset:** in a temporary copy of the app, `reset_demo.py` clears business records, keeps users and accounts, and the next startup does not reseed.
- **Packaging:** the ZIP contains exactly the allowlisted source files.

**PostgreSQL checks** (temporary script; not part of the pytest suite, because it needs a PostgreSQL server):
- schema 2 built from the original 0.1.0 models, then upgraded twice;
- rows kept; statuses and reversal link backfilled;
- old unique constraints dropped; partial indexes and `ck_invoices_status` added;
- the balance trigger still rejects unbalanced vouchers;
- a reused reference and a replacement reversal work;
- the database refuses a second active invoice and a second effective reversal;
- a failing upgrade changes nothing and shows only a fixed message;
- upgrade from version 1 to 3, and a new database created at version 3 with no sample records.

---

## Files changed

| File | Change |
|---|---|
| `app.py` | Configuration and migration errors shown safely; demo startup does not upgrade an existing database; sanitized logging |
| `nova/config.py` | Reliable secrets, demo restricted to `data/demo.db`, production validation, `ConfigError` |
| `nova/diagnostics.py` (new) | Credential-redacting failure logging |
| `nova/db.py` | `hide_parameters=True`; `initialize(upgrade_existing=...)` |
| `nova/models.py` | `Invoice.status`; partial unique indexes for active invoice references and effective reversals |
| `nova/migrations.py` | Schema 3 step (SQLite table rebuild in one transaction, PostgreSQL ALTERs), link restoration, `MigrationError` |
| `nova/auth.py` | Demo guard, production `[auth]` check, escaped user name |
| `nova/seed.py` | Refuses demo seeding outside SQLite; PKT date |
| `nova/services/common.py` | `business_today()` (Asia/Karachi) |
| `nova/services/accounting.py` | Control-account and party rules; invoice rejection status; reversal history kept; single posted reversal |
| `nova/services/sales.py` | Invoice control-account and duplicate checks; settlement requires an active invoice |
| `nova/services/master.py` | Period close checks pending ownership requests; PKT date |
| `nova/services/reports.py` | Integer-paisa reports, `to_rupees`, posted/active invoice balances, PKT dates |
| `nova/services/imports.py` | Trims blank amount cells |
| `nova/ui/common.py` | `md_escape`, escaped error messages, sanitized logging |
| `nova/ui/transactions.py` | `voucher_rows`, pending invoice table, settlement choices, escaping, paisa totals, PKT defaults |
| `nova/ui/reporting.py` | Paisa-based dashboard and report totals, escaping, PKT defaults |
| `nova/ui/admin.py` | Paisa-based reconciliation, escaping, PKT defaults |
| `nova/ui/masters.py` | PKT defaults |
| `scripts/init_db.py` | Backup-then-upgrade for SQLite, confirmation flag for PostgreSQL, safe error output |
| `scripts/package_release.py` (new) | Source-only release ZIP |
| `reset_demo.py` | Requires schema 3, with a clear message |
| `.streamlit/config.toml` | `client.showErrorDetails = "type"` |
| `.gitignore` | Database and archive patterns |
| `requirements.txt` | `tzdata==2026.5` |
| `docs/SETUP.md`, `docs/SCHEMA_POSTGRESQL.sql` | Upgrade steps and demo rule; regenerated schema 3 DDL |
| `tests/conftest.py`, `tests/test_ui.py` | Isolation from the real database and secrets |
| `tests/test_audit_fixes.py`, `tests/fixtures/schema_v2_sqlite.sql` (new) | Regression tests; exact 0.1.0 SQLite schema |
| `CHANGELOG.md`, `AUDIT_REPORT.md` | This documentation |

---

## Remaining limitations and open decisions

1. **Your decisions needed:**
   - access to sensitive customer fields (proposal above);
   - controls against duplicate administrator identities (above);
   - whether to restore the example configuration files. `.env.example` and `.streamlit/secrets.example.toml` were removed from the project folder during this session, and I did not recreate them. `docs/SETUP.md` still tells you to copy them.
2. **PostgreSQL:** the migration was tested on local PostgreSQL 15.14, not on Supabase or your production database. Take a `pg_dump` backup first.
3. **Sign-in:** the production `[auth]` check confirms only that the section exists. The Google OIDC flow itself is untested here, as before.
4. **Display escaping:** verified on the Markdown strings the app produces (including in the running app through Streamlit's test harness), not by viewing a real browser.
5. **Server logs:** with `showErrorDetails = "type"`, the browser shows only the type of an uncaught error. Streamlit's own console log of that error is not redacted, though SQL parameters are hidden.
6. **Old pending entries:** any created before the party-tagging rule must be rejected and re-entered (see the query above). Posted untagged entries stay as they are and can be reversed.
7. **Point-in-time status:** invoice and booking status in reports is current status, not status at the as-of date (unchanged pilot limitation).
8. **Sale invoices:** they still post to 1200 alongside booking receivables. That is a pilot policy question, not changed here.
9. **Python version:** the tests ran on Python 3.14.7, from the existing `.venv`. The documentation specifies 3.12, which I have not tested here.


## Extension release 0.2.0 — 2026-10-13

This supplied audited source was extended without reading or migrating the user's uploaded database. Schema-4 additive migrations, password login, stable sequences, safe record controls, branded/itemized documents, financial years, hierarchy and dashboards are documented in the new upgrade/coverage/test-results guides. New validation was performed with fictional temporary databases; original audit test assertions were retained or adapted explicitly for the changed requirements. This section does not claim the original PostgreSQL/OIDC checks were rerun here.
