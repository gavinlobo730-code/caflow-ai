# Design record: What changes every financial year and the statutory data a human must supply

Moved verbatim from `CLAUDE.md` on 10 October 2026 (the owner asked for the always-loaded file to be slimmed).
Nothing here was rewritten. Wherever the text says "this file" or "CLAUDE.md" it means the design record as a whole
(this directory plus `CLAUDE.md`). Each entry below is one block of the old file, in its original order, under the
section it came from. `CLAUDE.md` lists every entry's headline in its "Design record index".

## From CLAUDE.md section: What has to be updated every financial year

**The pre-commencement branch takes its own figure, and that is not cosmetic.**
`compute()` used to return the s.2(88) wage aggregate for an earlier month too,
and the router had — correctly, for s.2(88) — folded medical, special and other
allowance into it. EPF Act **s.6** named three things: "basic wages, dearness
allowance and retaining allowance". So an October 2025 month on ₹10,000 basic
with ₹2,000 medical and ₹3,000 special deducted ₹1,800 where s.6 gives ₹1,200 —
wrong on every historic month carrying an allowance, and it recomputes on
demand, so a reprinted payslip disagreed with the challan actually remitted.
`pre_code_wages_paise` is now passed explicitly and the docstring says what it
is rather than claiming a reproduction that was false. Of the
components modelled, only **HRA** (clause f) and **LTA** (clause d, "the value
of any travelling concession") are excluded; everything else stays on the wage
side, because that is the direction that cannot under-deduct and because a cash
medical allowance is not clause (b) and a special allowance is not clause (e)
(*RPFC v. Vivekananda Vidyamandir*, 2019). Rates and both ceilings are
unchanged — it was only the base they apply to that moved. **ESI is deliberately
NOT changed**: `_compute_esi` uses gross, the Code's definition is narrower, so
ESI may err the other way — unconfirmed, and pinned by a test so a later change
is deliberate. Gratuity likewise. Verified 2026-09-04; see
`docs/compliance/04-mca-epfo-esic.md`.

| what | where it is refused | why it cannot be derived |
|---|---|---|
| minimum wage for §12 of the Bonus Act | `domain/payroll/bonus.py` | per state, per scheduled employment, per skill grade, revised twice yearly. §12 computes on ₹7,000 **or the minimum wage, whichever is HIGHER** — treating ₹7,000 as the ceiling underpays by half in most states |
| SBI's rate for Rule 3(7)(i) | `domain/payroll/perquisites.py` | published by the bank on the first day of the previous year |
| ESIC reason codes | `domain/payroll/esic.py` | ESIC's own list |
| an earlier year's total income for §89 | `domain/payroll/arrears.py` | comes off the employee's return; the employer never held it |
| prior gratuity / leave exemption used | `gratuity.py`, `leave_encashment.py` | §10(10) and §10(10AA) are LIFETIME limits across employers |
| a vendor's MSMED classification | `vendors.msme_status`, surfaced by `public.schedule_iii_ageing` | it is a fact about the SUPPLIER — their Udyam registration — that no ledger holds, and it is not presentational: §43B(h) (Finance Act 2023, AY 2024-25) disallows a deduction for sums payable to a micro or small enterprise beyond the MSMED §15 limit unless actually paid, so calling an unclassified vendor "Others" changes taxable income. The column has NO default; an unclassified balance is reported beside the payables table, never inside a row |
| whether a supplier has a WRITTEN payment agreement, and for how long | `vendors.msmed_agreement_days` (migration 373), recorded on the Schedule III ageing screen | MSMED §15 requires payment "on or before the date agreed upon ... IN WRITING, or, where there is no agreement in this behalf, before the appointed day", and §2(b) makes the appointed day fifteen days from acceptance. So the limit is **FIFTEEN days by default and forty-five only under a written agreement** — forty-five is the number every article quotes and it is the exception. Whether such an agreement exists is a fact about a contract no ledger holds, and `credit_days` is NOT evidence of one: it is a commercial term, and reading it as the §15 period would give 30 days where the Act gives 15 on every vendor carrying the default. NULL means no written agreement, which is the statutory default rather than an absence. A recorded period above 45 is STORED as the contract says and capped by the engine, which says it capped |
| the DTAA rate for a payment to a non-resident | `public.dtaa_treaty_rates` (migration 310) — one row per (country, nature), firm-scoped; `vendors.treaty_rate_bps` is now only a per-vendor override. Refused on the purchase-bill path when a TRC is held and nothing is recorded | §194C, §194J and their neighbours charge, in their own words, sums paid "to a **resident**" — so for a non-resident payee they do not apply at all and §195 does, at rates in force under Part II of the First Schedule by NATURE of income, with surcharge and cess, displaced by the DTAA under §90(2) where a TRC and Form 10F are held. Nature of income × ninety-odd treaties × surcharge band cannot be written from memory, and §206AA's 20% floor has a non-resident carve-out (§206AA(7) with Rule 37BC) that residents do not get. Under-deducting disallows the WHOLE expenditure under §40(a)(i). The ACT side is now computed — `domain/tds/section_195_rates.py` holds §115A and Part II by nature of income, with surcharge and cess — but §90(2) gives the assessee whichever of the Act and the AGREEMENT is more beneficial, and the agreement cannot be: ninety-odd treaties, differing royalty/FTS/interest articles, MFN clauses needing their own §90(1) notification (*AO v. Nestle SA*, 2023), and several — the UAE and Singapore among them — with no FTS article at all. So a CA reads the agreement once per country and nature and records what they read (Settings → DTAA Treaty Rates); the engine then applies §90(2) to the two numbers it has, and REFUSES where a TRC is on file and nothing is recorded, because falling back to the Act rate would over-deduct exactly where somebody has established a treaty applies. **"No article" is an ANSWER, not a missing rate**: several agreements — the UAE and Singapore among them — have no FTS article, which makes the income Article 7 business profits and not taxable here without a PE, so it needs the same no-PE declaration chargeability does |
| the §47 late fee outside what is held | `domain/gst/late_filing.late_fee` and `_annual_late_fee`; the refusal (`gst_late_fee_rates_not_held`) says what is missing | GSTR-1 and GSTR-3B are HELD for FY 2017-18 to 2026-27 (Notifications 4/2018 and 76/2018, then 19/2021 and 20/2021 from the June 2021 tax period) and GSTR-9 from FY 2022-23 (7/2023-CT, with the 2023 amnesty window for the years before it, which has closed): see the "What being late costs" paragraph. Still refused: any other return (GSTR-4, GSTR-6, GSTR-7, GSTR-8, CMP-08 and GSTR-9C have no fee entered here; whether and what each carries is open, see the open-items ledger and that return's own notification), a GSTR-1 or GSTR-3B year the table does not hold, a GSTR-9 before FY 2022-23 filed outside the amnesty window, and the State-level turnover GSTR-9's percentage cap is measured on (`cap_gap`: the answer is the uncapped accrual). What was PAID is a challan this product does not record, so GSTR-9 Table 19 stays unbuilt. Charging a refused case at the monthly ladder is a rate that was not in force |
| which accounts hold unbilled dues | `chart_of_accounts.unbilled_dues_side` + `public.schedule_iii_unbilled_reviews` (migration 305) | both ageing notes end "Unbilled dues shall be disclosed separately", and an unbilled due has no document — having none is what makes it unbilled — so the figure is a BALANCE on accounts somebody marked. No account name decides it: "Accrued Interest" may be income receivable or an expense payable. And the review is a SECOND fact: the markings say which accounts hold them, only the review says there are no others, so an unreviewed client shows no figure rather than a zero that claims it has none |

- **Depreciation — but read this, it changed.** There IS a statutory table in
  code now: `routers/fixed_assets.py::_SCHEDULE_II_PART_C` holds Schedule II
  Part C's useful LIVES, and the WDV rate is derived from them as
  `R = 1 − (residual/cost)^(1/n)` with residual capped at 5% (Part C Note 5).
  It still does not belong in the April sweep — lives change only by MCA
  amendment, not by Finance Act — which is why it is listed here rather than
  above. What it replaced was a set of flat literals in which Furniture 10.00%
  and Intangibles 25.00% were **Income-tax Act block rates** sitting under a
  form field labelled "Companies Act 2013 Sch II rate", every one of them
  under-depreciating. An asset's own stored `wdv_rate_percent` still wins over
  the default whenever it has one.

  **Schedule II Part C and the rules over it live in
  `domain/fixed_assets/`** (`schedule_ii.py` for the table,
  `integrity.py` for the five register checks), not in the router. Three
  callers read them — the categories endpoint the Add Asset drawer pre-fills
  from, `GET /register-integrity`, and `reconciliation_service`'s nightly sweep
  — and a service importing a router to reach a statutory table is the wrong
  direction and one refactor from a cycle. `routers/fixed_assets.py`
  re-exports the old names so existing imports still work.
  `integrity.COLUMNS` is the projection BOTH fetchers use: a column added to
  one query and not the other makes that one quietly answer "clean" on a
  finding it could not see.

  **AND A REDUCING BALANCE HAS TO BE TOLD WHERE TO STOP.** A WDV charge
  approaches its floor and never reaches it, so with the column's default
  `salvage_value_paise = 0` an asset was depreciated for ever — and the derived
  rates above sharpened that, because a rate derived from the life lands the
  asset exactly on its residual at the end of the life, so the overshoot begins
  precisely when the asset is fully depreciated. `_wdv_residual_at_end_of_life`
  is the terminal, and it is derived from the ROW'S OWN rate and life by
  running the same yearly chain the charges run — not from a 5%-of-cost
  constant (which would be a different asset's arithmetic wherever the CA
  recorded their own rate) and not from the closed form `cost × (1 −
  rate/100)^life` (which is a paise below where the flooring actually lands, so
  the asset takes a ₹0.01 charge in the year after it finished). The floor is
  `max(stored salvage, that residual)` — a salvage the CA deliberately recorded
  above the residual still wins. A row with **no useful life** keeps exactly the
  behaviour it has, because there is nothing to derive from; `register-integrity`
  reports those as `wdv_asset_has_no_stopping_point` rather than writing a life
  in, since a life is a Part C judgement about that asset and guessing one moves
  the profit. Straight line already terminates and is untouched, trailing paisa
  included.
