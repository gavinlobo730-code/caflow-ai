# The verification pass — 163 findings re-checked against the code

**11 September 2026, against `bd3cd323`.** Nine read-only agents, one per
subsystem, each given the finding's own `evidence` field and told to go and look
at what is there NOW. No edits, no test runs, `path:line` required for every
verdict.

This **supersedes `2026-09-08b-what-is-left.md` as the remaining-work list.**
That document is kept because its §2 is the record of what the previous tranche
introduced.

---

## 1. The headline, including the prediction that was wrong

| verdict | count | share |
|---|---:|---:|
| `open` — still live | 131 | 80% |
| `partial` — half closed | 15 | 9% |
| `done` — closed | 17 | 10% |
| **total** | **163** | |

**The prediction behind this pass was wrong, and by a lot.** On 11 September I
told the owner that the 11-September spot-check — sixteen of twenty-two claims
stale — implied roughly 73% of the backlog was already closed, and that a
verification fan-out "could retire something like 100 of them". It retired
**17**. The spot-check was not a sample: it was a list of findings I had *chosen*
to look at, and I had chosen the ones that smelled stale. Generalising from it
was a sampling error, and I should have said so before quoting a rate.

**The pass was still worth its cost, for a reason I had not predicted.** It found
**seven findings whose severity had gone UP** since the rescore, all by the same
mechanism, and **two live defects with no finding at all**. Those are in §2 and
§3 and they are the work to do first.

Per-slice:

| slice | n | open | partial | done |
|---|---:|---:|---:|---:|
| accounting-core | 19 | 11 | 3 | 5 |
| banking | 20 | 17 | 1 | 2 |
| fixed-assets & inventory | 18 | 14 | 3 | 1 |
| GST | 18 | 11 | 4 | 3 |
| income tax & ITR | 15 | 13 | 2 | 0 |
| payroll | 18 | 15 | 1 | 2 |
| purchase cycle | 18 | 16 | 0 | 2 |
| sales cycle | 19 | 17 | 1 | 1 |
| TDS/TCS | 18 | 17 | 0 | 1 |

---

## 2. The escalations — the same mechanism, seven times

Every one of these was scored **medium or low** because it was **unreachable**:
the engine was wrong, but no screen could reach it, so nothing wrong ever
displayed. **Phase 7 built the screens.** The defects did not change; the
mitigation that held their severity down disappeared, and nobody re-scored them
because a rescore reads the finding, not the diff that invalidated it.

**This is a class, not seven coincidences.** "Latent because no UI reaches it" is
a severity that expires the moment a UI reaches it, and nothing in the process
was watching for that.

| id | was held down by | what closing that made true |
|---|---|---|
| **PAY-08** | "employee loans have no UI" | `LoansSection` creates loans. `reverse_run` (`routers/payroll.py:2759`) reverses both journals and resets the run to `review` but **never touches `payroll_loans`**, while `_apply_loan_recoveries` (`:2650`) writes the balance down at every finalisation. Reverse-and-re-finalise writes one recovery down **twice**. |
| **PAY-07** | "perquisites are reachable from no UI" | `PerquisitesSection` values and records §17(2) benefits. They still never reach monthly §192 withholding — and the confirmation message reads as reassurance. |
| **IT-08** | "no screen sends capital gains" | `714c1c84` wired capital gains into the client computation screen. The missing §111A(1)/§112(1) basic-exemption absorption is now **a wrong number on screen**: ₹5,00,000 STCG and no other income shows **₹1,04,000** against a correct **~₹20,800**. |
| **GST-19** | "nothing writes `gstr2a_records`" | The 2B reconciliation writes them (`gst_2b_reconciliation_service.py:450`) and `gst_return_service.py:842` feeds them to `compute_gstr3b`. The aggregate Rule 36(4) cap now fires **on the return the CA files**, and trims legitimate self-assessed **RCM** credit, which the cap has no business reaching. |
| **PUR-04** | "PUR-05 keeps `itc_eligible` unsettable" | PUR-05 is closed — `PurchaseBillEditor.tsx:812` sets `itc_eligible:false` with a reason. So a CA can now book a blocked-credit bill, and `phase2_journal_service.py:670` still debits Input GST with the **full** tax: a phantom asset and a permanent books-vs-GL difference. |
| **TDS-18** | "the compute→save path is unreachable" | TDS-03 closed in `1dc3d961`. And the screen's **default** is already the broken year: `tds/returns/page.tsx:54` seeds from `currentFinancialYear()` = `2026-27` while the `<select>` at `:254` stops at 2025-26 — so the control renders blank, the API returns form `140`, and the save hits the `return_type IN ('24Q','26Q','27Q','27EQ')` CHECK. |
| **ACC-18** | "the FY list is only presentational" | Migration 361 made the firm lock reach the **posting kernel**. A lock on a year outside the four hardcoded ones is now enforced on every posting and is **invisible and un-unlockable** on the only screen that manages firm locks. FY **2026-27 is absent today**. |

**The process fix, not just the seven fixes:** a finding whose severity rests on
"nothing reaches this" needs that premise stated as a *testable* claim, not as
prose in a rescore. A reachability ratchet already exists
(`tests/test_every_mounted_endpoint_has_a_way_in.py`) and answers the opposite
question. The missing guard is the one that fails when a **named** unreachable
path becomes reachable.

---

## 3. Two live defects with no finding at all

Both found in the agents' `notes` fields — the "flag anything the finding does
not mention" instruction earned its place.

### 3a. A revenue ledger cannot be created. `Income` is not `Revenue`.

Three spellings of one thing, in three layers, and they do not agree:

| layer | spelling | `path:line` |
|---|---|---|
| API request model | `Income` | `apps/api/models/accounting.py:46` — `AccountType.INCOME = "Income"`, and there is **no** `REVENUE` member |
| the screen's `<select>` | `Income` | `apps/web/app/accounting/account-groups/page.tsx:30` |
| **the database CHECK** | **`Revenue`** | `apps/api/migrations/003_phase3a_foundation.sql:108` |
| the Schedule III classifier | **`revenue`** | `apps/api/domain/reporting/schedule_iii.py:255,260` |
| the seeded chart | **`Revenue`** | `apps/api/services/coa_seed_service.py:85-93` |

`routers/accounting.py:137` writes `data.account_type.value` verbatim. So a CA
who opens **Account Groups → add a ledger** and picks the only revenue-shaped
option gets a **CHECK constraint violation** — a 422 they read as "could not
create the account". **There is no way to create a revenue ledger from that
screen at all.**

**Measured, not inferred.** Production holds `Asset` 42, `Expense` 40,
`Liability` 24, `Revenue` 19, `Equity` 8 — and **zero** `Income`, which is what
the CHECK refusing every one of them looks like from the outside.

Why no test caught it: **mock mode has no CHECK constraint.** The mock path
(`routers/accounting.py:124`) takes `accounting_service.create_account` and
accepts `Income` happily; the ~10,400-test mock suite therefore exercises the
broken value and passes. `coa_seed_service.py:35` even carries a comment
acknowledging both spellings exist.

### 3b. All seven year-end schedule tabs 404

The route is `/api/year-end/{engagement_id}/schedules/{schedule_type}`
(`routers/year_end_statements.py:34,240` mounted at `main.py:397`). The only
caller fetches
`/api/year-end/engagements/{engagementId}/schedules/{type}`
(`apps/web/app/clients/[id]/year-end/[engagementId]/schedules/_page.tsx:49`) —
**five path segments against a four-segment pattern.** No match, 404, on all
seven tabs.

This interacts with **FA-09** and the two must be fixed together: the endpoint
behind the 404 windows the GL (`.gte`/`.lte` on `entry_date`, then
`balance = debit - credit`) with **no opening balance**, so fixing the URL alone
would replace a 404 with a wrong schedule. `routers/year_end_notes.py:180-280`
already computes a proper FY movement and is the model this endpoint lacks.

---

## 4. What `done` actually looked like

Of the 17 closed, **11 were closed by a mechanism the finding never imagined** —
which is the same staleness shape the last pass found, and the reason a rescore
that reads finding text cannot settle anything:

- **ACC-21** — closed by a statement-level **trigger** (migration 360), and the
  suggested per-RPC `EXISTS` check was explicitly rejected: the gate is on the
  TABLE so it covers the ORM and every future RPC.
- **ACC-17** — the scope lives on the ledger **source**, built per request, so a
  fetch added later inherits it. The finding's premise ("no frontend caller
  omits `client_id`") was false — the Schedule III screen offers "All Clients".
- **GST-27** — closed by **deletion**, not by moving the function.
- **BANK-18** — closed by a machine-readable refusal `code`, richer than the
  suggested `errorMessage(res)`.
- **ACC-04** — the 8 September rescore probed migration **266**, a *superseded*
  body. Migration **338** is the last definition of `edit_posted_journal`.
- **PAY-17** — the rescore measured `46bd46c`; the fix landed in the later
  `9fbe40d4`. Verified here by **measurement**, not by reading.
- **GST-31** — the finding's own suggested fix was "leave it", and it has been
  left. Correctly `done`, not `open`.

---

## 5. Corrections this pass makes to earlier documents

| claim | where | the correction |
|---|---|---|
| "~73% of the backlog is stale" | my own message, 11 Sep | **~10%.** The spot-check was not a sample. |
| "PAY-22 may have closed IT-20" | — | It did not. `bd3cd323` capped §80CCD(2) on **salary** rather than gross; the **10%-vs-14%** rate under the new regime is untouched, and the two are easy to confuse because they are the same computation. |
| "IT-08 is latent — no screen sends capital gains" | 2026-09-08 rescore | Stale since `714c1c84`. |
| "GST-19 is dormant — nothing writes `gstr2a_records`" | 2026-09-08 rescore | Stale. The 2B reconciliation writes them. |
| "TDS-18 is latent" | 2026-09-08 rescore | Stale since `1dc3d961`, and the screen's **default** state is the broken one. |
| "PUR-04 is latent behind PUR-05" | 2026-09-08 rescore | PUR-05 is closed; PUR-04 is reachable. |
| "FA-02 is the one remaining critical" | 2026-09-08b | Still true as scored, but **PAY-08 and IT-08 both now outrank it** on what a user experiences today. |

---

## 6. The order to build in

Ranked by **what a person experiences**, not by the finding's stored severity.

**Phase 13a — a wrong number or a wrong money movement, today.**
`PAY-08` (loan written down twice) · `IT-08` (₹1,04,000 shown for a ~₹20,800
liability) · `PAY-07` (§17(2) never withheld, with a reassuring message) ·
`IT-26` (HRA and §24(b) added to the Chapter VI-A accumulator — GTI understated
*and* Schedule VI-A overstated) · `IT-32` (`other_deductions_paise` has no
ceiling, so anything routed through it escapes the §80CCE ₹1.5 lakh cap) ·
`IT-20` (§80CCD(2) at 10% where the new regime allows 14%).

**Phase 13b — the credit side: GST and purchases.**
`GST-19` (the Rule 36(4) cap reaching RCM) · `PUR-04` (phantom Input GST asset).

> **Found while fixing 13b, not fixed there.** The whole Rule 36(4) working —
> book figure, 2A figure, whether the cap applied, and now the self-assessed
> figure that sits outside it — is computed, returned by both
> `routers/gst.py` and `gst_return_service`, and **rendered by no screen**.
> `lib/data/gst.ts:492` reads one of the ten fields. So a CA cannot see why
> their claim was trimmed, or that it was. That is a screen build of the same
> shape as the others in 13c and belongs there, not inside a statutory fix.

**Phase 13c — an action that fails outright.**
`TDS-18` (save raises a CHECK violation on the screen's own default state) ·
`ACC-18` (a firm lock outside four hardcoded years is un-unlockable) ·
**§3a** (a revenue ledger cannot be created) · **§3b + FA-09** (seven tabs 404,
and the endpoint behind them is wrong too) · `IT-33` (advance-tax instalments
hardcoded to FY 2025-26 — today the hub shows four elapsed instalments under
last year's heading) · `ACC-20` (`PATCH /journal/{id}/post` is mounted against
the in-memory demo store and 404s in any real deployment).

**Phase 13d — the statutory calendar.**
`PAY-19` — an invented PT challan row for every client, and both calendars omit
the **ESI deposit (15th)** and the **monthly salary-TDS deposit (7th)**: the two
that attract interest.

Everything after that is the long tail in `results/`, unchanged in priority.

---

## 7. Where the evidence lives

The nine per-slice verdict files, each `{id, verdict, evidence, how, notes}` with
`path:line`, are the raw record. They are **session scratch and are not committed**
— what survives is this document. Anything in them that mattered is in §2, §3 and
§6 above.

The brief the agents were given is worth keeping as a method: give the verifier
the finding's own evidence, forbid edits and test runs, require `path:line`,
make `unclear` a legitimate verdict, and ask for a `notes` field on anything the
finding does **not** mention. §3 came entirely out of that last instruction.
