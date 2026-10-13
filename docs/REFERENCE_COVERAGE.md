# Reference and requested-feature coverage — 0.2.0

All 64 supplied original screenshots and the additional voucher reference were inspected. Many are repeated, partial, or show menus without their full forms. No financial data from the photos was imported. The Nova logo is preserved as supplied.

| Reference / request | Implementation |
|---|---|
| Dark sidebar, blue controls, professional dashboard | Existing navigation retained, Nova gold/navy theme, branded headings/cards |
| Project dashboard | Inventory, approved bookings, booked sales, collections, cash, receivables/payables, revenue/expenses |
| Balance sheet dashboard | Asset/liability/equity totals, hierarchical account balances, red differences |
| Consolidated dashboard | All-project financial summary and consolidated balance sheet hierarchy |
| Voucher form header | Nova logo, business name, General Payments heading, date, project, payment mode/type |
| Voucher rows | Account search, party, description, debit, credit, explicit Add Row and grid add/remove controls |
| Voucher totals/upload | Live totals, unbalanced red alert, receipt upload, balanced posting validation |
| New/list/pending vouchers | Separate sections, count, pending red status, permanent numbers and UUIDs |
| Printable vouchers/invoices/bookings | A4 Nova-branded PDFs with header/contact/footer, status, amounts and signature lines |
| Edit/delete | Dependency-aware unused-master deletion; pending financial edits/cancellation; posted reversal/correction workflows |
| Accounts | Stable codes, parents/groups, current/non-current asset/liability groups, furniture/equipment, name edits and safe deactivation |
| Financial years | Date ranges, non-overlap validation, Not audited/In review/Audited status, reviewer/date/reference |
| Trial balance | Opening, activity, closing, details/hierarchy/grouped view; integer-paisa computations |
| Balance sheet | Detailed, hierarchical/grouped, consolidated, totals, reconciliation alerts |
| Profit/loss | Detailed and parent-hierarchy grouped period amounts |
| General/party/customer/dealer/landowner ledgers | Posted transactions, account/party/project/date filters and running balance |
| Cash/expenses reports | Posted inflows/outflows, expense movements and bankbook/reconciliation |
| Dealer commissions | Accrued, paid, outstanding per dealer control ledger |
| Sales summary/detailed | Active approved bookings; collections/outstanding; unit category/floor/feature filters |
| Installment detailed/client-wise/defaulters | Dates/paid/outstanding/overdue, separate down-payment/installment summary and red overdue rows |
| Inventory | Project/type/category/floor/feature/status filters and current unit status |
| Projects/clients/units | Create/list/detail edits/delete checks; stable IDs; available price updates |
| Allotments/transfers/cancellations | Existing accounting flows retained with pending edit/cancel controls |
| Purchase/sale/dealer invoices | Existing types retained; history, sequential voucher-based invoice numbers, print, pending edit/cancel, settlements |
| CRM/bulk import/users | Lead edit/delete, atomic CSV import, email/password users/roles, active/deactivate, audit history |
| Table tools | Search, native sorting, pagination, visible columns, CSV/Excel/PDF and print through PDF |

## Specific boundaries still requiring business policy

- Streamlit controls follow the reference fields and layout style; they are not a pixel-identical copy of the other ERP.
- The photos show surcharge columns but do not establish a surcharge formula, grace period, waiver, or accounting treatment. No fee is automatically invented. Similarly, tax/withholding rates, depreciation schedules, token reservation/deposit accounting, revenue recognition for booked units, and cancellation deductions require accountant-approved policies.
- The application does not certify statutory statements or an external audit. Booking value, collections, and recognized revenue remain distinct.
- Inventory/ownership reports show current operational records. Historic ownership/inventory snapshots and per-branch/project access remain outside this release.
- General ledgers show posted entries; pending entries are kept in separate queues to avoid confusing draft activity with financial balances.
- A pending edit may replace internal line/allocation/schedule rows when its structure changes. The master/document UUIDs, account codes, and business numbers remain stable; SR No. is separate.

These are explicit policy/technical limits, not hidden balances or fabricated defaults. Further decisions should be recorded before automating the corresponding accounting entries.
