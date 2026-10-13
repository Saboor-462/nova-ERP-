# Verification — Nova ERP 0.2.0

Build environment: Python 3.12.14, Streamlit 1.65.0, SQLAlchemy 2.0.54, Argon2-cffi 25.1.0; all business databases were temporary fictional SQLite fixtures. No uploaded actual database, secrets, backup, attachment content, or virtual environment was read or migrated.

**Complete suite: 92 passed in 19.42 seconds.** Command: `python -m pytest -o addopts='' -q -p no:cacheprovider`.

The uploaded audited source contained 77 tests. Its initial baseline here had 76 passing and one failure caused by a legacy server-date assumption at the Pakistan-midnight boundary. Workflow tests now use the already-audited Pakistan date helper. Legacy UI fixtures now explicitly seed and authenticate fictional users because normal startup no longer seeds business data or permits role switching. Migration-preservation checks still assert every original table/record count, while allowing new empty additive tables. Pending alerts are deliberately red and are asserted separately from unexpected runtime errors.

| Check | Result |
|---|---|
| Existing audit/accounting checks | Passed, including balanced entries, exact money, pending reservations, reversals, closing, control-account rules, imports, and history |
| Fresh startup | Password form required; no project or financial voucher seeded |
| Login | Argon2id hashes, correct/wrong password, disabled users, persistent email lockout, logout and reset revocation |
| Navigation | Fifteen main pages exercised; twenty-five report choices exercised |
| Dashboard | Project, balance-sheet and consolidated views exercised |
| Voucher grid | Explicit Add Row produces a third row; incomplete/zero grid cannot submit |
| Numbering | Pending and rejected numbers remain consumed; edit retains identities; concurrent allocation is unique/sequential |
| Account codes | Optional AC sequence, no reuse of retired codes, hierarchy cycle prevention, stable IDs |
| Record controls | Unused delete, linked-unit deletion blocked, pending edits/cancellations, posted invoice reversal |
| Booking/payment edits | Document IDs/numbers retained; schedules/allocation totals verified |
| Itemized invoices | Item amounts validated against gross total |
| Account hierarchy | Root totals reconcile with financial statements without double-counting subtotal rows |
| Financial years | Non-overlap, complete external-audit metadata, audited-period posting guard |
| Upgrades | SQLite versions 1/2/3 to current schema covered by preservation/atomicity/backup checks |
| Reset | Local business reset takes backup, preserves users/accounts/credentials/sequences, prevents sample reseeding |
| PDF output | Voucher and invoice PDFs rendered and visually inspected; embedded fonts, Nova logo, clean A4 layout |
| Packaging | Allowlist excludes actual databases, secrets, reference photos and virtual environments; only trusted branding/font assets included |
| PostgreSQL | Current schema compiled to reference DDL; no new PostgreSQL/Supabase runtime integration was performed here |

## User-environment checks still required

Windows batch execution, the user's Python 3.14 environment, real browser visual behaviour, the actual database upgrade/restore, PostgreSQL/Supabase and OIDC sign-in, production concurrency/load, and accountant approval of business policies are not certified by these tests.

The original Claude audit's PostgreSQL 15 checks belong to that prior release and were not repeated for the new features. All statements above refer only to the current build's verified evidence. Tests reduce defects; they do not prove unrestricted production readiness or statutory accounting compliance.
