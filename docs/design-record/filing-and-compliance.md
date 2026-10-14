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

## From the 14-10-2026 audit of the browser's direct writes

- **A GST RETURN IS APPROVED, REBUILT AND REOPENED THROUGH THE API, AND THE DATABASE ASKS WHO MAY APPROVE** (migration 491, ledger POST-A-223 and POST-A-224). Four defects of one family, found by an audit of every write the browser makes straight to the database. (1) `approveGSTR1` / `approveGSTR3B` set `status: "ca_approved"` and `ca_approved_by` on the return table themselves, with the approver supplied by the page. The route reserves approval to `gst:approve` (Manager and above); the table's policy asks `gst:compute` (Executive); a row policy cannot tell an approval from any other UPDATE, so an Executive approved a return, and the page sent the Supabase AUTH id for a column that is a foreign key to the INTERNAL user id. They now PATCH the status route like `markGSTR1Filed` did already, and take no approver from the caller. (2) `saveGSTR1Return` / `saveGSTR3BReturn`, reached on every Build or Compute click, upserted `draft` or `validated` over whatever the row held: a return the CA had filed on the portal came back as an unfiled draft with a CA Approve button, its ARN, filing date and approver still on the row and the `filings` row (the period lock) still in place. They refuse a submitted return in the server's own words and void an earlier approval (the server's recompute does the same). (3) The server's save of the ANNUAL return did the same to a filed GSTR-9, and the status routes asked the ROLE and not the PERSON (`can(role, ...)`), so a Partner's grid decision was ignored; a re-save, a recompute, a delete and a PATCH to `draft` of an approved or filed return all went through for anyone who could compute. `_approval_needed_to_change` now asks `can_user(person, "gst", "approve")` before any of them, and a zero-row UPDATE is no longer read as success. (4) Migration 491 is the backstop for a request that is not the screen's: RESTRICTIVE policies on both tables so that a return currently `ca_approved` or `submitted` changes, and a return is given either status, only for someone for whom `my_permission('gst', 'approve', 'Manager')` holds, and a filed return is deleted by nobody signed in.
  - **THE GUARD THAT MISSED IT WAS WRITTEN FOR A SPELLING.** `a-filed-gst-return-locks-its-period.test.ts` looked for `submitted` and filed dates, so an approval and a reset to `draft` walked past it. It now asserts the approval and the save by their shape (no PostgREST write in `approve*`, the status route with the CA's confirmation, the envelope checked, no approver parameter; the save reads the existing status before it writes, refuses a filed return and voids an approval) and has a rule that nothing in the browser sets an approval on either table. Eleven of its new tests fail against the old code.
  - **WHAT IS NOT DONE.** The browser still computes and writes the whole return row itself (about thirty columns); moving that persistence to the server door is the larger fix the audit named, and the API's save door does not yet accept the credit-ledger columns the screen writes. A Manager can still move a submitted return back to draft through the status route (the route's rule, not a row-policy question). A save into a locked financial year is not refused on the browser path (the server door does). The GSTR-9 save keys on financial year and not on registration, so a client with two registrations collides.
  - **THE SAME RULE REACHES MCA FILINGS (migration 493, POST-A-225) AND THE ITR CALENDAR TICK (POST-A-226).** The MCA screen wrote `status: "filed"`, the SRN and a date straight into `mca_filings` in three places (create, mark one, mark a batch), and the create path supplied TODAY as the date a filing was made, a date the software invented and presented as a fact about MCA21. The route requires Manager and above and the CA's confirmation; the table's policy asks Executive. All three go through `PATCH /api/mca-workspace/filings/{id}/status` now, the add modal creates the row not started and records it filed afterwards with an SRN and a date the CA typed (an Executive is told the row exists and was not marked filed), and the route asks the PERSON (`can_user`), refuses a zero-row UPDATE as a failure and refuses to reopen a filed filing without approval. Migration 493 is the backstop on `mca_filings` with the same shape as 491. The ITR screen's single and bulk "mark filed" wrote `filing_status: "filed"` into `compliance_calendar`; they use `api.compliance.markFiled` like the GST tracker, which cleans the date, audits and answers a refusal as `{ success: false }`. The tier is Executive at both ends, so that one is a bypass of checks and not a tier gap; the web guard's list of screens that still write a filing state is now EMPTY and `mca_filings` joined its table list.
  - **NOT DONE.** `tax_audits` status `completed` / `filed` (with UDIN and acknowledgement number) is still written from the browser with no API door at Executive tier while `itr_filings` is Manager (POST-A-226, a decision). `complete_filing` on the MCA route still defaults the filing date to today when the caller sends none; the browser now always sends one. The MCA create route accepts only eight form types and the screen offers more, so creation stays a browser insert.
