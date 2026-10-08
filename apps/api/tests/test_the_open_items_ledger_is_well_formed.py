"""The open-items ledger (docs/open-items/) stays one line per item, with stable ids, and says nothing false about itself.

WHY THIS EXISTS

    On 2-7 October 2026 the audit, finding, "what is left" and plan documents (about 4 MB, none of them
    kept in step with the others) were replaced as the answer to "what is still open?" by six files of
    one-line items: before or after the demo, times three buckets of who must act. The point of the change is
    that a new session, or one that has just been compacted, can find everything still to do in ONE place.
    That only holds while the place stays well formed, so this test states the rules the ledger relies on
    rather than any particular item:

      * an item is exactly one line, `- **PRE-A-001** · `theme` · priority ...`, in the file its id belongs to
        (PRE-A in pre-demo-A-mine.md, POST-C in post-demo-C-yours.md, ...);
      * ids are unique across all six files and are never reused by a different item (the test cannot see
        history, so it checks only uniqueness; the README says never renumber);
      * every line names an allowed theme and priority and has a bold title;
      * an id cited in the README's lists or in decisions-and-strategy.md exists (closing an item without
        removing it from those lists leaves a dangling reference, which is how an index rots);
      * every before-the-demo item appears in the README's ordered checklist (a new pre-demo item that
        nobody put in the checklist is invisible to the person working through it);
      * the generated counts block in the README is current (`python3 scripts/open_items_counts.py`);
      * the ledger carries no secret-looking string and no model identifier, because the repository is
        public.

    It deliberately does NOT check an item's facts: that is what reading the code is for, and the README says
    each line was verified on a stated date and goes stale.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LEDGER = REPO / "docs" / "open-items"
SECTIONS = {
    "pre-demo-A-mine.md": "PRE-A",
    "pre-demo-B-ours.md": "PRE-B",
    "pre-demo-C-yours.md": "PRE-C",
    "post-demo-A-mine.md": "POST-A",
    "post-demo-B-ours.md": "POST-B",
    "post-demo-C-yours.md": "POST-C",
}
THEMES = {
    "gst-returns", "gst-einvoice-eway", "tds-tcs", "income-tax-itr", "payroll-statutory",
    "accounting-gl-reporting", "banking", "sales-purchase-docs", "inventory-fixed-assets", "ai",
    "security-access-rls", "platform-ops-ci-deploy", "frontend-ux", "marketing-commercial-legal",
    "filing-integrations-registrations", "schema-data-migrations", "docs-hygiene",
    "demo-and-onboarding", "dependencies", "other",
}
ITEM = re.compile(
    r"^- \*\*(?P<id>(?P<prefix>(?:PRE|POST)-[ABC])-\d{3})\*\* · `(?P<theme>[a-z\-]+)` · (?P<prio>high|normal|low)\b"
)
ANY_ID = re.compile(r"\b((?:PRE|POST)-[ABC]-\d{3})\b")
SECRETISH = re.compile(
    r"eyJ[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|whsec_[A-Za-z0-9]{10,}"
    r"|\b(?:password|passwd|secret|token)\s*[:=]\s*[\"']?[A-Za-z0-9/+_-]{12,}",
    re.I,
)
MODEL_NAME = re.compile(r"claude-(?:opus|sonnet|haiku|fable)|\b(?:Opus|Sonnet|Haiku|Fable)\s*[0-9]", re.I)


def _lines(name: str):
    return (LEDGER / name).read_text(encoding="utf-8").splitlines()


def _items():
    """Yield (file, line_no, line, match-or-None) for every bullet in the section files."""
    for name in SECTIONS:
        for n, line in enumerate(_lines(name), 1):
            if line.startswith("- "):
                yield name, n, line, ITEM.match(line)


def test_the_ledger_has_its_files():
    for name in [*SECTIONS, "README.md", "decisions-and-strategy.md", "checked-closed.md", "deletion-plan.md"]:
        assert (LEDGER / name).is_file(), f"docs/open-items/{name} is missing"


def test_every_bullet_in_a_section_file_is_a_well_formed_item_in_the_right_file():
    bad = []
    seen_any = 0
    for name, n, line, m in _items():
        seen_any += 1
        if not m:
            bad.append(f"{name}:{n} is not `- **ID** · `theme` · priority ...`: {line[:90]}")
            continue
        if m["prefix"] != SECTIONS[name]:
            bad.append(f"{name}:{n} carries id {m['id']} but this file holds {SECTIONS[name]}-NNN")
        if m["theme"] not in THEMES:
            bad.append(f"{name}:{n} {m['id']} has unknown theme `{m['theme']}`")
        if " — **" not in line or ".** " not in line:
            bad.append(f"{name}:{n} {m['id']} has no bold `Title.` after the em dash")
    assert seen_any > 0, "no items found at all: the collector is broken"
    assert not bad, "\n".join(bad[:25])


def test_ids_are_unique_across_the_six_files():
    ids = {}
    dup = []
    for name, n, _line, m in _items():
        if not m:
            continue
        if m["id"] in ids:
            dup.append(f"{m['id']} in {name}:{n} and {ids[m['id']]}")
        ids[m["id"]] = f"{name}:{n}"
    assert not dup, "\n".join(dup)


def _all_ids() -> set[str]:
    return {m["id"] for _, _, _, m in _items() if m}


def test_no_list_cites_an_id_that_no_longer_exists():
    ids = _all_ids()
    dangling = []
    for name in ("README.md", "decisions-and-strategy.md"):
        text = (LEDGER / name).read_text(encoding="utf-8")
        for cited in sorted(set(ANY_ID.findall(text))):
            if cited not in ids:
                dangling.append(f"{name} cites {cited}, which is not in any section file (closed? remove it from the list)")
    assert not dangling, "\n".join(dangling)


def test_every_pre_demo_item_is_in_the_readmes_ordered_checklist():
    readme = (LEDGER / "README.md").read_text(encoding="utf-8")
    cited = set(ANY_ID.findall(readme))
    missing = sorted(i for i in _all_ids() if i.startswith("PRE-") and i not in cited)
    assert not missing, f"pre-demo items missing from the README checklist: {missing}"


def test_the_generated_counts_in_the_readme_are_current():
    spec = importlib.util.spec_from_file_location("open_items_counts", REPO / "scripts" / "open_items_counts.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    readme = (LEDGER / "README.md").read_text(encoding="utf-8")
    assert mod.apply(readme, mod.render_block(LEDGER)) == readme, (
        "docs/open-items/README.md counts are out of date: run python3 scripts/open_items_counts.py"
    )


def test_the_ledger_is_safe_to_publish():
    problems = []
    for path in sorted(LEDGER.glob("*.md")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for rx, what in ((SECRETISH, "secret-looking string"), (MODEL_NAME, "model identifier")):
                m = rx.search(line)
                if m:
                    problems.append(f"{path.name}:{n} {what}: {m.group(0)[:30]}")
    assert not problems, "\n".join(problems[:20])
