# Emergency mode, and what the one run of it taught

Written on 18 November 2026 (IST), at the owner's request: the powers he gave for the run of 16 to 18 November are kept as an **emergency mode**, and everything else is done **normally**, under the standing instructions in `CLAUDE.md`. This file says what the mode is, what it is not, and what it taught about saving time without it.

## 1. Normal mode and emergency mode

- **Normal mode is the default.** It is the standing instructions at the top of `CLAUDE.md`: the work is done directly, sub-agents are for narrow research or the review of one diff (at most three at a time, a task needing more than five agents is costed to the owner first), at most three pull requests are open and they merge one at a time, closing a pull request and pushing a tag need the owner's go-ahead, and low credits are said plainly, not spent through.
- **Emergency mode is the owner's to switch on, in words, and a session never starts it by itself.** It begins when the owner says so ("emergency" or an equivalent, naming the deadline) and ends when he says so or when the deadline he named passes. A session that thinks an emergency has come says so and asks; it does not assume the powers. Nothing in this file is a standing permission.

## 2. What emergency mode allowed, as used on 16 to 18 November 2026

The deadline was the owner's, Thursday night 19 November 2026. His words were, in substance: use as many credits as you want, raise the caps as far as is needed, push to new branches, combine the pull requests and close the old ones as fast as you can without any loss of correctness, do whatever you judge best, and not even one mistake. In practice that meant:

- Many cloud builders at once, in four waves of five to twelve (C, D, E and F), each in its own session and branch, instead of at most three sub-agents.
- Credits spent without a per-batch estimate, including independent review workflows over a whole batch, two reviewers per batch and two skeptics per finding.
- More than three pull requests prepared at once, several branches combined into one "train" pull request, and the superseded pull requests closed.
- Each train merged by the session without asking, when both required checks were green and the branch was current with `main`, including through the night.
- An hourly scheduled check-in that restarted builders stopped by a usage limit and merged what was ready.
- Technical choices (how to combine, in what order, which rule to build) taken without a question to the owner.

## 3. What emergency mode never allowed, and still does not

- **Skipping or weakening a test, an empty commit, or closing and reopening a pull request to restart a check.** A failing check is read and fixed.
- **Merging without both required checks green and the branch current with `main`.** And, by the owner's word of 18 November 2026: **no half-finished work is merged**; what is not done is written into the ledger in detail (`docs/open-items/checkpoint-2026-11-18.md` is the example).
- **Assuming a statutory rate, date, section or legal reading, and deciding money** (a paid plan, a gateway, counsel, a domain, pricing). Credits for the session's own work were allowed; the owner's money decisions were not.
- **Auto-submitting anything to a government portal.**
- **Applying a revoke migration before the code that stopped using the privilege has been live for about an hour** (the writers-first rule), whatever the hurry.

## 4. What it cost

- **The usage limit stopped the builders twice**: on 16 November (about 12:15 to 16:10 UTC, per the running notes) and in the early hours of 18 November (about 04:20 to 05:50 UTC). Each stop needed a "continue" message to every builder and a check that it had restarted.
- **The week's allowance was about 96% spent by midday on 18 November**, two and a half days in, with the weekly reset on Thursday 19 November at 04:30 IST. The mode is a loan against the following days.
- **Review costs about as much as the build.** A review that is cut short leaves a change merged with known gaps (the dialog sweep of 18 November) or a batch built and not merged (wave 2).

## 5. What it taught about time, and how to use it in normal mode

The clock is not typing; it is waiting. Each point below has its evidence, and none needs emergency powers.

1. **The checks are the clock.** On the 35-commit Train 6 pull request the backend suite took about 33 minutes and the real-database migration check about 48 minutes (04:01 to 04:34 and 04:48 UTC); the web checks took about 4. Merges are one at a time and each must be current with `main`, so *N* pull requests cost about *N* times 50 minutes. **Use fewer, fuller themed pull requests within the normal size rule (about ten hours-sized items), not many small ones.**
2. **A documents-only change still runs the whole backend suite**, because the ledger and design-record guards are backend tests (checked on the pull request that added `checkpoint-2026-11-18.md`: the backend suite and the migration check both ran). **Fold ledger and document edits into the code pull request they belong to, as the standing rule already says, and do not open a documents-only pull request unless the change is itself the work.**
3. **Prepare the next batch while the last one's checks run** (the standing "pace" rule) and build it **from `main`**. The wave-2 combination sits on the pre-squash head of Train 6 and has to be rebuilt, because a squash merge rewrites the base under any stacked work. Base a batch on `main`, or merge its base first.
4. **Conflicts gather in four ledger files** (the README counts, `checked-closed.md`, `new-findings.md`, `owner-list.md`). Generate the counts with `scripts/open_items_counts.py` and never by hand; put a batch's ledger edits in its own last commit so a conflict is one place; keep a failed cherry-pick out of a hand-made `git add -A` and `--continue` (a conflict marker reached a commit that way once and was caught before a push). The small resolver scripts that made combining fast lived in a session's scratch space and are gone with it: if combining many branches is to be routine, write them into `scripts/` first.
5. **A wide mechanical sweep needs a pilot slice before it grows.** The dialog rule found 153 ways out in 63 files at once and needed a second fix round and a second review, and still merged with gaps. Land the rule with a handful of files, review it, then widen it.
6. **Put the review's questions into the build.** The reviewers kept finding the neighbours of what a builder fixed (the sibling dialog, the sibling loop, the same defect on the customers page). Tell a builder to list every sibling of the pattern it fixes and to run the new rule's negative control, and the review has less to find.
7. **Writers first, then the revoke, in two merges at least an hour apart** (the standing rule): plan the pair as two trains from the start so the second is prepared while the first's checks run.
8. **Short reports and a written handoff.** A builder's final message should be five lines (what is pushed, what is verified, what is not, what is unfixed, what it covers). When a run stops, write the checkpoint at once: unpushed work in a reclaimed container is lost, and a note in a session is not read by the next one.
9. **Spend the review on the riskiest diff.** Of six batches, the one that merged with gaps was the largest mechanical one. Rank by the size of the change and by whether it touches money, tax or access, and review those first and twice.

## 6. A short checklist for normal mode

- Is the work one themed pull request of about the usual size, branched from `main`?
- Are its document and ledger edits in the same pull request, with counts regenerated by the script?
- Is the next batch being prepared while this one's checks run?
- If it is a sweep, has a small slice been reviewed first?
- Has every builder been told to list the siblings of what it fixes?
- Is anything unreviewed or half done about to be merged? If so, stop and write it down instead.
