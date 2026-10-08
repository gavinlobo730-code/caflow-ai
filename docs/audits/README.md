# docs/audits was deleted on 8 October 2026

The audit, finding and plan snapshots that lived here (the 2026-07 to 2026-09 audits, `findings-status.json` and `.md`,
the 278 finding JSON files, the 2026-09-07 market research, the probe pass, the phase plans and the question files)
were deleted with the owner's approval. They were dated snapshots, each already stale, and what was still open in them
is a one-line item in [`docs/open-items/`](../open-items/README.md); what they proved closed is in
[`docs/open-items/checked-closed.md`](../open-items/checked-closed.md).

Nothing is lost. Every file is in git exactly as it stood at merge commit `315e6a1980053c5db5e00646d16624d48e358907`:

    git show 315e6a19:docs/audits/<file>
    git ls-tree -r --name-only 315e6a19 docs/audits        # the full list

A source comment, a test docstring or a document that names `docs/audits/...` is a historical reference to one of those
files. See [`docs/open-items/deletion-plan.md`](../open-items/deletion-plan.md) for what else was deleted and what was kept.
