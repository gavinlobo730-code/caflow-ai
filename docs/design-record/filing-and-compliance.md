# Design record: Filing to government portals, trackers and the period lock

Moved verbatim from `CLAUDE.md` on 10 October 2026 (the owner asked for the always-loaded file to be slimmed).
Nothing here was rewritten. Wherever the text says "this file" or "CLAUDE.md" it means the design record as a whole
(this directory plus `CLAUDE.md`). Each entry below is one block of the old file, in its original order, under the
section it came from. `CLAUDE.md` lists every entry's headline in its "Design record index".

## From CLAUDE.md section: Indian tax domain rules — never violate these

- **AND THE PRODUCT WORDS THAT POSITION ONCE.** `domain/filing_posture.py` holds
  the badge, the banner headline, its body, the one forward-looking sentence and
  the long disclaimer; `services/filing_demo/common.envelope` serves them as
  `posture` on every walk-through, and `apps/web/lib/filing/posture.ts` is a
  FALLBACK for the redeploy window, pinned from the Python side by
  `tests/test_one_filing_posture_and_the_browser_echoes_it.py`. It used to be
  three voices — the payload's sentence, a DIFFERENT one hard-coded in
  `FilingDemoWizard`, and a guard that pinned the second with
  `assert.match(src, /DEMO — nothing is being filed/)`, a regex over the SOURCE
  that could not tell a rendered banner from a commented-out one and failed on
  any rewording. **What the wording may NOT claim is asserted**: no registration
  has been applied for (D17), so "in progress", "applied for", "pending
  approval" and "coming soon" are all forbidden and a test says so — a product
  that overstates its regulatory standing is a different and worse kind of wrong
  from one that overstates a feature. It says direct submission is **planned**
  and names what grants it. **The wizard carries no roadmap voice of its own** (COMING-016/017,
  9-10-2026): where software may transmit it renders the served `posture.roadmap`,
  where it may not it says only that no public API lets software transmit, and the
  PF ECR and ESI walk-throughs say the file IS produced today from a finalised run
  (`build_ecr`, `build_esic_return`) with the upload, verification and payment left
  to whoever holds the login; a guard fails the product's own future tense
  ("PracticeSync will") in a flow whose file is built.

## From CLAUDE.md section: Not built yet — known, deliberate, and not to be quietly started

**THERE ARE TWO TRACKERS AND BOTH LOCK THE PERIOD** (gst-27, practice_management-15,
frontend_ux-26). GST-14 made the `/gst` tracker (`compliance_calendar`) write
`public.filings`; the OTHER tracker, `compliance_records` — which `/deadlines`, a
client's Compliance tab and Practice → Compliance all show — moved an obligation to
"Filed" and wrote nothing else, so the two doors a CA actually uses were the two that
locked nothing. `compliance_record_service.update_record` is the ONE place an
obligation becomes Filed, so the filing is recorded THERE and `mark-filed`,
`transition` and `PATCH /compliance-records` all get it. For a GSTR-1 or GSTR-3B it
writes the `filings` row over the obligation's OWN period bounds (a QRMP quarter locks
all three months) **before** the status moves, so a failed write leaves the obligation
open for a retry rather than Filed-but-unlocked (`record_filing` is idempotent).
**The filed date is REQUIRED for those two and never defaulted** — the lock message
quotes it — and a refusal is asked BEFORE the first step of the four-step walk, so it
does not strand the obligation at Ready To File. A record cannot be CREATED already
Filed (a second way to Filed that locks nothing), and `gst_filing_record_service` now
holds the one map of which returns lock and the per-type reason for each that does not
(GSTR-9, TDS, ITR…), re-exported by the calendar router so the two doors cannot
disagree. The screens share `components/compliance/MarkFiledModal` and tell the CA what
the server did (`lib/compliance/filingOutcome`, which renders an ABSENT answer as
"could not confirm", never as "nothing was locked"). Nothing is backfilled: production
held one GSTR-3B obligation Filed without a lock, in a QA test firm. **THE WORKSPACE DOORS ASK FOR THE DATE TOO** (PRE-A-007, 08-10-2026): `record_filing` used to default a missing `filed_date` to today for a GSTR-1 or GSTR-3B, and the two firm-level mark-filed dialogs sent none, so a return filed on the portal on the 11th and recorded on the 14th was stamped the 14th, the date the period lock quotes and the s.37(3)/39(9)/16(4) window is measured from. `gst_filing_record_service.checked_filed_date` is the one rule (required, a real YYYY-MM-DD, not in the future, not before the period it declares ended, a QRMP quarter judged on the quarter's end), asked BEFORE the status moves by `routers/gst_workspace` (a refusal is that router's HTTP 200 `{success:false}` with the sentence) and by the calendar door (422), because `record_filing` sits in a swallow-and-log `try` and a refusal raised inside it would leave a return Filed with no `filings` row and so no lock. `markGSTR1Filed` / `markGSTR3BFiled` take a required `filedDate`; the two dialogs use `DateInput` with the `useDateProblems` gate, start empty and show the server's sentence. Other filing types keep today's behaviour. Not changed: the per-client GST tab's `MarkFiledDialog` still prefills its native date input with today (the guard covers that it sends `filed_date`), and `filing_history` shows `submitted_at`, the recording time, not the portal date.
