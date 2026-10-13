# Nova ERP 0.2.0

Nova-branded real estate ERP with email/password login, an empty business starting database, sequential document numbers, safe record controls, financial years, hierarchical accounts, financial dashboards, and printable A4 invoices/vouchers.

## Windows — new setup

1. Extract and open the `nova_erp` folder in VS Code.
2. Run `setup_windows.bat` (Python 3.12+; tested on 3.12).
3. Run `setup_admin_windows.bat` and set your own email/password.
4. Run `run_windows.bat`; open http://localhost:8501 and sign in.
5. Add an Approver user/password under Administration. Posted approval requires another account; local role switching and default passwords are removed.

## Existing installation

Stop the old app and keep a complete backup. Follow **docs/UPGRADE_0_2_0.md** before copying your database or replacing code. Run `python -m scripts.init_db` for the backed-up schema-4 upgrade, then set your administrator password. No original records, IDs, codes, or numbers are reset by the upgrade.

## What is included

- Existing audited accounting and property workflows.
- Nova logo, navy/gold dashboard styling, configurable print business details.
- Email/password login, roles, logout, password reset, throttling, expiring server sessions.
- New/list/pending voucher sections, live debit/credit totals, payment fields, receipt upload and dynamic rows.
- Stable UUIDs/codes and sequential type-specific business document numbers.
- Pending voucher/receipt/settlement/booking/invoice edits and cancellations; safe unused-record deletion and posted reversals.
- Hierarchical accounts including current/non-current assets/liabilities and furniture/equipment.
- Financial years and externally recorded audit status; period closure.
- Project, balance-sheet and consolidated dashboards; twenty-five report choices and red exception/status alerts.
- Branded invoice, voucher and booking PDFs; CSV/Excel/PDF report exports.

No actual records, database, passwords, secrets, virtual environment, or private reference photos are included in the release ZIP. Fresh startup creates core accounts only; fictional records are generated exclusively by isolated tests.

## Testing and limits

Run `test_windows.bat`. Read **docs/TEST_RESULTS_0_2_0.md**, **docs/REFERENCE_COVERAGE.md**, and the upgrade guide for what was verified and what remains. Accountant review is required for booking revenue recognition, taxes, surcharge/commission/cancellation policies, and financial statement treatment before daily business use. Public deployment is a separate setup/test step.

## File map

`app.py` starts the app. `nova/auth.py` and `nova/services/security.py` handle login. `nova/documents.py` renders branded print documents. `nova/services/records.py` implements safe edit/delete/year controls. `nova/services/numbering.py` allocates document numbers. `nova/services/overview.py` computes hierarchy/dashboard/diagnostics. Existing service modules retain accounting and sales logic. See docs/FILE_MAP.md for the full original map.

Read PROJECT_CONTEXT.md, CHANGELOG.md, the audit report and upgrade/coverage guides before future modifications. Use a private Git repository for source history and separate database backups for records.
