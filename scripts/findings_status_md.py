#!/usr/bin/env python3
"""Render docs/audits/findings-status.md from findings-status.json.

The JSON is the record — it is amended in the same commit that closes a
finding. This turns it into the page somebody reads when they ask "how much is
left". Regenerate after every amendment:

    python3 scripts/findings_status_md.py
"""
import glob
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs/audits/findings-status.json"
OUT = ROOT / "docs/audits/findings-status.md"
FINDINGS = ROOT / "docs/audits/2026-09-07-findings"

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def titles() -> dict[str, tuple[str, str]]:
    """(severity, title) per finding id, from the 7 September audit files.

    `corrected_severity` wins where the adversarial pass set one — the raw
    severity is the reader's first impression, the corrected one survived a
    check (docs/audits/2026-09-07-findings/README.md).
    """
    out = {}
    for path in glob.glob(str(FINDINGS / "*.json")):
        if "verification" in path:
            continue
        for x in json.load(open(path))["findings"]:
            v = x.get("verification") or {}
            out[x["id"]] = (v.get("corrected_severity") or x.get("severity") or "?",
                            x["title"])
    return out


def main() -> None:
    led = json.loads(LEDGER.read_text())["findings"]
    known = titles()

    def rows(status):
        out = []
        for fid, r in led.items():
            if r["status"] != status:
                continue
            sev, title = known.get(fid, (r.get("severity", "?"), r.get("title", "")))
            out.append((sev, fid, title, r))
        return sorted(out, key=lambda r: (SEVERITY_ORDER.get(r[0], 9), r[1]))

    def table(status):
        rs = rows(status)
        if not rs:
            return "_none_\n"
        return ("| severity | finding | what it is |\n|---|---|---|\n"
                + "".join(f"| {s} | **{fid}** | {t[:96]} |\n" for s, fid, t, _ in rs))

    def blockers():
        rs = [r for r in rows("open") if r[3].get("needs")]
        return ("| finding | what actually blocks it |\n|---|---|\n"
                + "".join(f"| **{fid}** | {r['needs']} |\n" for _, fid, _, r in rs))

    c = {}
    for v in led.values():
        c[v["status"]] = c.get(v["status"], 0) + 1
    left = c.get("open", 0) + c.get("partial", 0) + c.get("unverified", 0)

    OUT.write_text(f"""# Where the 278 findings stand

Generated from `findings-status.json`. That file is the record; this one is it,
readable. Regenerate with `python3 scripts/findings_status_md.py`.

## The number

| state | count | what it means |
|---|---|---|
| closed | **{c.get('closed',0)}** | re-read against the code. The defect is gone. |
| closed_by_commit | **{c.get('closed_by_commit',0)}** | named in a merged commit on `main` **and** in an in-code comment saying what it closed. Two independent traces; not a re-read. |
| closed_by_commit_only | **{c.get('closed_by_commit_only',0)}** | named in a commit and nowhere else. The weakest state here — read these before quoting them as done. |
| partial | **{c.get('partial',0)}** | part of the finding is answered, part is not. Each says which. |
| open | **{c.get('open',0)}** | re-read and still true. |
| unverified | **{c.get('unverified',0)}** | a probe was inconclusive. Treat as unknown, **not** as open. |
| not a defect as stated | **{c.get('not_a_defect_as_stated',0)}** | the premise is false, or the suggested fix would be worse than the defect. |
| deferred to the redesign | **{c.get('deferred_to_the_redesign',0)}** | a navigation complaint the module hub answers. |
| **total** | **{len(led)}** | |

**The work left is about {left} items — {c.get('open',0)} open, {c.get('partial',0)} partial,
{c.get('unverified',0)} unverified — not 254.** The audit documents were never amended as
tranches landed, so they still list findings fixed weeks ago.

**And of the {c.get('open',0)} open, most are not code problems.** Nearly every one needs a
migration; a handful need a statutory document a person has to read.

## Open

{table('open')}
### What actually blocks each of them

{blockers()}
## Partial

{table('partial')}
## Unverified — a probe was inconclusive

These need a code read before they can be scheduled. Do NOT treat them as open.

{table('unverified')}
## Not a defect as stated

{table('not_a_defect_as_stated')}
## Deferred to the redesign

{table('deferred_to_the_redesign')}
## Closed by a commit, with nothing in the code naming them

The weakest evidence in this file. 88% of the commit-closed findings carry an
in-code comment naming them and saying what they closed; these do not, so a
promotion to `closed` should start here.

{table('closed_by_commit_only')}
## Closed by a code read

{table('closed')}
---

## Why this file exists

`docs/audits/2026-09-11-the-verification-pass.md` measured the backlog ~10%
stale. Five days later `docs/audits/2026-09-12-the-probe-pass/` measured the
same backlog **38-59% stale by subsystem**, because five tranches had landed
and nothing re-scored. A hand-check on 12 September found nineteen more.

A status only ever written by an audit is wrong by the time it is read. This
one is amended in the same commit that closes a finding.
""")
    print(f"wrote {OUT} — {len(led)} findings, {left} still to do")


if __name__ == "__main__":
    main()
