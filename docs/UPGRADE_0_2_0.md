# Upgrade to Nova ERP 0.2.0

## What you receive

Source only, with your Nova logo and embedded print fonts. No actual database, passwords, secrets, virtual environment, uploaded documents, or sample business records are in the ZIP. The 64 screenshot references were inspected during development; the supplied originals remain in your previous project and are not repackaged into the runtime release.

## Fresh setup — empty business records

1. Extract into a new folder and open `nova_erp` in VS Code.
2. Run `setup_windows.bat` once (Python 3.12+ and internet required for dependency installation).
3. Run `setup_admin_windows.bat`. Enter your own administrator email, display name, and password/passphrase (12–128 characters). Nothing appears while typing a terminal password; this is normal.
4. Run `run_windows.bat`; open http://localhost:8501 and sign in.
5. The business database starts empty. Core accounts and account groups are provided; no financial transactions or fictitious properties/customers are created.
6. Under Administration, create an Approver account and set its password. The creator must sign out and the other authorized account must sign in to approve. Passwords are never hardcoded or emailed by this app.
7. Enter your business address/contact/footer in Administration → Invoice / voucher business header.
8. Add your actual financial year under Financial Years, then start with the fictional TEST-02 acceptance scenario before real accounts.

## Upgrade your existing working database

1. Stop the old app with Ctrl+C. Copy the entire old project to a separate backup folder.
2. Extract this release into a separate new folder. Keep the old code and database together for rollback.
3. Copy your original `data` folder into the new `nova_erp` folder, with Streamlit stopped. If WAL/SHM files exist, keep the database set together or use the old release's consistent backup tool.
4. Restore `.env` and `.streamlit/secrets.toml` only if you configured them. Local password mode is the default for local demo.db; remote databases require explicit production configuration.
5. Run `setup_windows.bat` to install the updated dependencies.
6. Run `.venv\Scripts\python.exe -m scripts.init_db`. It backs up an older SQLite database to `backups/before-upgrade-v4-*.db` before schema upgrade. The migration adds login/year/sequence tables and payment fields. Existing UUIDs, voucher numbers, account codes, and records are retained.
7. Run `setup_admin_windows.bat` to set a password for an existing active Admin email or create your personal Admin. Old Demo identities cannot sign in until passwords are explicitly assigned. No sample transactions are added.
8. Add/enable your other users and set passwords, then test the original balances and new controls.

Do not run reset_demo.py to perform an upgrade. Reset is deliberately destructive to business records, requires an explicit confirmation argument, and first creates a backup.

## Numbering and identities

New documents use JV-0001, PV-0001, RC-0001, PI-0001, SI-0001, DI-0001, BK-0001, and other type-specific sequences. A pending document consumes its number; rejection/cancellation does not make that number reusable. Editing and approval keep the document number and underlying UUID. Legacy random document numbers remain exactly as they were. Invoice reference is a separate user-entered supplier/customer reference. Table SR No. is a display row number, not a persistent identity.

## Edit / Delete semantics

- Projects, parties, units, leads, and non-core accounts: delete only when no dependent records exist; a deletion snapshot remains in the audit log.
- Used/core accounts: retain codes; edit descriptive fields or deactivate eligible posting accounts. Retired unused account codes cannot be reused.
- Pending manual vouchers, receipts, settlements, bookings, and invoices: edit through the relevant form, preserving their document identities.
- Delete a pending financial entry by cancellation, retaining its number and history. Pending booking cancellation releases its unit; pending receipt/settlement cancellation releases its reservation.
- Posted entries: original data remains immutable. Journals/receipts/settlements use approved offsetting reversals. Bookings use transfer/cancellation workflows. Unsettled invoices can request an approved cancellation reversal; settled invoices require settlement reversals first.
- Approved/rejected ownership events are history; only pending requests are editable/cancellable.
- Users: deactivate rather than deleting identities referenced by transactions/audits.
- Financial years: delete only unused, unaudited years. Audit status is an external review record, not a software-certified audit.

## Rollback

Stop the new app. Return to the complete old project and its matching pre-upgrade database backup. Never point the old code at a schema-4 database; its models do not understand the new schema. If you entered new records after upgrade, reverting the database loses those later records, so export/reconcile them before deciding to roll back.

## Login behaviour

Passwords are Argon2id hashes. Server-side opaque sessions expire after eight hours and are rechecked on every rerun. Logout and password reset revoke the appropriate sessions. Five failed attempts for an email lock sign-in for fifteen minutes. A browser reload creates a new Streamlit session and requires sign-in again. CLI administrator setup is trusted local maintenance access; anyone with control of the code/database can bypass application-level controls, so protect the laptop and backups.

Online PostgreSQL/OIDC settings remain available. Public deployment, identity-provider login, HTTPS hosting, backups, and production load require separate acceptance testing. Different account IDs do not establish different human identities; manage administrator membership accordingly.
