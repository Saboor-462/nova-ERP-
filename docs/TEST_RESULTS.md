# Historical verification record

This document records the original 0.1.0 build. See TEST_RESULTS_0_2_0.md for the current release.

# Verification record — version 0.1.0

Verified on 2026-10-09 in the build environment using Python **3.12.14**, Streamlit **1.65.0**, SQLAlchemy **2.0.54**, and temporary SQLite databases.

| Check | Result |
|---|---|
| Automated suite | 22 tests passed |
| Main navigation | All 14 page choices exercised by Streamlit AppTest |
| Report navigation | All 20 report choices exercised |
| Invoice screen variants | Purchase, Sale, and Dealer forms exercised |
| UI write action | Project creation through the form verified in database |
| Viewer restriction | Project creation controls hidden; service permissions tested separately |
| Double-entry and statements | Trial balance totals and balance sheet equality checked |
| Booking schedule precision | Exact paisa totals and month-end behavior checked |
| Receipt/invoice settlement | Partial/full receipt, reservation, rejection, overpayment, and reversal checks passed |
| Ownership events | Transfer and cancellation accounting passed |
| Concurrent writes | Same-unit booking and excessive simultaneous receipts tested locally |
| CSV imports | Balanced import, stable duplicate identity, and all-or-nothing rollback tested |
| Date/period controls | Future posting and closed-period posting blocked |
| Attachments and audit | Invalid file signature rejection and audit creation tested |
| Bank reconciliation | Clearance reflected in cash/bank report |
| Exports | XLSX/CSV value preservation, formula treatment, and PDF generation tested |
| Compilation | Python sources compiled successfully |
| PostgreSQL schema | SQLAlchemy PostgreSQL DDL compiled successfully; reference SQL included |
| HTTP startup | Streamlit started locally and health endpoint returned HTTP 200 / ok |
| Local backup | Consistent SQLite backup created; restored copy integrity_check returned ok |
| Reference preservation | 64 originals copied with filename/size/SHA-256 register |

## Not verified in this environment

Actual Supabase network connection, PostgreSQL concurrency/integration, Google OIDC sign-in, hosted Streamlit behavior, Windows batch execution, PostgreSQL backup restoration, target-user browsers, real business accounting policies, and production load.

AppTest checks widget execution and page behavior; it is not a pixel-level screenshot comparison. PDF generation was verified programmatically, not visually reviewed in a print shop. The supplied interface references remain available for the user's design acceptance.

See TESTING.md for the user-environment acceptance sequence. All seeded financial records are fictional and were not imported from the reference photos.
