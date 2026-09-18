# CBIC notifications, fetched 18-09-2026

From `taxinformation.cbic.gov.in` → GST → Notification → Central Tax Notification.
That portal also carries an **amendment history** per notification (a "View" link in the
History column), which is what settled the §50(3) question: it is the only way to
establish, from the publisher, that a notification has NOT been amended.

| Notification | Date | What it settled |
|---|---|---|
| **13/2017-Central Tax** | 28-06-2017 | the interest rates under section 50 — **§50(1) at 18% and §50(3) at 24%** — made under "sub-sections (1) and (3) of section 50". Its amendment history lists 31/2020, 51/2020, 08/2021 and 18/2021, all COVID-period concessions, and **nothing after July 2022** |
| **09/2022-Central Tax** | 05-07-2022 | appoints 05-07-2022 for "clause (c) of section 110 and **section 111**" of the Finance Act 2022. It does NOT reach s.116, carries no Schedule and states no percentage |
| **04/2018-Central Tax** | 23-01-2018 | §47 late fee for **GSTR-1**: waived above ₹25/day central tax, ₹10/day for a nil return |
| **76/2018-Central Tax** | 31-12-2018 | the same for **GSTR-3B**: ₹25/day, ₹10/day nil |
| **19/2021-Central Tax** | 01-06-2021 | amends 76/2018 — turnover-banded caps for GSTR-3B from the June 2021 tax period: nil ₹250, up to ₹1.5cr ₹1,000, ₹1.5–5cr ₹2,500 (central tax) |
| **20/2021-Central Tax** | 01-06-2021 | amends 4/2018 — the identical table for GSTR-1 |
| **07/2023-Central Tax** | 31-03-2023 | §47(2) **annual return** fee from FY 2022-23: up to ₹5cr ₹25/day capped at 0.02% of State turnover; ₹5–20cr ₹50/day capped at 0.02%; plus a one-off ₹10,000 cap for FY 2017-18 to 2021-22 furnished 1 Apr – 30 Jun 2023 |

**Every figure above is CENTRAL tax.** The State notification mirrors it, so what a CA
actually pays is double — ₹50 a day, ₹20 nil, caps of ₹500 / ₹2,000 / ₹5,000, and
₹10,000 above ₹5 crore where the table does not reach and §47's own ceiling applies.
`domain/gst/late_filing.py` holds the doubled figures because that is what the taxpayer
owes; the notifications here are the working.

## The Finance Act 2022

Not committed — it is a 147-page Gazette PDF. What matters from it is **section 111**, at
page 65, quoted in full in `domain/gst/late_filing.py`: it substitutes §50(3) with effect
from 01-07-2017 and **delegates** the rate, "at such rate not exceeding twenty-four per
cent. as may be notified". No percentage appears in the Act.
