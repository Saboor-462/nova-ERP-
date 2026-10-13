# Testing guide

## Automated checks

Run `test_windows.bat`, or:

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m scripts.check_integrity
```

Tests create temporary SQLite databases and fictional fixtures. They do not require Supabase credentials or alter the live database. AppTest exercises Streamlit pages without a browser. PostgreSQL/OIDC integration and multiuser production load are not covered by those local tests.

## Guided local acceptance

1. **Dashboard:** open the seeded project, verify cash/bank, pending vouchers, booked/available units, and overdue installments.
2. **Party and project:** create a new sample project and customer; edit contact details and confirm audit history.
3. **Unit:** add a unit, change its available price, then book it. It must disappear from the available booking list.
4. **Booking:** enter a price such as 1,000.01, a down payment of 100, and three monthly installments. Schedule amounts must total exactly 1,000.01. A scheduled down payment does not count as money received.
5. **Approval:** switch to Approver and approve the booking voucher. In production, attempt creator self-approval and confirm rejection.
6. **Receipt:** submit 200 against the booking. Pending receipt should reserve the balance but should not yet change the approved ledger. Approve it and inspect allocation, cash ledger, receivable ledger, and installments.
7. **Overpayment:** try collecting more than the remaining price or submit a second full receipt while one is pending. It must fail without partial changes.
8. **Rejection:** reject a pending receipt with a reason; it must release reserved capacity. Reject a pending booking; the unit must become available again.
9. **Invoice:** create a purchase invoice; approve it; pay part of it; approve the settlement; check payable and invoice outstanding.
10. **Reversal:** reverse an eligible receipt, approve the reversal, and verify that the schedule payment and cash balance return correctly. Duplicate reversal must be blocked.
11. **Transfer:** request a different customer, approve as another user, check ownership and both customers' account movements. Receipts are blocked while the request is pending.
12. **Cancellation:** cancel an active booking. Verify unit availability, removal of the unpaid receivable, and refund payable for approved money received. Record refund payment separately.
13. **Reports:** compare ledger closing balances with trial balance; verify balance sheet assets equal liabilities plus equity. Verify that pending vouchers are excluded. Confirm date-range opening balances.
14. **Reconciliation:** clear cash/bank rows using statement references; check adjusted statement and book difference. Enter charges/interest as vouchers first.
15. **Imports:** modify the sample CSV to your sample project/date, import a balanced voucher, reimport it, and check that there is no duplicate. A batch with one invalid voucher must save none of its new vouchers.
16. **Exports:** search/filter/choose columns; open CSV, Excel, and PDF. Compare selected values and print layout. PDFs are generated only for up to 2,000 rows.
17. **Roles:** Viewer cannot create entries; Accountant cannot approve; Sales can add customers/leads; disabled users cannot mutate records.
18. **Closure:** resolve pending vouchers, take a backup, then close a sample period. Attempt a backdated entry; it must fail. Use a separate demo database for this forward-only test.
19. **Restart:** stop/restart the app and verify saved local records persist.
20. **Restore:** rehearse backup restoration into a separate database and rerun integrity/acceptance checks.

## Before daily office use

- Run the same checks with your PostgreSQL test database and two separately logged-in users.
- Test connection interruptions, simultaneous receipts/approvals, refresh/retry behavior, and peak expected users with representative data volumes.
- Verify backups and restore time, restrict database credentials, and configure the identity provider.
- Have your accountant review the decision register and financial reports, especially booking obligations, revenue recognition, taxes, and cancellation policies.
- Add regression tests for any issue found and package a new version after fixes. No untested production capacity promise is part of this release.
