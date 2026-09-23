# Checkpoint — 19 September 2026

Written at the owner's request as a stopping point. Read this first when
picking the work back up; then `docs/plan/THE-PLAN.md` for what is next and
`docs/audits/questions-for-the-owner.md` for everything waiting on a human.

**Supersedes `WHERE-WE-STOPPED.md`**, which is an 11 September snapshot and was
never amended.

---

## Where the work stands

**The audit backlog is finished.** Of 279 findings: **259 closed**, 12 partial,
5 not-a-defect-as-stated, 1 deferred to the redesign, and **2 open** — and both
of those are blocked on a document a person has to fetch, not on code:

| finding | what it needs |
|---|---|
| the TDS FVU/RPU writer | the NSDL file layout, and a correction-statement model |
| the GSTR-9 filing demo | the GST offline utility's own screens |

`docs/audits/findings-status.json` is the record and is amended in the commit
that closes a finding. Its four states are not interchangeable — read
`findings-status.md`'s header before quoting any number from it.

**The redesign (THE-PLAN) is where the work now is, and its tracks are NOT
level.** Counted off the plan's own item rows on 19 September rather than from
memory — an earlier draft of this paragraph read *"T1, T2, T3 and T4 are done;
T5 is in progress"*, which was wrong about three of those four and would have
sent the next session straight past the one track everything downstream waits
on:

| track | state, by the plan's own rows |
|---|---|
| T1 — safety net | **7 of 7 done** |
| T2 — demo data | 1 of 3; only T2-0, the 18 corrected GSTINs |
| T3 — design system | 3 of 6 fully done. T3-c is 5 of 6, T3-e's guard is half built |
| **T4 — token adoption** | **0 of 4, and it is the bottleneck** |
| T5a — documents | 5 of 9 marked ✅. T5a-3's condition is in fact met — `invoice_pdf_service` imports `invoice_layout` and `email_service` imports `email_template` — so the row is simply unmarked, making it 6 in substance. T5a-5 is owner-blocked (§M) |
| T5b — spreadsheets | 1 of 5; T5b-5, the one CSV writer |
| T6 / T7 / T8 / V | not started. The plan marks T6 and T8 `BLOCKED on T4` |
| T9 — backlog | effectively done; open + partial is **14**, was 49 |

The plan's own critical path is **T1 → T3 → T4 → T6 → T8 → V**. T4 is
unblocked today and nothing else on that path can start until it moves.

Re-measured the same day, against the plan's own commands in its metrics
section:

| check | plan records | measured 19 Sep | target |
|---|---|---|---|
| hardcoded hex colours | 116 | **170**, but see below | 0 |
| arbitrary font sizes | 405 | **379** | ~130 |
| error boundaries | 65 | 65 | ≥ 14 |
| Cloudflare redirect rules | 98 | 98 | ≤ 90 (cap 100) |
| browser-side Excel writers | 7 | 7 | 0 |
| backlog open + partial | 49 | **14** | ≤ 10 |

⚠️ **"The hex count has gone UP, 116 → 170" was WRONG, and the correction is
worth more than the figure.** Checked on 24 September before any work started:
nothing regressed. The plan's metric is a coarse `grep` for `#RRGGBB`, while the
guard — `apps/web/scripts/a-colour-and-a-type-size-come-from-the-token-file.test.ts`
— counts three separate populations, and the coarse grep is their sum plus
comments plus an allowlist:

| population | now | budget |
|---|---|---|
| hex in a Tailwind arbitrary class (`border-[#E2E8F0]`) | 98 | 98 |
| bare hex outside a class (`style={{}}`, an SVG attr, a prop default) | 46 | 46 |
| arbitrary font size (`text-[13px]`) | 392 | 405 |

All eight guard assertions pass on `352dec8c`. Both hex budgets sit exactly at
their ceiling, so a new colour written today fails CI — the ratchet doing its
job. The lesson is the one this file keeps recording in other words: **a metric
and the guard that enforces it have to count the same population, or the metric
reports a regression the guard cannot see and nobody can find.**

---

## In flight

**PR #567 — merged**, as `0485c88a`. Two commits, no migration. Recorded here
because this section read "open and green locally" when it was written, an hour
before the merge.

1. **Three export screens read only the first 1000 rows.** PostgREST's
   `db-max-rows` cap is silent, so a risk report and a receivables ageing were
   downloaded short with nothing to say so. Now paged through
   `lib/supabase/selectAll`, each with the unique `.order("id")` tiebreaker
   OFFSET paging needs.
2. **T5a-1 + T5a-2 — one PDF palette.** Six services had four different header
   fills; the navy was on the year-end pack, the set a CA signs.
   `services/pdf_style.py` is now the only place a PDF colour is decided, and
   the palette is the product's own, pinned to `tailwind.config.ts` from the
   Python side.

Two contrast defects fell out of the second and are worth knowing about
independently of the consistency work: the invoice's and payslip's small text
was reportlab's stock `colors.grey` at **3.95:1 on white**, below WCAG 1.4.3,
on the style that carries the Rule 46 citation and the bank details a customer
pays into; and the reconciliation's tie-out rule was **#94A3B8**, at 2.56:1.

---

## What needs the owner

Full detail in `docs/audits/questions-for-the-owner.md`. The three that block
work already specified:

| § | question | what it blocks |
|---|---|---|
| M | **the rupee-glyph font licence** — FreeSans is the only near-metric match for Helvetica and is GPLv3; DejaVu is permissively licensed and 1.13×/1.26× wider, which re-breaks the columns T5a-4b just fixed | T5a-5, and with it ₹ on every PDF |
| — | **T5b-3 scope** — convert all 11 browser export actions to endpoints, or only the 5 that bypass `rbac()` | T5b-1 and T5b-3 |
| F | **six documents to fetch** — TDS file layouts, §194I/194J + Form 3CD, the GST offline tools, a bank salary file, the ITR schemas, professional tax | the two open findings, and the annual ITR schema refresh |

Nothing else is waiting on anybody.

---

## What is next, in order

1. **T4 — token adoption.** The critical path, unblocked, and the only track
   whose own metric is moving backwards (hex 116 → 170). T4-a is the codemod
   over the hex literals, T4-b the judgement pass over the 8,234 named-colour
   utilities, T4-c the type-size codemod, T4-d the width sweep. **T6 and T8 are
   marked `BLOCKED on T4` in the plan**, so this is what unblocks the rest of
   the redesign.
2. **T5b-1 + T5b-3** once the scope question is answered. A shared workbook
   module with no caller would be the `capital_wip` shape this file keeps
   recording, so the two land together. Parallel with T4 — different files.
3. **T5b-4** — `shareToPortal` writes to storage from the browser, so `rbac()`
   never runs.
4. **T6** — navigation and the module hub, which is also where the one
   `deferred_to_the_redesign` finding is answered. Not before T4.
5. **The 68 remaining unpaged PostgREST reads.** Recorded, deliberately not
   swept: most are bounded in practice by one client or one month, and a budget
   over 68 files is the shape that gets raised until it means nothing. Worth
   revisiting per-screen when each is next touched.

---

## How to check the state yourself

```
cd apps/api && python3 -m pytest tests/ -q          # ~16,700, mock mode, no DB
cd apps/web && pnpm test && pnpm build
```

The real-Postgres set self-skips without `HARNESS_PG` — 1,539 tests invisible
locally unless you stand one up. CI's exact invocation is:

```
HARNESS_PG="host=127.0.0.1 port=5432 user=postgres password=postgres" \
  pytest tests/test_migrations_apply.py tests/test_atomic_journal_posting.py tests/test_*_pg.py
```

And the 60-module browser-contract set, which `pnpm test` cannot see:

```
cd apps/api && python3 -m pytest $(python3 -c "import sys;sys.path.insert(0,'scripts/ci');\
import tests_reading_the_browser as s;print(' '.join(str(p) for p in s.modules_reading_the_browser()))") -q
```
