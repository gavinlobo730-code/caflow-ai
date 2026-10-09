#!/usr/bin/env python3
"""Keep the counts in docs/open-items/README.md true.

The open-items ledger (docs/open-items/) is six files of one-line items. The README states how many items each
file holds, so a person closing an item has two things to do: delete its line, and make the counts agree. This
script does the second. Run it after closing or adding an item:

    python3 scripts/open_items_counts.py            # rewrite the block in README.md
    python3 scripts/open_items_counts.py --check    # exit 1 if the block is out of date (the test does this)

Only the text between the two marker comments is generated; everything else in the README is prose.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "open-items"
START = "<!-- counts:start -->"
END = "<!-- counts:end -->"

SECTIONS = [
    ("pre-demo-A-mine.md", "before the demo: Claude can do alone"),
    ("pre-demo-B-ours.md", "before the demo: owner decides, or a live session"),
    ("pre-demo-C-yours.md", "before the demo: only the owner can do"),
    ("post-demo-A-mine.md", "after the demo: Claude can do alone"),
    ("post-demo-B-ours.md", "after the demo: owner decides first, then Claude builds"),
    ("post-demo-C-yours.md", "after the demo: only the owner or outsiders can do"),
]
OTHERS = [
    ("decisions-and-strategy.md", "the 15 owner decisions with the items each gates, what is parked until after the demo, the 30 Sep strategy and staged roadmap"),
    ("checked-closed.md", "what the sweep tested and found already done, answered or moot, with evidence, so nobody reopens it"),
    ("deletion-plan.md", "which audit and plan documents can be deleted, which must stay and why, and what must be done first"),
    ("coming-soon.md", "the register of every statement a person is shown that something is planned, coming or not switched on: where, its exact words, what gates it, who acts and the ledger id"),
]

ITEM = re.compile(r"^- \*\*(?P<id>(?:PRE|POST)-[ABC]-\d{3})\*\* · `(?P<theme>[a-z\-]+)` · (?P<prio>high|normal|low)\b")


def read_items(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- **"):
            yield line, ITEM.match(line)


def render_block(ledger: Path = LEDGER) -> str:
    rows, total, pre, high, unsure = [], 0, 0, 0, 0
    for name, desc in SECTIONS:
        n = 0
        for line, m in read_items(ledger / name):
            n += 1
            if m and m["prio"] == "high" and name.startswith("post-"):
                high += 1
            if " · UNSURE" in line.split(" — **", 1)[0]:
                unsure += 1
        total += n
        pre += n if name.startswith("pre-") else 0
        rows.append(f"| [{name}]({name}) | {n} | {desc} |")
    for name, desc in OTHERS:
        rows.append(f"| [{name}]({name}) | — | {desc} |")
    lines = [START, "", "| file | items | what it holds |", "|---|---|---|", *rows, "",
             f"**{total} open items** ({pre} before the demo, {total - pre} after); {high} after-demo items are `high` priority; {unsure} are UNSURE.",
             "", END]
    return "\n".join(lines)


def apply(readme_text: str, block: str) -> str:
    if START not in readme_text or END not in readme_text:
        raise SystemExit(f"README.md must contain {START} and {END}")
    head, rest = readme_text.split(START, 1)
    _, tail = rest.split(END, 1)
    return head + block + tail


def main(argv: list[str]) -> int:
    readme = LEDGER / "README.md"
    text = readme.read_text(encoding="utf-8")
    new = apply(text, render_block())
    if "--check" in argv:
        if new != text:
            print("docs/open-items/README.md counts are out of date: run python3 scripts/open_items_counts.py")
            return 1
        return 0
    if new != text:
        readme.write_text(new, encoding="utf-8")
        print("README.md counts updated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
