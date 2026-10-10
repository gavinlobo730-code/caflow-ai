# Design record: Payroll: accrual, PF on actual wages, bonus, monthly review, declarations

Moved verbatim from `CLAUDE.md` on 10 October 2026 (the owner asked for the always-loaded file to be slimmed).
Nothing here was rewritten. Wherever the text says "this file" or "CLAUDE.md" it means the design record as a whole
(this directory plus `CLAUDE.md`). Each entry below is one block of the old file, in its original order, under the
section it came from. `CLAUDE.md` lists every entry's headline in its "Design record index".

## From CLAUDE.md section: Indian tax domain rules — never violate these

- **THE PAYROLL ACCRUAL HAS TWO DEBITS, AND THE EMPLOYER SHARE COMES OFF THE
  SLIPS** (PAY-25). Schedule III Division I Part II presents Employee Benefits
  Expense as (a) salaries and wages, (b) contribution to provident and other
  funds, (c) share based payments and (d) staff welfare. `_build_payroll_lines`
  posted ONE debit for gross PLUS the employer's 12% PF, EDLI, the EPF
  administrative charge and the employer's 3.25% ESI, so **(b) was nil on every
  payroll client's note and (a) was overstated by exactly the contribution** —
  and the split cannot be recovered afterwards, because one posted debit
  carries no record of how much of it was contribution and a posted journal
  cannot be rewritten (migration 251). It has to be two lines at the moment of
  posting or it is not recoverable at all. Salaries takes **gross** (§17(1));
  `Contribution to Provident and Other Funds` (5016, migration 375) takes the
  employer side. The **administrative CHARGE is a fee, not a contribution**,
  and is grouped there anyway because it is remitted on the same challan and is
  universally presented with PF. **The employer share is summed off
  `payroll_slips`, paged** — `payroll_runs` stores only the COMBINED
  `total_pf_paise` / `total_esi_paise` and has no column for either employer
  half, so reading the slips is the only way, and it also means an old run
  finalised after the change splits correctly with no cached figure to drift.
  **The subtype `Employee Benefits` is load-bearing**: `schedule_iii.classify`
  buckets on it, so both accounts land under one caption and the P&L total is
  unchanged — only the note's sub-split moves, which is what makes this safe
  against books already holding one-line entries. **The range guard became an
  EXACT identity** (`gross + contribution == sum(credits)`), because the debit
  is no longer defined as sum(credits) and the kernel's balance check does its
  job again — it caught a fixture on the first run whose `total_net_paise` had
  deducted BOTH halves of the 12% from the employee's pay. Deliberately NOT
  extended to `_build_settlement_lines`: a leaver's F&F payload carries no
  employer contribution at all, so there is nothing there to split.

- **THE STATUTORY BONUS IS AN ANNUAL DEBT AND THE PRODUCT COMPUTED IT ONLY FOR
  LEAVERS** (PAY-23, migration 395). `domain/payroll/bonus.py` has implemented
  the Payment of Bonus Act 1965 since the payroll module was built, and its one
  caller was a leaver's settlement — so a client's CONTINUING employees, which
  is all of them most years, were never computed for. §10 makes the minimum
  payable "whether or not the employer has any allocable surplus", §19 makes it
  due within eight months of the accounting year's close and §28 makes
  non-payment an offence: it is a liability the balance sheet owes.
  `domain/payroll/bonus_register.py` is the register and calls `bonus.compute`
  rather than restating any of its sections. **EVERY EMPLOYEE APPEARS,
  INCLUDING THE ONES THE ACT DOES NOT REACH**, each with its own reason —
  §2(13)'s ₹21,000 ceiling, §8's thirty days, §9's forfeiture — because a
  register that silently drops them cannot be checked against the payroll.
  **§19's date is DERIVED from the year's own close**, not stated as 30
  November, so a client whose accounting year is not the financial year gets
  their own; the proviso allowing an extension on application is NAMED rather
  than assumed.
  **THE SERVICE READS THREE COLUMNS THAT EACH HAVE AN OBVIOUS WRONG
  NEIGHBOUR.** §2(21) salary is `basic_paise` plus DA and NOT the slip's
  `gross_paise`, which carries every allowance the section excludes; a month
  worked is a RELEASED run (PAY-04's reasoning — a draft has paid nobody, and
  here it would put a month of salary into a statutory debt); and §8's count is
  `attendance.days_present`, days ACTUALLY worked, not `working_days`, which is
  the establishment's days in the month. **An unrecorded working-day count is
  read as NEITHER nil NOR thirty**: nil would disqualify every employee at a
  client who runs payroll without attendance and hide the debt, thirty would
  assert a fact nobody holds — so the figure is shown, the employee is named,
  and the gap travels on the LINE as well as the summary.
  Migration 395 stores only what no ledger holds: the employer's own §10/§11
  rate (defaulted to the §10 minimum, which is owed whatever the surplus turns
  out to be) with §12's minimum wage, and §9 dismissals **CHECKed to the Act's
  five grounds** — a free-text reason would let "poor performance" forfeit a
  statutory debt, which §9 does not reach. ⚠️ **One §12 minimum wage per
  client-year is a stated simplification** (the section compares per SCHEDULED
  EMPLOYMENT and per skill grade) and the wage TABLE itself remains the human
  step §3b records. Nothing is posted — the provision is a journal the CA
  raises — and Form C (Rule 4(c)) and Form D (Rule 5) are named rather than
  produced.

- **THE THREE QUESTIONS ASKED ON THE 3RD OF THE MONTH, AND THE ONE THAT MOVES
  MONEY REFUSES A DRAFT** (PAY-27). A CA closing payroll asks why this month is
  bigger than last, what each department cost, and how the bank is to be paid —
  and the product answered none of them although every figure was already in
  `payroll_slips`. `domain/payroll/month_on_month.py`,
  `domain/payroll/department_cost.py` and `domain/payroll/bank_advice.py` are
  the three rules; the endpoints under `/api/payroll/reports/` fetch and the
  Monthly Review tab decides nothing.
  **THE VARIANCE BASELINE MUST BE RELEASED AND THE MONTH BEING LOOKED AT NEED
  NOT BE**, which is PAY-04's rule applied in one direction only: a draft has
  paid nobody, so comparing against one measures a number that has not happened,
  while the whole point of opening this screen is to check a draft *before*
  releasing it. It names EVERY component that moved rather than the biggest —
  a rise in basic and a fall in HRA net out, and reporting only the larger sends
  the CA looking in the wrong place — and where gross moved with no component to
  explain it the employee is listed as `unexplained` rather than dropped.
  `COMPONENTS` excludes `gross_paise` and `net_paise` deliberately: they are
  totals of the others, so counting them restates every cause twice.
  **DEPARTMENT COST IS PAY-25's TWO DEBITS REPORTED APART, AND NET PAY IS NOT
  COST.** What a department costs is gross (§17(1)) plus the employer's own PF,
  EDLI, admin charge and ESI — the split Schedule III Division I Part II makes
  at the moment of posting — reported beside each other rather than summed into
  one figure, because the second is remitted on a challan and the first is not.
  Net pay is what the employee BANKS, after their own deductions, and is a
  different question. **An unrecorded department is its own row**, never folded
  into another and never dropped: a client who has not filled the column in has
  one big row that says so, and a client who has filled in half has the half
  they can act on.
  **THE ADVICE MOVES NO MONEY** — it is a file the CA uploads to their own
  bank's portal, the same prepare-only posture as every statutory output here —
  and it **REFUSES AN UNRELEASED RUN**: `run_status` is a required parameter
  with no default and `None` refuses, because a default would have made a draft
  payable by omission. **Every employee it leaves out is NAMED with its own
  reason**, in a fixed order — no account, no IFSC, a malformed IFSC, a negative
  net, then a nil net — with the money asked LAST, so a missing bank account is
  never reported as "nothing to pay". The account number is MASKED on the screen
  and whole in the file: the screen is read over somebody's shoulder and the
  file is read by a bank. **The layout is deliberately generic** — each bank's
  own upload format is a document this environment cannot fetch, and inventing
  one would produce a file that fails at the bank rather than in front of the
  CA. **No migration**: `bank_account_no`, `bank_ifsc`, `department` and the
  four employer-contribution columns all already exist.

- **PF ON ACTUAL WAGES ABOVE THE CEILING IS AN ELECTION THE EMPLOYER RECORDS, ONE EMPLOYEE AT A TIME, AND THE PRODUCT NEITHER INFERS NOR CHECKS IT** (payroll-22, migration 477). `_compute_pf` capped the employee's 12% and the employer's 12% at the Rs 15,000 ceiling for everyone and the ECR builder capped the EPF wage the same way, so an employer who contributes on the whole wage (EPF Scheme 1952 para 26(6), a JOINT request of employee and employer) had a payroll that under-deducted, a ledger that under-accrued and a return that declared the wrong EPF wage. `domain/payroll/pf_wage_election.py` is the authority and **EVERY statement of law in it is `[S]`**: egress is refused here, `VERIFIED` is False, and nobody has read whether the joint request is REQUIRED in every case, what form it takes, whether EPFO accepts it for a member, or whether the Code on Social Security 2020 carries the paragraph forward. So it records **the employer's assertion** and nothing cleverer: `payroll_employees.pf_on_actual_wages` (NULL = never recorded, the statutory default and every row that exists; true = elected; false = recorded and withdrawn. NULL and false compute alike and are kept apart because "nobody said" and "somebody withdrew it" are different facts to read back; no default, no backfill), an optional `pf_on_actual_wages_from` and an optional `pf_on_actual_wages_reference` (the employer's own words, at most 200 characters, not a link and not an upload: no document workflow is built). **Per employee, not per client or firm**: the request is joint and EPFO treats contribution above the ceiling as a fact about the member, and an establishment switch would decide for the employees who never asked and the ones hired next year. **It is never inferred**, not from wages above the ceiling and not from an earlier month. `applies()` is the one rule: PF applies to the employee, the election is exactly `True` (`"yes"` and `1` are not an election), and the payroll month is on or after the date, **tested on the month's END as `wage_base.rule_in_force` tests it, because a month is paid as one thing**; an unreadable date or an unplaceable month answers the CEILING and never a guessed election; no date means every month. **What moves**: the employee's 12%, the employer's 12% (so the EPF half, which absorbs everything above the pension diversion) and the administrative charge, whose base follows the EPF wage `[S]`. **What does not**: EPS wages and the EPS contribution (still 8.33% of Rs 15,000, Rs 1,250), EDLI wages and the EDLI contribution, the wage BASE itself (the same `_pf_wage_base` the capped path takes: Basic + DA before 21-11-2025 and the s.2(88) aggregate after, so the pre-commencement branch keeps its own figure) and the rounding. `_compute_pf(on_actual_wages=)` changes ONE variable, `capped`, and EPS and EDLI read their own ceilings; `_pf_for_slip` is the one place a row becomes contributions for the run AND for `/statutory-position` (a test fails either calling `_compute_pf` itself), and the election is read off the employee row at compute time and cached nowhere, so a draft recomputed (PAY-21) after it is recorded, dated or withdrawn picks up what the row says now; nothing is added to `payroll_runs`. **The slip stores what was applied** (`payroll_slips.pf_on_actual_wages`, NOT NULL DEFAULT false: defaulted, unlike the master's column, because the value is KNOWN for every existing slip, nothing could elect before) and **the ECR reads the slip and never the row**, because the return declares what was remitted and the row can change after a month is finalised: a month computed capped stays capped on the ECR whatever the row says today, a month computed elected stays elected after a withdrawal, and restating a finalised month is a reversal and not a flag. The ECR's EPF-wage column is uncapped for such a member and EPS and EDLI wages stay at the ceiling; a member with no election files a **byte-identical** line (held as a matrix, as a property over any wage, and slip-key-absent against slip-key-false). **Three refusals on the ECR, each named per member**: an election recorded for an employee PF does not apply to (asked BEFORE the never-contributory skip, which would otherwise hide it), a slip that says actual wages and holds no PF wage, and a declared EPF wage the slip's own employee contribution does not follow within one rupee (a tie-out of two figures already on the slip and not a second computation; skipped where no rate is passed, which is every caller written before). **Both API doors validate and the database is the last line**: `EmployeeIn` and `EmployeeUpdateIn` clean the date and reference, and a PATCH is judged against the row it lands on (`plan_update`): PF off beside an election, and a date or reference without an election, are 422 sentences; a blank date or reference arrives as `""` and means CLEAR because PATCH cannot send a null; withdrawing (false) clears both with it. Migration 477's four CHECKs hold the same rules (an election needs PF; the detail belongs only to a true election; the reference is non-blank and at most 200 characters; the date is not before 1952) and are vacuous for every existing row. The row is read only when a PATCH touches the election or switches PF off, and a create with no election never names the new columns. **Every change is written to the edit log** with the AUTH id as actor and old values beside new (the withdrawal clears the date and reference from the row, so the log is where they survive). The CSV importer deliberately has no column for it, and a row that would switch PF off for an elected employee is refused up front, naming the row, rather than failing a CHECK halfway through an all-or-nothing file. **The screens**: the employee form shows the control only where PF applies and says, in the server's own words (`SCREEN_NOTICE`, pinned character for character from the Python side), that the product records a statement by the employer, does not check that the request exists, whether it is required or whether EPFO will accept it, that the reading is unverified, and that EPS and EDLI stay at the ceiling; the payslip PDF names it on the SAME deduction row (no extra row, no moved page break); the payslip modal, the run's slip tables and the Statutory Deductions screen label what the slip stored; the handoff names how many members the file carries on actual wages, adds the EDLI wage total (EPF wages are no longer what A/c 21 is raised on) and says EPFO's acceptance is not checked. **Not modelled, and named rather than guessed** (`NOT_MODELLED`): the higher-pension option under EPS para 11(3) as the Supreme Court read it in 2022 (a different joint option exercised with EPFO; EPS wages stay at the ceiling for every member), contribution on an amount the employer picks between the ceiling and the wage (the election is all or nothing), whether EPFO raises the administrative charge on the uncapped wage, and the joint request as a document. ⚠️ **The legal position is `[S]` and a person must establish it before the option is offered to a client**; nothing here is transmitted to any portal. ⚠️ **Seen on the way and NOT changed**: `domain/payroll/ecr.py` declares `EPF_CONTRI_REMITTED` as the employee's 12% PLUS the employer's EPF half (Rs 2,350 / 1,250 / 1,100 for a Rs 15,000 member) and `test_epfo_ecr` pins it, while the sample line EPFO's material is recalled as carrying reads Rs 1,800 / 1,250 / 550; unchecked, and an elected member's line follows the file's existing convention. ⚠️ **`payroll_employees.pf_applicable` defaults FALSE in the schema** (migration 014's CREATE TABLE won over 054/093's `DEFAULT true`, and the production snapshot agrees) while `EmployeeIn` defaults it True, so only the API's explicit value keeps PF on and a raw insert reads as "no PF", which the election's CHECK then refuses beside an election.

- **PAYROLL LEDGER ACCOUNTS ARE STILL FOUND BY NAME, AND KEY-FIRST IN THE ACCRUAL ALONE WOULD BE WORSE THAN THE RENAME PROBLEM** (payroll-29, NOT built; needs a migration). `journal_for_payroll`, `journal_for_settlement` and `journal_for_payroll_disbursement` resolve Salaries Expense, Net Salary Payable, PF/ESI/PT Payable and TDS Payable - Salary by ILIKE and `_find_account` raises on a miss or a rename. `_find_account` already supports a key, but no migration or seeder sets a payroll key, and `seed_firm_coa` sets a key on NO account. Switching only the three posting functions to key-first would let a renamed account finalise while `tds_return_service` (24Q GL tie-out, exact name 'TDS Payable - Salary') and `statutory_remittance_service` (`%ESI Payable%`, `%PT Payable%`) still look the SAME accounts up by name, so the accrual and its readers silently diverge. Migration 092 also stamped `tds_payable` on BOTH TDS accounts, so the salary account needs a new key, and `_find_account`'s key branch is firm-wide, unordered and unscoped, safe only for `client_id` NULL rows (migration 360's trigger refuses another client's account). The right shape is one vocabulary and one client-scoped resolver for every payroll reader and writer, keys backfilled only where exactly one firm-level row matches, seeded in `STANDARD_COA`, with a guard that no payroll reader names these accounts outside the vocabulary: one PR with its migration, not a code half first.

- **A DRAFT payroll run has deducted nothing** (PAY-04).
  `_tds_already_deducted_this_fy` and `_members_contributing_earlier_this_period`
  read `payroll_runs` with no status predicate while every other reader has
  filtered on `_PAYROLL_RELEASED` (`finalized`, `paid`) since migration 323 made
  RLS agree. Reading a draft credits the employee with §192 tax nobody withheld,
  so the month's withholding comes out too SMALL — and §192(1) makes the
  EMPLOYER liable for the shortfall with §201(1A) interest — and it keeps
  somebody in ESI past the ₹21,000 ceiling on a contribution that never
  happened.
  **AND THAT RULE IS WHAT MAKES A DRAFT REBUILDABLE** (PAY-21, closed
  17-09-2026). `POST /api/payroll/runs/{run_id}/recompute` deletes the slips
  and rebuilds them, and `DELETE /api/payroll/runs/{run_id}` throws an
  unreleased run away so migration 237's unique index stops making the month
  permanently uncreatable — without either, a run computed before the
  attendance was entered could only be fixed against the database, and
  reversing a finalised one reopens it at `review` with the SAME slips.
  Both are safe precisely because a draft has posted no journal, registered no
  §192 TDS and recorded no loan recovery, and because the two readers above
  count only RELEASED runs, so a rebuild cannot disturb what an earlier month
  withheld. `create_run`'s slip-building body is `_compute_and_store_slips` and
  BOTH doors call it — two copies would be two payrolls that agree until one is
  changed. A finalised or paid run is refused with a 409 naming the reversal
  path. **`_PAYROLL_UNRELEASED` is its own tuple and NOT the inverse of
  `_PAYROLL_RELEASED`**: the two answer different questions — which runs COUNT,
  and which have not yet paid anybody — and writing either as "not the other"
  would make a fifth status silently join both.

- **A DECLARED DEDUCTION HAS A DOCUMENT BEHIND IT, NOT A SENTENCE ABOUT ONE**
  (PAY-26, migration 410). `payroll_it_declaration_items.proof_reference` has
  been a bare TEXT column since migration 296 — somebody types "LIC receipt
  12345" and nothing holds the receipt — so the verifier set
  `amount_verified_paise` against a memory of a document, on the very decision
  §192(1) makes the EMPLOYER answerable for. Rule 26C's Form 12BB is a statement
  of particulars *with* evidence; the evidence half did not exist.
  **ONE ATTACHMENT RULE AND IT IS NOT NEW**: `domain/attachments`, the same
  authority manual journals (138) and bank transactions (259) use, with the same
  CHECK. Its two decisions carry over and both matter more here — the scheme
  vocabulary is CLOSED to http/https because an employee's own portal upload is
  precisely an untrusted uploader and a stored `javascript:` or `data:` URL is
  script execution in the app's origin the moment the CA clicks the "receipt";
  and an UPLOADED document stores the document id with NO url, because the
  firm's store hands back a signed url that expires in an hour and would be a
  dead link by the time an assessing officer asked.
  **`None` MEANS UNCHANGED AND `[]` REMOVES**, so the field defaults to `None` on
  a model that is the CREATE door and the VERIFY door both, and the verify path
  omits the column entirely when the request did not send it — an `or []` there
  wipes an employee's uploads every time a CA saves a verified amount.
  **`proof_reference` IS KEPT AND IS NOT REPLACED**: it is the employee's own
  words about a proof that may only exist on paper, and making it a caption for
  the attachment would make a row with paper evidence look empty.
