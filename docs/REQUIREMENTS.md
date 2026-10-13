# Requirements, reference coverage, and decision register

## Agreed scope and coverage

| Reference area | This release | Coverage / limitation |
|---|---|---|
| Project and consolidated dashboards | Cash, receivables, payables, overdue installments, units, cash activity, financial overview | Working; filters use approved entries |
| Project/owner details | Project number/name/owner/area/description/terms | Create, list, detail edits |
| Clients | Customer/vendor/contractor/dealer/landowner, relation, contact, city/province, identity | Create, list, detail edits; no duplicate-person matching |
| Chart of accounts | Parent/type/group/posting/cash accounts | Create/list; stable core codes; no arbitrary reclassification of posted accounts |
| Unit inventory | Project/type/number/floor/feature/area/price/reference/status | Create/list/detail edits/available-unit price changes |
| Unit allotments | Customer, date, number, agreed price, down-payment schedule, monthly installments | Booking and printable form; amendments of posted prices not included |
| Vouchers | Project/date/type/account/party/description/debit/credit/receipt upload | Balanced entry, list/detail, approval/rejection, eligible reversal |
| Pending vouchers | Pending/posted/rejected filtering | Working; self-approval disabled in production |
| Collections | Receipts, allocation, outstanding, overdue days | Working; no automatic surcharge policy |
| Purchase/sale/dealer invoices | Party, project, reference, amount, dates, account, supporting document | Working; partial/full settlement; tax detail/credit notes not included |
| Transfers | Request/list/approval and receivable/obligation reclassification | Working under pilot policy |
| Cancellations | Request/pending/history/approval and refund payable | Working under pilot policy; refund payment uses separate voucher |
| Trial balance and detail | Opening/activity/closing debit and credit | Both choices currently use the same detailed account table |
| Balance sheet and grouped view | Cumulative balances and computed accumulated earnings | Working; group view groups by account type |
| Profit & loss and grouped view | Period income/expense accounts | Working; bookings do not automatically recognize income |
| General/customer/party/dealer/landowner ledgers | Account/client/project/date filters and running balances | Working; voucher drill-down is through Vouchers → Open voucher |
| Sales summary/detailed | Active bookings, amounts/paid/outstanding and property attributes | Working; current ownership, excludes cancelled bookings |
| Installment summary/client-wise/defaulters | Due dates, paid/outstanding, overdue days | Working; current active schedules with as-of receipt totals |
| Cash in/out and expenses | Posted cash activity and expense movements | Working |
| Bank reconciliation | Cleared entries, statement balance, uncleared items, difference | Working; no bank-feed import or automatic matching |
| CRM/leads | Contact, project, stage, notes, next follow-up | Basic working CRM |
| Bulk vouchers | Template, preview, validation, atomic import | Working; 1,000-row limit; no bulk booking import |
| Users | Authorized email, display name, role, active status | Google OIDC example; no username/password or branch mapping |
| Report toolbar | Search, native sorting, CSV/Excel/PDF, print via PDF, visible columns | Working; no copy-to-clipboard command |
| Unit tokens, surcharge rules, construction material costing | Not included | Next scope after acceptance/policy definition |

## Pilot decisions

1. **Currency and precision:** one currency, PKR. Money is stored in paisa integers; user input has at most two decimal places. Price/receipt/invoice inputs allow up to 1 trillion PKR per entered amount.
2. **Booking accounting:** an approved booking debits customer receivables (1200) and credits customer booking obligations (2100). It represents the full installment obligation. This convention is a pilot policy requiring accountant review; it is not an asserted statutory revenue-recognition policy.
3. **Revenue:** booking income is not automatically recognized. Standalone sale invoices recognize income. A completed booking requires a reviewed recognition workflow before business use; do not create a second sale invoice for the same booked property as a shortcut.
4. **Down payment:** scheduled due amount only. Actual receipt is recorded separately after booking approval.
5. **Installments:** monthly dates retain the day where possible and clamp to month end. Remaining paisa are spread across early installments; schedule sum exactly equals the agreed price.
6. **Receipt allocation:** oldest due unpaid installment first, including down payment. Approved receipts count as paid; pending receipts reserve capacity but do not appear in approved financial reports.
7. **Approvals:** Admin and Approver can approve. Admin and Accountant enter accounting transactions. Sales handles customers/leads. Viewer reads reports. Production requires different creator and approver identities.
8. **Corrections:** posted vouchers are immutable in the UI. Eligible journals/receipts/payments can request an offsetting reversal, which requires approval. Linked booking/invoice/ownership vouchers cannot be reversed using the generic action. Invoice credit notes and broader amendments are future scope.
9. **Transfer:** the outstanding receivable and full booking obligation move from old customer to new customer; previous receipt history stays on original vouchers. No fee is automatically charged.
10. **Cancellation:** the full booking obligation is removed; unpaid receivable is cancelled; approved receipts become customer refunds payable (2200). The unit becomes available. Refund cash payment is separate. No deductions or automatic dealer commission reversal are applied.
11. **Dealer commission:** booking commission creates expense/payable at booking. Dealer invoices are separate; avoid booking the same commission twice. Payments for invoice commissions use invoice settlement; booking commission payout can use a party-tagged payment voucher to account 2300.
12. **Purchases:** one gross amount and one expense/asset account per invoice. Withholding, sales tax, tax invoices, retentions, and itemized cost allocation require additional configured rules.
13. **Project expenses:** the user chooses expense versus development asset; the app does not infer capitalization.
14. **Dates and periods:** transaction dates cannot be in the future; installment/lead due dates can. Period closure is forward-only and blocks entries and approvals dated on or before the closed date. Reopening requires a reviewed future workflow.
15. **Imports:** manual voucher imports cannot post booking control accounts 1200/2100. A repeated project/VoucherRef returns the existing voucher; changing the CSV does not amend posted or pending imported entries.
16. **Storage:** demo SQLite is local sample storage; production requires PostgreSQL and external backups. Attachments are up to 5 MB and stored in the database in this pilot; a growing deployment should migrate them to managed object storage with access control.
17. **Scope:** one company, project-wide role access. No per-project/branch authorization, multi-company books, automatic reconciliation feed, statutory report certification, or production load guarantee.
18. **Reports:** booking/installment/inventory/party names use current operational records. Financial ledger dates and opening balances are historical. Reports do not reconstruct historic ownership or cancelled booking state at an earlier date.

## Accounting entry examples

| Transaction | Debit | Credit |
|---|---|---|
| Booking PKR 5,000,000 | Customer receivable 5,000,000 | Booking obligation 5,000,000 |
| Customer receipt PKR 1,000,000 | Cash/bank 1,000,000 | Customer receivable 1,000,000 |
| Supplier invoice PKR 250,000 | Expense/development asset 250,000 | Supplier payable 250,000 |
| Supplier payment PKR 100,000 | Supplier payable 100,000 | Cash/bank 100,000 |
| Cancellation after PKR 1,000,000 paid | Booking obligation 5,000,000 | Receivable 4,000,000 and refund payable 1,000,000 |
| Refund paid separately | Refund payable 1,000,000, tagged customer | Cash/bank 1,000,000 |

## Before expanding the release

Acceptance testing should settle booking revenue recognition and cost capitalization, cancellation deductions, commission timing/clawback, surcharge formula, tax/withholding, branch/project permissions, required document layout, and opening-data migration. Record those decisions here before implementing them. Existing photos remain the visual reference; current source code and these decisions define behavior.
