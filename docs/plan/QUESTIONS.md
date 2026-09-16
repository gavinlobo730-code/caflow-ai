# Questions for the owner

Anything I hit while working that needs a decision, a document or a judgement
only the owner can make. **Nothing here blocks what I am doing** — I set the
item aside and carried on, or took a stated default and recorded it.

Read with `docs/plan/THE-PLAN.md`. Answered questions move to the decisions
table there and are struck through here.

**Status key:** `OPEN` · `ANSWERED` · `DEFAULTED` (I took a safe default and
carried on — you can still overrule it)

---

## Q1 — Make two GitHub checks REQUIRED · `OPEN` · needs repo settings

**Raised while doing T1-a, 16 Sep 2026.**

I fixed the code half: `browser-contract` is a new job in `backend-ci.yml` that
runs the 33 python guards which read `apps/web` whenever a frontend-only PR
lands — about 50 seconds, against the ~7 minutes the full suite costs. That
closes the hole where a redesign PR merged with the reachability guard never
evaluated.

**What I cannot do is make a check REQUIRED.** That is a branch-protection
setting on `main` and it needs repository admin, which I should not change on a
shared repo without you asking.

**Two checks to require** — Settings → Branches → `main` → Require status checks:

1. `browser contract — python guards that read apps/web` (new, from this work)
2. `lint · typecheck · test · build (Node 22)` — the frontend job carrying 716
   guards. **Its own header already argues it should be required** and explains
   why it is safe: the filter lives inside, in its `scope` job, so it always
   reports and can never hang as "expected" forever.

Until both are required they run and report, but cannot block a merge.

**Why it matters more than it sounds:** everything else in T1 makes the guards
see the truth. This is what makes them able to stop a bad merge.

---

## Q2 — Three frontend guards still only run when `apps/api` changes · `DEFAULTED` · low

`test_frontend_columns_exist_pg.py`, `test_frontend_status_values_match_the_check_pg.py`
and `test_frontend_never_writes_an_auth_id_into_a_users_fk_pg.py` need a real
Postgres, which means applying 470 migrations — the ~6 minutes the new job
exists to avoid. They self-skip in `browser-contract`.

They catch a frontend change naming a column or status the schema does not
have, which IS a real `apps/web` risk. Today it is caught only when the same PR
also touches `apps/api`.

**Default taken:** leave them skipping and name the gap in the workflow comment
rather than hide it. **The proper fix** is a mock-mode variant reading the
committed production snapshot in `tests/fixtures/` instead of a live database —
a build of maybe half a day, not a config change. Tell me if you want it and I
will do it; otherwise it stays named.


---

## Q3 — 12 more sites of the *shape* that crashed 13 screens · `DEFAULTED` · low

**Raised while doing T1-d, 16 Sep 2026.**

The smoke walk's 13 crashes were all one defect: a screen reading a nested
field off an API payload that did not have it. Two spellings:

* `x?.y.z` — the author wrote `?.` on the first hop and not the second. **I
  swept all 17 of these**, because writing `?.` once is an explicit statement
  that the value can be absent, so leaving the next hop bare is an oversight
  rather than a decision.
* `x && x.y.z` — the root is guarded, the field is not. **I fixed only the one
  the walk proved** (`CashBook.tsx:131`, `book.negative_days.length`) and left
  the other 12.

**Why the second group was left.** `x && x.y.z` reads as a deliberate guard on
the root by an author who may know the field is always present. Sweeping it
would be changing 12 files on a pattern match with no evidence any of them
fails — the kind of blind edit this codebase's own guard history warns about.

They are in: `fixed-assets/page.tsx`, `capital-gains/page.tsx` (×2),
`SalesDebitNoteEditor.tsx` (×2), `SalesCreditNoteEditor.tsx` (×2),
`PurchaseBillEditor.tsx`, and four others. Find them with:

```sh
grep -rnoE "\b(\w+) && \1\.\w+\.(length|map|filter|find|some|every|reduce)\b" \
  apps/web/app apps/web/components
```

**Default taken:** leave them and let the walk decide. Now that it renders
every screen, any of these that actually fails will show up as a named route on
the next run rather than as a guess today. Tell me if you would rather have
them all guarded pre-emptively.
