# Plan for Thursday 19 and Friday 20 November 2026 (IST): finish the before-demo items, then make the CA deck

Written on 18 November 2026 at the owner's request. It is a plan, not a ledger: the ledger (`README.md` and the section files) says what is open, and `checkpoint-2026-11-18.md` says what is merged and what is not. Read both first. Work in **normal mode** (`docs/operations/emergency-mode.md`): no emergency powers unless the owner switches them on in words.

## 1. Where things stand

- **57 items are before the demo** (the list is the three `pre-demo-` files and every line with the header token `before demo`): **10 Claude can do alone** (the eight of section 2, and POST-A-475 and POST-A-476, section 3), 2 need the owner's hands, 26 the owner decides first, 19 only the owner or someone outside can do. 586 backlog items and 26 new findings are open in all; nothing is parked.
- **What is done by Friday, and what the deck shows (the owner's decision of 18 November 2026):** by Friday only the 57 before-demo items are done; about 560 stay open. **The deck is made on the whole platform as it is meant to be when all 612 are done**, and every feature on it carries a status badge, so that what is not built yet is shown as work in progress (WIP) and never as something that works.

## 2. Thursday from 04:30 IST (the weekly limit resets): the 8 Claude-alone before-demo items, while the owner sleeps

These are POST-A-447, 468, 469, 470, 471, 472, 473 and 474. Most are already built on branches that are **not merged and not independently reviewed**; the work is to land them correctly, one theme per pull request, branched from `main`, each merged only when both required checks are green and the branch is current with `main`, and **nothing half-finished merged**.

| Items | Where the work is | What is left |
|---|---|---|
| 473, 474 (dialogs; the 45-second bound on bulk loops) | branch `claude/u16ekt-e4-dialogs-drive`, commit `f92d2b1c`, directly on a commit `main` holds | Rebase onto `main` (the design record has a conflict), independent review, the drive, merge; then delete the two findings' lines, re-close POST-A-395, add the ids POST-A-470 and 471 where its record paragraph says "the two unfixed findings". **Do this first: it is a gap in live code.** |
| 472, 468 (employee re-import wipes identifiers; attendance export writes seeded days) | branch `claude/u16ekt-f1-payroll-people`, head `53bba756` | Rebuild on `main`, review, merge. Also mark POST-A-082's remaining parts waits on owner and write owner-list S42 (the question is in the checkpoint). |
| 470 (screens whose requests never time out) | branch `claude/u16ekt-f3-timeouts-baselines`, head `a6e03745` | Rebuild on `main`, review, merge. Also record its new finding (the database client's own transport has no time limit) and the owner-list row for the marketing site's check as a required check. |
| 469, 471 (Reports P&L added up in the browser; the picker that runs off a short window) | branch `claude/u16ekt-f2-shared-ui`, head `ec756b85`, **unfinished** (six commits, builder interrupted) | Read the commits, finish or drop the unfinished parts and say so in the ledger, review, merge. |
| 447 (what each member sees, screen by screen) | branch `claude/u16ekt-f5-audit-export`, head `dee0ce20` | Merging it narrows 447 to a live walk that needs the owner's hands, so 447 becomes a "together" item and **the Claude-alone count becomes 7**. F5 also carries a portal fix and a new owner decision (archived-client portal contacts). |
| the combination | branch `claude/days-sized-ledger-items-u16ekt-train7` (F1, F3, F4, F5 on the pre-squash base) | Not mergeable as it stands; take its commits again onto `main`. F4 is not before-demo (it narrows POST-A-267, 206, 092 and leaves 057, which needs an owner money decision). |

- **Review before merge, not after:** two lenses per batch and two skeptics per finding, at most three sub-agents at a time, briefed with the goal, the files and what is ruled out. A finding is real if no skeptic refutes it. Spend review first and twice on the riskiest diff.
- **Prepare the next batch while the last one's checks run** (about 33 and 48 minutes on a large change). Fold ledger and document edits into the pull request they belong to; regenerate the counts with `python3 scripts/open_items_counts.py`, never by hand.
- **Stop and write it down** (a checkpoint, as on 18 November) if the usage limit or the clock cuts a batch short.

## 3. Thursday, once the owner is awake: the 47 before-demo items that need him, and POST-A-475 and 476

- **POST-C-214 (the owner's own): go through each filing and each filing walk-through himself, first.** The September research behind docs/compliance and the walk-throughs is out of date, so he opens the live portals and registration pages from outside this container, notes what can be done today and what each walk-through gets wrong, and hands Claude the corrections. **This comes before POST-A-476 and before the deck.** While there: whether the Account Aggregator conclusion still holds (POST-C-167).

- **POST-A-475 (Claude alone, done with the owner present): review every open item for the ones that are impossible.** Impossible means no lawful and technically available route exists for anyone, however much time or money is spent (the Account Aggregator bank feed and filing through an EPFO, ESIC, MCA or state professional-tax API are the known examples). It is not the same as hard, or as gated (a route exists but waits on a registration, a bank, a regulator, a document or his money). Claude reads each item with its sources, writes the evidence and its grade ([P] primary text, [S] search summary), and the owner confirms each before it is closed as 'cannot be done' and every promise of it is removed from the screens, the site and the deck. This runs before the deck, so the deck promises nothing impossible.
- **POST-A-476 (Claude alone, with the owner present, after POST-C-214): the filing access table.** For each filing, which key, registration or credential can be had (NIC production credentials for the e-invoice and e-way bill; a GSP contract for GST returns; ERI registration for ITR; the self-service software-utility registration), and which can never exist because no filing API or programme exists (MCA, the EPFO ECR, the ESIC contribution, professional tax, TDS statements). Then every promise is aligned: the filing walk-throughs for those five stay only if they are renamed as guides to the portal's steps (the client's MCA page offers a button labelled "File (demo)" today), the site, the demo script and the deck say prepared here and filed by the CA, and the owner decides whether the goal text "not complete until real filing works" becomes "real filing wherever a route exists". Demonstrate none of those walk-throughs as filing until this is done.

- **Cheap, large risk reduction (hours each, mostly his):** the security settings (enforce the content security policy, restrict accepted token algorithms, upload size and type limits, the error-tracking region and the sub-processor list, check the security headers in Firefox and Safari, the alert rules), a security contact, replace the smoke-test login, confirm the error tracking is on, the uptime monitor, an always-on API plan to end the cold start (his money), custom mail for sign-in and invites, a business mailbox for demo requests.
- **Decisions:** a real Privacy Notice and Terms, the pricing-page promises, the one fee-billing engine, the Tally import rules, opening the government sites to Claude (which unblocks the statutory readings), the first-run staffing promise.
- **Statutory readings and proofs (his and a practising CA's):** verify the FY 2026-27 figures, the PF and ECR readings, prove the GST and payroll files on the real portals, the ITR Part A layout, the composition rates.
- **Rehearsals and walks (the 15 from 2 October):** seed the demo firm and walk it, rehearse sign-up and the portals as a stranger would, check six outputs against one real client's filed figures, print the outgoing documents and read them, the outside-CA rehearsal, wake the API before the demo.
- Work through them in that order with the owner, closing each line with its evidence in the same commit.

## 4. Thursday and Friday: the deck for the CAs (after the before-demo items are done)

**Prerequisite.** POST-C-214 (the owner goes through the filings and the walk-throughs himself, because the September research is out of date) and then POST-A-476 (the access table, built on his corrections) are done first; the deck is built after both.

**Scope and status.** The deck covers the whole platform, real filing included. **A live bank feed is not shown as coming**: the Account Aggregator route is closed and no other route is promised (statement upload is the way in), so it appears only as "statement upload", LIVE. Each feature on a slide is badged one of three, taken from the ledger and the coming-soon register **as they stand on the day the deck is made, not from memory**:

- **LIVE:** built and in production; shown with a real screen of the seeded firm; safe to demonstrate.
- **PREPARE-ONLY:** the platform prepares and the CA files on the government portal and records it here; any filing walk-through is a simulation and says so.
- **WIP:** not built yet; shown as a concept slide, never as a screenshot of a screen that does not exist, with what gates it where the register says (real filing needs registrations only the owner can obtain).

The demonstration guide shows only LIVE features and the labelled simulations. Where a competitor slide touches a WIP feature the deck claims nothing better; it says what the competitor does (sourced) and that ours is WIP. Replacing Tally is the direction and is badged WIP: today the platform runs beside Tally and the importer writes customer and vendor masters only.

Make it in Claude Code: start from the slides type (`Artifact` quickstart with intent `slides`; it downloads as a .pptx or a PDF), or the `pptx` skill if that is not offered. **The deck must be true, because being believed is what this product has that a rival does not.**

**Slide plan (about 25 slides)**

1. **Opening (3):** who it is for (small and mid-size CA firms with 15 to 150 SME clients), the problem in their words (five tools and spreadsheets between them), what PracticeSync is (one ledger for the practice, the accounts, GST, TDS, income tax, payroll and banking).
2. **What it does, by area (8):** practice management (clients, tasks, deadlines, engagements, billing); accounting and the one ledger (Schedule III statements, ageing, year end); GST (GSTR-1, 3B, 9, 2B reconciliation, amendments, e-invoice and e-way bill preparation); TDS and TCS; income tax (computation, capital gains, 3CD, ITR preparation); payroll (PF, ESI, professional tax, bonus, Form 16 workings); banking (statement import, matching rules); the client and employee portals; PracticeSync AI. One real screen of the seeded firm per LIVE slide, never a mock-up; a WIP feature gets a concept slide badged WIP.
3. **Why it is different (3):** one ledger, not five; a screen says what it read, what it did not and what it will not do (an unknown is never shown as a value); prepare-and-review with the CA's confirmation on every filing, nothing auto-submitted.
4. **Comparison (3):** the owner chooses the competitors (for example Tally, Zoho Books, a GST and ITR filing platform and a practice-management tool). **Every competitor claim carries its source page and the date it was read, nothing from memory; a claim that cannot be sourced is left out.** Claim better only where the feature is LIVE. Do not present filing as working (it is PREPARE-ONLY, with simulated walk-throughs, until the registrations exist) and do not say it replaces Tally (that is the direction and is badged WIP).
5. **Status at a glance (2):** one slide counting what is LIVE, PREPARE-ONLY and WIP, and one slide of the WIP roadmap with what gates each item.
6. **Close (2):** the pilot offer (run it in parallel, tell us what to change), what we need from the firm.

**Demonstration guide (about 8 slides, for the presenter, not the audience):** what to open in what order on the seeded firm, taken from `docs/operations/demo-script.md`, with the screen, what to say, what to avoid (the known gaps the owner decided to avoid or show), and the honest answer to the filing question.

**What the deck needs from outside the repository:** real screenshots of the seeded firm (a login to the live deployment or a local build with the demo seed; this container reaches only the product's own host), the owner's choice of competitors, and the owner's wording for the pilot offer.

## 5. What more we could add (for the roadmap slide; each is an existing ledger item, none is promised)

- **Moving a client's books in:** Tally ledger and voucher import beyond customer and vendor masters (POST-B-298, POST-C-153 to 155): the switch story.
- **Collecting from clients:** organizers and questionnaires (POST-A-207), automated document collection and reminders (POST-B-322).
- **Notices:** intake from a file, a rule-derived due date and a reply draft (POST-A-049, held by the owner's rule).
- **Returns:** the ITR e-verify clock (POST-B-120), the Form 16 and 130 importer (POST-C-086), attributing each document to a GST registration for multi-GSTIN clients (POST-B-091).
- **Trust:** a whole-firm data export in open formats (POST-A-205, partly built), a published security page.
- **The big one, last:** real filing, which waits on registrations only the owner can obtain. **Not on this list: a live bank feed.** The Account Aggregator route is closed; the one open route is a per-bank agreement the owner would have to open (POST-C-162), with no bank approached, so it is not a roadmap promise.

## 6. The message to paste into the next chat

> Read `docs/open-items/plan-2026-11-19-thursday-friday.md`, `docs/open-items/checkpoint-2026-11-18.md` and the counts block in `docs/open-items/README.md`, then continue in normal mode. First confirm that migration 715 applied to production and that main is green. Then, if the overnight session has not already, land the eight Claude-alone before-demo items in the order of section 2 of the plan: review before merge, one theme per pull request, nothing half-finished merged. The ninth and tenth, POST-A-475 (review every open item for the ones that are impossible, so nothing impossible is promised) and POST-A-476 (the filing access table: which key can be had for each filing and which can never exist, and make every filing screen, walk-through and slide say so), are done with me present. When I am awake I first go through the filings and the filing walk-throughs myself, because the September research is out of date (POST-C-214), and then we work through the 47 before-demo items that need me (section 3), and when those are done we make the CA deck (section 4): the whole platform as if all 612 items were done, every feature badged LIVE, PREPARE-ONLY or WIP from the ledger as it stands that day, every comparison sourced.
