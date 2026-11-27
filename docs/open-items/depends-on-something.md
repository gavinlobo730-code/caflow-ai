# Items that depend on something before they can be built

**What this is.** A Claude-alone item (lettered A in the ledger) can still be unbuildable today because it waits on something that is not Claude's: time passing, another item, a choice of the owner, or a registration. Those are listed here, so that the answer to "what can Claude build now, with no help?" is the Claude-alone items **minus** these (and minus the items marked `waits on owner`, `live session`, `held` and `UNSURE` in the ledger itself).

**How to keep it true.** One row per item, with what it waits on and what lifts it. Delete the row in the same commit that closes the item or lifts the dependency; `apps/api/tests/test_the_open_items_ledger_is_well_formed.py` fails a row whose id is no longer in the ledger. This list does not count anything and the ledger's counts do not read it. First written on 27 November 2026 (IST), from a read of the 44 Claude-alone items the ledger counted as needing no help.

| Item | Size | What it is | What it depends on | What lifts it |
|---|---|---|---|---|
| POST-A-025 | hours | Tighten the smoke-test timing budgets from a thirty-day reading | The thirty days of timing history. The nightly smoke walk keeps its timings for 90 days and the item says a first reading was possible from about 1 November 2026, so the data may already exist; **Claude said mid-December on 27 November and that was a guess that the ledger line contradicts** | Read the saved timings of the walk (a check, no one else needed); if there are fewer than thirty days of them, wait |
| POST-A-036 | days | Make the nightly smoke walk render a real client workspace in CI | Only if cutting the walk further is not enough: a longer time allowance for the nightly run, which is the owner's | Try cutting first; ask the owner only if that fails |
| POST-A-061 | days | Hold state-level turnover so the annual GST late-fee cap can be computed | A turnover figure per GST registration, which interacts with POST-B-091, the owner's decision on attributing each invoice, bill and note to a registration | The owner's decision on POST-B-091 |
| POST-A-051 | weeks | AI steps inside workflow automation, each ending in an approval | POST-A-204 (workflow triggers and actions that actually fire) first, and the owner choosing it as the next weeks-sized feature | POST-A-204 built; the owner's order |
| POST-A-199 | weeks | Task checklists, comments with mentions, attachments and a board view | The owner choosing which weeks-sized feature comes next | The owner's order |
| POST-A-200 | weeks | A workflow builder screen and the starter templates | POST-A-204 (its trigger picker may offer only triggers that fire), and the owner's order | POST-A-204 built; the owner's order |
| POST-A-201 | weeks | Client-facing proposals with price acceptance | The owner's order; its payment-link half also needs a payment-gateway registration, which is the owner's | The owner's order; the gateway registration for the payment-link half |
| POST-A-202 | weeks | Client e-acceptance for any document, not only engagement letters | The owner's order | The owner's order |
| POST-A-203 | weeks | Document folders, versions and open-ended document types | The owner's order | The owner's order |
| POST-A-204 | weeks | Make workflow triggers fire, delays wait, add email and document actions | The owner's order | The owner's order |
| POST-A-205 | weeks | A whole-firm data export in open formats | The owner's order | The owner's order |
| POST-A-206 | weeks | Turn each compliance obligation into staged work on the preparer's list | POST-A-199 (task checklists) first, and the owner's order | POST-A-199 built; the owner's order |
| POST-A-207 | weeks | Client organizers and questionnaires for data collection | The owner's order | The owner's order |
| POST-A-399 | weeks | The last cases of an emptied box on an edit saying "saved" while the old value stays | The remaining cases have no screen that edits them yet; each is converted when such a screen is built | A screen that edits that text is built |
