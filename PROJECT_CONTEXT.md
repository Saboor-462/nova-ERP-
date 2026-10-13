# Current project checkpoint — Nova ERP 0.2.0

Latest base: user-uploaded audited nova_erp.zip, containing AUDIT_REPORT.md and schema-3 migrations. Changes preserve that code and add schema version 4. The original audit report is historical evidence; current validation is in docs/TEST_RESULTS_0_2_0.md.

User requirements: English UI; VS Code/Python/Streamlit; laptop SQLite testing first; later Supabase/Streamlit deployment. Preserve the established accounting/property workflows. Nova logo on professional invoices/vouchers; login before dashboard; attractive dashboard; edit/delete controls with audit preservation; pending/exception red alerts; grouped account totals and financial years; stable record IDs/codes, sequential document numbers, and separate SR rows. Start fresh with no sample financial data.

Authoritative next reads: README.md, docs/UPGRADE_0_2_0.md, docs/REFERENCE_COVERAGE.md, docs/TEST_RESULTS_0_2_0.md, CHANGELOG.md, then the actual current code.

Run locally: setup_windows.bat, setup_admin_windows.bat, run_windows.bat. Existing databases first require scripts.init_db with automatic SQLite pre-upgrade backup. Passwords are chosen locally. Separate creator/approver accounts are required. Mode demo is retained as the internal configuration label for the default local SQLite file; it no longer exposes role switching in the UI.

Never change historical UUIDs, account codes, or existing document numbers. New numbers are type-specific and never reused after cancellation. Draft edits may replace internal accounting lines/schedules, but document/master identities stay fixed. Posted financial entries use reversals/cancellations; no cascading destructive deletion.

All 64 supplied screenshots and the new voucher reference were inspected. The source-only runtime ZIP does not contain private originals or databases. Detailed scope boundaries are explicit in the coverage guide. Taxes, surcharge/token policies, booked-unit revenue recognition, external audits and production access/load still require business decisions and acceptance.

Use private Git for source history and separate database backups for transaction history. Every schema change requires a versioned tested migration and upgrade documentation. Do not rely on conversation memory as the sole development record.
