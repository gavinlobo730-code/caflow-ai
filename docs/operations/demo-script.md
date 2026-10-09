# Demo script — what to say, what to show, what to steer round

> **DRAFTED, NOT REHEARSED.** Nobody has followed this script with a practising CA, no step has been timed,
> and no demo date exists (PRE-C-001). The rehearsal record in section 10 is empty, and this warning stays
> until that record holds a date. Everything the run of show opens exists on `main` today. Sections 6 and 7
> name the screens a demo is likely to reach that say a feature is planned, not built or not switched on, each
> next to its row in the register of such wording (`docs/open-items/coming-soon.md`). **That list is not
> exhaustive**: the register does not yet find every such sentence, and the public marketing site is outside
> this script. Treat any other screen, or anything a CA read on the public site, that says a feature is planned,
> not built, not available or not switched on as unrehearsed. The script describes the product as it stands and
> is edited when a screen it names changes.

> **Public repository.** No login, address, phone number or key belongs in this file. The owner's own
> accounts and the seeded firm's sign-in are held where the owner keeps them.

The script has one job above the others: when a CA asks whether this can run their practice, the answer is
the sentence in section 2, said the same way every time, and it is the same position the product itself
prints on every filing screen. `apps/api/tests/test_the_demo_script_gives_the_filing_answer_in_the_products_voice.py`
holds the sentence, the long form, the forbidden words, the ids this file cites and every screen it names.

## 1. Before you start

1. Wake the server. It sleeps when idle and a cold start can take close to a minute (PRE-C-005 has the
   command and the reasoning). Open the product and sign in at least two minutes before anyone arrives, load
   one data screen and keep that signed-in tab open. If a screen says «The server is waking up. The first
   screen of the day can take up to a minute.», say that this is exactly what it is, wait, and use Retry once
   it appears.
2. The firm. The run of show uses the seeded practice (Sharma & Associates, Mumbai, financial year 2025-26),
   written by `apps/api/scripts/seed_demo_firm.py`. That script has not been run against the deployment yet
   (PRE-B-001), so until it has there is no firm to demonstrate on. After seeding, open **Verify Books**, the
   **GSTR-1** and **GSTR-3B** tabs and the client's overview, and stop if anything is empty or red. Stay on
   FY 2025-26, the year the product has verified (section 6).
3. Sign-in. A Partner account with its authenticator code to hand: a second factor is required in
   production (PRE-C-002).
4. The AI. Press **Check now** for Groq and for Gemini on Settings, AI status, once before anyone arrives
   (PRE-B-014). No successful live call on the current models has ever been recorded, and the assistant and
   the invoice reader depend on it. If either fails, take the assistant and the invoice reader off the run.
5. Mail. Do not send an engagement letter, invoice, statement, reminder or sign-up link live: mail cannot
   reach a client until a verified sending address exists (PRE-B-016, PRE-C-003). Show the screen and the PDF,
   and say what the button does.
6. A GSTR-2B file. The 2B step needs the portal's GSTR-2B JSON for a client and month whose purchase bills
   are in the product. The seed does not write one and the repository holds none, and no open item holds
   that gap yet. Without one, show the **GSTR-2B Recon** tab as it opens and say what a file would do.
7. The employee portal. Before the day, give one seeded employee access under Payroll, People
   (**Payslip portal**, **Give access**), copy the activation link the dialog shows and open it once in a
   private window. The seed does not do this, because it is that employee's own sign-in. Nobody has yet
   walked either portal end to end (PRE-B-009).
8. Leave Pay Now alone in the client portal and on an invoice (section 6).

## 2. The one sentence

> PracticeSync prepares your returns and books; you file on the portal. Direct submission is planned and depends on registrations we do not yet hold.

Say it as written, whenever the question is some form of "does it file", "can I use this for my practice
tomorrow" or "are you a registered provider". It is the owner's wording (decision of 9 October 2026), it is
consistent with decision D17 (stay prepare-only) and it says the same thing as the banner on every filing
walk-through. Do not add a yes or a no to it. Do not soften "planned" and do not sharpen it. Do not describe
any registration as being in motion, whatever has been started since this was written: the sentence says what
is held and what is not, and that is all (section 8).

## 3. If pressed

The long form is the product's own filing position, the sentence its filing screens print. Read it out if a
CA wants the whole answer:

> PracticeSync prepares the return and you submit it on the authority's own portal. Direct submission from within PracticeSync is planned: it requires authorisation from GSTN, the Income Tax Department or NIC, which those bodies grant only to registered providers.

Then the detail, only for the question actually asked and one at a time:

- Which registrations. GST returns go through a GST Suvidha Provider (GSP), income tax returns through an
  e-Return Intermediary (ERI), and e-invoice and e-way bill through credentials from NIC. PracticeSync holds
  none of them today. `docs/compliance/07-getting-permission-to-file.md` is the plan; it says itself that
  it could not read the primary sources, so do not quote a cost or a timeline from it.
- Where no registration is the gate. TDS statements, the PF return file, ESI contributions and MCA forms have
  no filing interface for software to be granted, so for these "you file on the portal" stays true after the
  registrations above. The PF and ESI walk-throughs say so on screen
  (`apps/api/services/filing_demo/pf_ecr.py`, `apps/api/services/filing_demo/esi.py`). Do not let the
  word "registrations" in the sentence be read as covering them.
- "Prepares ... books". The books are kept in PracticeSync, and the returns are computed from that ledger.
  "Prepares" is about the returns: nothing is sent to a government system. Nothing is ever emailed to a
  client's customers automatically either; a person presses Send (D27).
- What "planned" is not. It is not a date and not a promise of a timetable. If asked when, say that it
  depends on bodies that grant registrations on their own schedule, and that you will not guess.
- The two outputs software can finish. E-invoice and e-way bill are the only statutory outputs software can
  complete end to end, because the portal signs and no taxpayer signature is needed. PracticeSync prepares
  them and does not transmit them today.

## 4. The run of show — thirty minutes

The order follows what the marketing site's /demo page promises a CA. In this section, and in section 1, a
word in bold type is always a label on a screen and nothing else is set in bold; a test finds each label in
the product's source. Cut from the bottom if time is short: first the Schedule III page in row 4, then row 6.

| Min | The /demo page promises | Screen | Click | Say |
|---|---|---|---|---|
| 8 | «A client's GST month» | `/clients/<id>/compliance/gst` | **GSTR-1**, **Compute from Books**, **Validate**, **CA Approve**; then **GSTR-3B**, **Compute from Books**; then **GSTR-2B Recon** | The return is computed from the books, not typed in, and the findings panel names what is missing before anything is filed. A 2B file says which month and whose it is. The answer has four outcomes: matched, amount mismatch, supplier has not filed, and no bill in the books. The last two say whom to chase, the supplier or the document. |
| 6 | «A bank statement, so you can watch it become vouchers you review rather than type» | `/clients/<id>/bank` | **Entries**, **Import statement**, **Pass**; then **Reconcile** | A statement line becomes a receipt, a payment or a contra. The machine proposes the coding and a person passes it. Use the lines the seed left to pass; import a file only if none is left. |
| 6 | «A payroll run with PF, ESI and §192 TDS, and the employee portal your client's staff would use» | `/clients/<id>/payroll`, then `/portal/employee` | **Inputs**, **Register**, **Release**, **Outputs** | PF, ESI and the §192 withholding are worked out per employee. Open a month that ended before 21 November 2025 (section 6). Then the employee's own sign-in: payslips, the tax declaration and the §192 projection. |
| 4 | «A trial balance, and the Schedule III statements that come out the other end» | `/clients/<id>/accounting`, then `/accounting/schedule-iii` | **Trial Balance**, **Balance Sheet**, **Verify Books** | The trial balance foots, the balance sheet is the Schedule III presentation read from the same ledger, and Verify Books names anything that does not add up. |
| 3 | «What it does, what it does not» | `/clients/<id>/compliance/gst` | On the approved GSTR-1 row, **File (demo)**; then **Mark as filed** | Read the walk-through's banner aloud: «Demonstration — no return is being filed». It walks the portal's real sequence and transmits nothing. Say the sentence from section 2 here. Then show the **Mark as filed** dialog: you file on the portal, record the acknowledgement here, and the period locks. Cancel it unless this is the last thing you will do on that client, because recording the filing really locks the period. |
| 3 | «what moving across from Tally or ClearTax would actually involve» | `/migration`, then `/clients/<id>/accounting`, then `/accounting/trial-balance-import` | **New Import**; then **Opening Balances** | Customer and vendor masters come across from a Tally XML export, with a preview before anything is written. Ledgers, journals and balances are read and checked but not written. Opening balances go in bill by bill with their dates, or as a trial balance. PracticeSync runs alongside Tally: keep Tally as long as you like, and nothing is exported back to it. |

## 5. Questions that will come

- "Does it file?" and "Can I use this for my practice tomorrow?" Section 2, word for word.
- "Where is our data?" The database is in Supabase's Mumbai region (the owner confirms the region in the
  dashboard: PRE-C-006). The server that does the computing runs in Singapore. The AI features send content
  to AI providers outside India: Groq for text and for PDFs with a text layer, Google Gemini for photographs
  and scanned pages. In a chat, anything shaped like a PAN or a GSTIN is replaced before the request leaves;
  names typed into a chat, and documents sent for reading, go as they are.
- "Is our clients' data used to train a model?" "I cannot say: we have not confirmed the providers' terms for
  the plans we use, and I will not say either way until we have" (PRE-B-013).
- "Can it connect to our bank?" "A statement comes in as an uploaded file, and the machine proposes the
  coding. There is no live bank feed."
- "Does it replace Tally?" "It runs alongside Tally on one ledger. Keep both as long as you like."

## 6. Avoid or explain

The Decision column is a proposal that the owner overwrites in the cell (PRE-B-004). **avoid** means do not
open it and do not volunteer it; if a CA opens it, say the line. **explain** means open it if asked and say
the line. A row whose register row is marked unsafe (the screen's words overstate what it does) is always
avoid: a screen that overstates is steered round, not explained away.

| Decision | Screen or claim | The line to say if it comes up | Held by |
|---|---|---|---|
| avoid | Anything dated FY 2026-27: income-tax, TDS and payroll-withholding figures, the assistant's statutory brief, a payroll run for that year | "Last year's rates are carried forward for FY 2026-27 and the screen says they are not yet verified. The seeded books are FY 2025-26, which is." | PRE-B-004 |
| avoid | A payroll month that ended on or after 21 November 2025: the PF wage base | "From that date PF follows the wage definition in the Code on Social Security. That reading is corroborated from secondary sources only and is not yet verified, so a CA computing on basic plus DA will see different figures." | PRE-B-004 |
| avoid | The ECR file under Payroll, File | "The file is produced from the payslips. Its line layout has not been checked against an EPFO sample, so I will not call it ready to upload." | PRE-B-004 |
| avoid | Importing a real AIS | "The importer's field names have not been checked against a real portal download." | PRE-B-004 |
| avoid | Uploading a CA's own Form 26AS | "It reads tab or pipe separated text and refuses anything else in words naming the lines it skipped. It has not been run on a real file from the portal." | PRE-B-004 |
| avoid | `/practice/profitability` on the seeded firm | "On this data profit equals revenue: revenue counts every fee invoice including drafts and cancelled ones, and the cost of timer-started time entries is zero." | PRE-B-004 |
| avoid | Saying the GSTR-1 or GSTR-3B file was accepted by the department's offline tool | "I will not say that. No accepted-upload record exists." | PRE-B-004 |
| explain | The IMS, DSC and MCA-signatory sentences in the filing walk-throughs | "They are worded as reported in the department's own notes and say to confirm on the portal. Treat them as a guide to the sequence, not as the rule." | PRE-B-004 |
| explain | Payroll for a state other than Maharashtra, Tamil Nadu, Karnataka or West Bengal | "Four states' professional-tax slabs are modelled. For any other state the run reports a gap instead of deducting. The seeded employees are in Mumbai, so it will not show unless you ask." | PRE-B-004 |
| avoid | The s.89 relief worksheet for arrears before FY 2025-26 | "The relief compares years at their own rates, and the rate tables hold only FY 2025-26 and 2026-27, so earlier years are refused." | PRE-B-004 |
| explain | "Nothing files, so it is not finished" | The sentence in section 2, and the banner on the walk-through. | PRE-B-004, COMING-010 |
| explain | The File (demo) walk-throughs for GSTR-1, GSTR-3B, GSTR-9, TDS, ITR and MCA, and what each says changes when filing is real | "Nothing is transmitted. At the end the screen says which registration would change it, and that the signature stays the taxpayer's." | COMING-010, COMING-011, COMING-012, COMING-013, COMING-014, COMING-015, COMING-018 |
| avoid | The last stage of the PF and ESI walk-throughs | "The file is produced today. That paragraph is worded as if it were not." | COMING-016, COMING-017 |
| avoid | Pay Now in the client portal, the payment link on an invoice and the Pay Now button in an emailed invoice | "Online payment is not switched on yet: it needs a payment gateway account that the owner holds. I will not click it." | COMING-001, PRE-B-002 |
| avoid | Settings, Scheduled Reports | "A schedule can be saved, but nothing sends it yet." | COMING-002, PRE-B-002 |
| explain | Work, Workflows | The screen opens empty and says «Templates for common firm workflows are planned; none exist to run yet». | COMING-003, PRE-B-002 |
| explain | A client portal that cannot receive a file | "The portal shows what you have asked a client for and says plainly that uploading is not available yet." | COMING-004 |
| explain | Mail that does not leave: letters, invoices, statements, reminders, staff notices and sign-up links | "Mail needs a verified sending address that the owner has not set up yet, and the screens say when email is switched off." | COMING-005, COMING-006, PRE-B-016 |
| explain | The assistant, the copilot and invoice reading when a key is not set | "Without its key the screen says the assistant is not configured and names the setting." | COMING-007, PRE-B-014 |
| explain | Settings, Multi-currency, and books kept in a currency other than rupees | "Rupee books that deal in foreign currency are supported and the platform setting is off for this deployment. Keeping the books themselves in another currency is not built." | COMING-008, COMING-009 |
| avoid | The "Viewed" badge on the invoice drawer | "No open-tracking exists. The badge does nothing." | COMING-019 |
| explain | Edges a CA reaches only by looking: an LLP's Form 11 and Form 8, TDS on a foreign-currency receipt, a GST rate with a multi-account bank split, registrations that file other returns, s.195 rates for a firm or co-operative payee, Form 3CD clauses 33, 35 and 40, a professional-tax challan | "Each of these refuses, or leaves the work to the CA, in words on the screen. None is on the run of show." | COMING-020, COMING-021, COMING-022, COMING-023, COMING-024, COMING-025, COMING-026 |
| explain | Settings, Email Templates | "Three of the four templates say they are not applied yet, because no mail uses the wording written there." | COMING-027 |
| explain | The Tally import | "It brings customer and vendor masters across and nothing else. Ledgers, journals and balances are read and checked, not written." | COMING-028 |

## 7. Switched off until the owner supplies something

Each of these is built and shown, and is held off by something only the owner can supply. Every row is a
`switch` row in the register; the register names the setting.

| What is off | What it means on the day | Held by |
|---|---|---|
| Mail: a verified sending address and domain | Letters, invoices, statements, reminders and staff notices cannot reach anyone, and sign-up and invitation mail has its own limits. Show the screens and the PDFs; do not send. | COMING-005, COMING-006, PRE-B-016, PRE-C-003 |
| Online payment: a payment gateway account | Pay Now cannot take a payment. Do not click it. | COMING-001, PRE-B-002 |
| The AI keys, and the providers' terms | The assistant and image reading answer only once a key is set and the status screen has been pressed; what the providers do with content is not stated, on purpose. | COMING-007, PRE-B-013, PRE-B-014 |
| The multi-currency platform setting | The settings screen shows it off and does not offer it. | COMING-008 |

Registrations are not a switch and are not in this table. A GSP, an ERI and NIC credentials are the owner's
to start, after the demo (D17), and until they are held the answer is the sentence in section 2.

## 8. Never say

The first nine lines are the product's own list of phrases that claim a regulatory standing PracticeSync does
not have (`apps/api/domain/filing_posture.py`, FORBIDDEN_REGISTRATION_CLAIMS), held once. A test fails the day
a phrase is added there and not here.

```
in progress
under way
underway
applied for
pending approval
awaiting approval
registered gsp
we are registered
coming soon
replaces Tally
files for you
accepted by GSTN
encrypted
trained on
```

Why the others are on the list:

- The first nine would claim a regulatory standing PracticeSync does not have (D17). Direct submission is
  planned, and that is the only word for it.
- "Replaces Tally": it runs alongside Tally on one ledger.
- "Files for you", and anything like "filed through PracticeSync": nothing is transmitted to a government
  portal.
- "Accepted by GSTN", and "the offline tool took it": no accepted-upload record exists.
- "Encrypted", and the words near it (secure, compliant, certified): nothing in the repository cites or
  checks the claim.
- "Trained on", and "not trained on": the AI providers' terms have not been confirmed (PRE-B-013).

## 9. After the demo

- Write down, in the CA's words, every question this script did not answer.
- Write down every screen that failed. A server error ends with a reference code; keep it, and
  `docs/operations/finding-one-request.md` says what to do with it.
- Ask which states their payroll staff are in (PRE-B-004), how many CAs attended and whether any wants to try
  their own client's data (PRE-C-001).
- Write down which registrations they asked about and whether the sentence in section 2 was enough or was
  challenged.
- Overwrite the Decision column in section 6 with what the owner decides, and edit this file for anything that
  changed.
- Record the session in section 10 with its date, and remove the warning at the top of this file only when
  every row there holds a date.

## 10. Rehearsal record

| Pass | Result | Date | Notes |
|---|---|---|---|
| R1. A read-through with the console open (PRE-B-008) | not run | | |
| R2. A timed run against the seeded firm (PRE-B-001) | not run | | |
