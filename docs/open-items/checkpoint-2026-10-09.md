# Checkpoint — 9 October 2026 (IST): what landed, what is left to build, what is owed

**`main` at `00e5801b`, the merge of #726, at about 23:30 IST.**

> **A snapshot, not a ledger.** The ledger is `README.md` and its six section files; this note says where a
> long run of pull requests stopped so the next session does not have to reconstruct it. Counts below were
> true when #726 merged (`python3 scripts/open_items_counts.py` gives today's). Every claim here about code
> was true of `main` on that day and goes stale like any other snapshot: read the code before acting on one.

## 1. Where things stand

- Open items: **761** (23 before the demo, 738 after), after PRE-B-005 and PRE-B-015 were closed.
- **The demo has no date.** The owner moved it later on 9 October 2026 and said not to fix one. The calendar
  the planning critic wrote (last migration merged Fri 23 Oct, code freeze Tue 27 Oct, rehearsal 28 to 30 Oct)
  was built on 1 November and is **superseded**; take only the order of the work from it.
- Owner rules in force: features are **built, not hidden**; a scheduled report **prepares and a CA clicks
  Send**; Pay Now stays visible and says online payment is coming soon; wording is "coming soon" for an
  ordinary feature, "planned" plus the gate for anything about filing or registration, "not switched on" for an
  owner-held switch; nothing is ever sent to a client's customers automatically.

## 2. What landed (squash-merged to `main`, #711 to #726; #712 is not in this list)

| PR | What | Ledger |
|---|---|---|
| #711 | A printed screen is not blank or clipped and names its client; the practice's fee screens link to its own invoices | PRE-A-016, PRE-A-018 |
| #713, #714 | The ledger records the demo moving later; the coming-soon register and its guard | — |
| #715 | The marketing site says "runs alongside Tally, one ledger" and no longer says it replaces four products | PRE-B-015 part b |
| #716 | Migration 481: workflow schema for both halves (schema only) | POST-A-200, POST-A-204 |
| #717 | A saved workflow runs every step it was saved with; running one workflow runs only that one | POST-A-204 first slice |
| #718 | The Team access drawer says what a block does not reach; a real-Postgres guard keeps the sentence true | POST-A-005 first slice |
| #719 | Migration 482: every firm chart has an Office Equipment ledger | PRE-A-004 |
| #720 | Pay Now says online payment is coming soon; the server refuses to make or send a mock link | PRE-B-002 part 2 |
| #721 | The PF ECR and ESI walk-throughs say the file is produced today | COMING-016, -017 |
| #722 | The money editors have a nightly browser drive; its first run fixed eight double-posting controls | PRE-A-015 first slice |
| #723 | The demo seeder writes honest books for eight clients on the real stack; the run fixed the defects behind them | PRE-A-004 |
| #724 | The scheduled-report rule: one pure module (which report, which period, which due date, who may be mailed) | PRE-B-002 part 1 |
| #725 | The footer's Privacy link opens a plain "How we handle your data" summary; the Terms link is gone | PRE-B-015 |
| #726 | The demo script: the owner's one sentence about filing, the product's own long form, the screens to steer round | PRE-B-005 |

## 3. Build waves not started (from the planning critic, in dependency order)

Sizes are the critic's, not measured. "Migration" gives the order the numbers must be taken in: number a
migration against `origin/main`, never the branch you are standing on.

| Id | What | Size | Needs | Migration |
|---|---|---|---|---|
| HON-1 | Reword the Scheduled Reports promise on both screens (COMING-002 still overstates) | hours | register | none |
| PAY-2 | Portal Pay under real access checks: the portal actor has no id, role or firm, so `can_access_client` is false and Pay would 404 the day a gateway is live. **Comes before any gateway is switched on.** | days | PAY-1 (done) | none |
| PAY-3 | Payment-link mail names the right supplier, escapes name and URL | hours | PAY-1 | none |
| RPT-2a | Stored schedules: runs table, `created_by`, widened report type, revoke browser writes; service and router | days | RPT-1 (done), HON-1, WF-S (done) | next free, with rollback |
| RPT-2b | The CA-click Send door (`report:export`, `mfa_guard`, recipients re-checked at send, compare-and-set) | days | RPT-2a | none |
| RPT-3 | Profit and loss and balance sheet documents, added to the exportable reports | days | RPT-1 | none |
| RPT-4 | Optional prepare-only sweep that writes "ready" rows and never mails | day | RPT-2a | none |
| WF-B | One workflow registry for triggers, actions and step types | days | WF-A1 (done) | none |
| WF-A2 | Schedule `last_run_status` from the real outcome | day | WF-B | none |
| WF-C | `create_task` assignee and due-in-days, placeholder parameters | days | WF-B | none |
| WF-D | Six CA starter workflows in engine shape | days | WF-B, WF-C; **a practising CA reads every statutory sentence first** | none |
| WF-E | Duplicate, archive, typed Start, run progress view | days | WF-D | none |
| WF-F | Poller over compliance records | days | WF-B, WF-C | none |
| WF-G | The builder page | a week | WF-E, WF-A2 | none |
| WF-H | Staff-only `send_email` through the practice mail door | days | WF-B, WF-C | none |
| WF-I, WF-J, WF-K | Persisted delay and claim function; schedule fan-out per client; event cursors | days each | WF-C or WF-I | one migration each, in that order |
| REG-2 | A scan that finds every "coming soon" or "not switched on" sentence with no register row, as a required guard | days | HON-1, PAY-1, RPT-2b, WF-E | none |
| CLOSE-1 | Close the remaining ledger lines (PRE-B-002 has three parts: edit the line, do not delete it) | day | the above | none |
| PAY-5, PAY-6 | Per-firm gateway credentials (encrypted, service-role only) | a week | PAY-2, owner decisions | later migration |

**Do not build:** an in-product "demonstration" payment provider with a Simulate-payment endpoint (PAY-4),
and outbox attachments so a schedule can send by itself (RPT-5). Both were put on the do-not-build list.

## 4. Slices of landed work that are still open

- PRE-A-004: TDS challans, PF and ESIC codes, practice and ITR data, partner remuneration and a composition
  or GSTR-8 client are not seeded; no screen was opened on the seeded firm; the live seeding has not been run.
- PRE-A-015: about 45 date fields, receipt allocation, add-asset, a payroll run and the CSV import's double
  Import are not driven; Firefox and Safari were never run; the nightly drive has not run on a GitHub runner.
- PRE-B-002: part 1's sender, migration and screen (RPT-2a/2b) and part 3.
- POST-A-005: the read policies for documents, payroll and bank accounts; each needs a role-tier decision.
- POST-A-204: branch targets through the API, action-type validation at save, role checks on an approval,
  audit rows, the other triggers.

## 5. Owner decisions still owed

1. Known gaps the demo fixes, shows or avoids (PRE-B-004); the demo script has the table, the Decision column
   is yours to fill.
2. Workflow permissions: who may author, activate, schedule and approve; who may Start; may a paused template
   be started by hand (the engine currently allows it and asks the owner to confirm).
3. May a workflow ever email a client's portal contact, and how much mail may it send to staff. The default
   the critic recommended is staff-only and no client mail.
4. Whether the staff Payment Link on a client's own sales invoice stays offered.
5. Whether to show a real payment at the demo, which needs Razorpay TEST keys and a webhook secret.
6. Copy: the hero's fourth figure, and the "Seven tools" and "Five tools. Five logins." numerals.
7. The demo firm: who attends, two or three real team accounts with client assignments, one active portal
   contact, a client with real ledger lines and a practice fee invoice.
8. Read before any new migration merges: the count of `scheduled_reports` rows; of `workflow_templates` and
   `workflow_instances` and any duplicate `(firm_id, template_id, idempotency_key)`; of
   `customer_payment_links` by provider and status.
9. Who reads the six starter workflows' statutory sentences (stale TDS form numbers, the s.208 threshold
   wording, the GSTR-9 tables sentence) before WF-D installs them.

## 6. Human steps (nothing in the repository can do these)

- Razorpay registration and a webhook secret; set `PAYMENT_PROVIDER`, the key pair and the secret in the
  Render dashboard only (the product refuses to offer online payment until all are set).
- Buy the domain; verified sending address; Resend webhook; Supabase sign-up mail; `EMAIL_FROM`
  (PRE-B-016, PRE-C-003). Confirm what `PRACTICE_MAIL_ENABLED` is in the dashboard (the code reads unset as off).
- Check that Cloudflare Web Analytics is off for the marketing project (an edge-injected script no test can see).
- Name a contact and a region code for the privacy page (PRE-C-006); settle the AI providers' terms for the
  plans in use (PRE-B-013). The privacy page says nothing about either until then.
- Press **Check now** for Groq and Gemini on Settings, AI status, once (PRE-B-014); no successful live call
  on the current models has ever been recorded.
- Set `SECURITY_CSP_MODE=enforce` on each Pages project once the deployed app has been exercised with the
  console open and shows no `Refused to ...` line.

## 7. How to resume

1. Read `README.md` here, then this note, then only the section file for the work in hand.
2. Take the next row of section 3 whose "Needs" is done; HON-1 and PAY-2 are the cheapest and the safest first.
3. One pull request at a time, from `origin/main`; wait for both required checks
   (`pytest — mock mode (Python 3.11)` and `migration apply — real Postgres 16`); squash-merge only when the
   pull request is current with `main`; close the ledger line in the same commit as the work.
