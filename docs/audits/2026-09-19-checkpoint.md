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

**The redesign (THE-PLAN) is where the work now is.** T1, T2, T3 and T4 are
done; T5 is in progress.

---

## In flight

**PR #567** — `claude/ca-platform-audit-roadmap-yuoad3`, two commits, open and
green locally. Carries no migration.

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

1. **T5b-1 + T5b-3** once the scope question is answered. A shared workbook
   module with no caller would be the `capital_wip` shape this file keeps
   recording, so the two land together.
2. **T5b-4** — `shareToPortal` writes to storage from the browser, so `rbac()`
   never runs.
3. **T6** — navigation and the module hub, which is also where the one
   `deferred_to_the_redesign` finding is answered.
4. **The 68 remaining unpaged PostgREST reads.** Recorded, deliberately not
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
