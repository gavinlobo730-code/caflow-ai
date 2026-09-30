"""ACCOUNTING-06 — the Migration Center says exactly what it writes.

The importer parses and validates six kinds of Tally item and writes exactly two
(`WRITTEN_ITEM_TYPES`). The screen's heading read "Import data from Tally —
Masters, Ledgers, Journals, Balances", so the sentence a CA read BEFORE starting
promised four things and delivered one; the honest sentence existed, but only
after the run.

The guard is on the PYTHON side — the Schedule III caption lesson: a test in
apps/web would assert the page against a copy of itself and pass whenever both
drifted together. This reads the browser's mirror and pins it to the importer's
own set, and reads the page to be sure the copy comes from the mirror.
"""
import re
from pathlib import Path

from domain.tally import migration_service as svc

WEB = Path(__file__).resolve().parents[2] / "web"
MIRROR = WEB / "lib" / "migration" / "writtenTypes.ts"
PAGE = WEB / "app" / "migration" / "page.tsx"


def _array(src: str, name: str) -> list[str]:
    m = re.search(rf"export const {name}\s*=\s*\[([^\]]*)\]", src)
    assert m, f"{name} not found in {MIRROR.name}"
    return re.findall(r'"([^"]+)"', m.group(1))


def test_the_mirror_exists():
    assert MIRROR.is_file(), "the browser's mirror of WRITTEN_ITEM_TYPES is gone"
    assert PAGE.is_file()


def test_the_browser_lists_exactly_the_kinds_the_importer_writes():
    src = MIRROR.read_text()
    assert set(_array(src, "WRITTEN_ITEM_TYPES")) == set(svc.WRITTEN_ITEM_TYPES)


def test_the_plural_import_types_are_the_ones_that_need_a_client():
    """The job's import types are plural and the items' singular; the plural
    spellings the mirror holds are the importer's own per-client masters."""
    src = MIRROR.read_text()
    assert set(_array(src, "WRITTEN_IMPORT_TYPES")) == set(svc._CLIENT_SCOPED_IMPORT_TYPES)
    # and each maps to a written kind — no plural name for something not written
    assert set(svc._CLIENT_SCOPED_IMPORT_TYPES.values()) == set(svc.WRITTEN_ITEM_TYPES)


def test_the_wizard_offers_exactly_the_types_the_api_documents():
    """The chips are the API's own vocabulary (`CreateJobRequest`'s description),
    or a chip would create a job the server does not recognise."""
    from routers.tally_migration import CreateJobRequest
    doc = CreateJobRequest.model_fields["import_types"].description
    documented = set(doc.split("|"))
    assert set(_array(MIRROR.read_text(), "ALL_IMPORT_TYPES")) == documented


def test_the_validator_builds_items_only_for_types_the_wizard_offers():
    """Premise: every type the validator reacts to is on the list, so a chip's
    'not written' note is a statement about every type the screen can select."""
    src = Path(svc.__file__).read_text()
    reacted = set(re.findall(r'"(\w+)" in import_types', src))
    assert reacted, "the validator's own branches were not found — the scan is vacuous"
    offered = set(_array(MIRROR.read_text(), "ALL_IMPORT_TYPES"))
    assert reacted <= offered, f"validator handles {reacted - offered} which no chip offers"
    # the two masters are handled in a loop rather than by name, so name them
    assert {"customers", "vendors"} <= offered


def test_the_page_takes_its_words_from_the_mirror_and_not_a_literal():
    code = PAGE.read_text()
    assert "migrationSubtitle()" in code
    assert "noClientOptionLabel()" in code
    assert "importTypeNote(" in code
    # the promise that was false
    assert "Masters, Ledgers, Journals, Balances" not in code
    assert "firm-level ledgers and journals" not in code


def test_the_page_no_longer_keeps_a_list_of_types_of_its_own():
    code = PAGE.read_text()
    assert not re.search(r'const IMPORT_TYPES\s*=\s*\[', code), \
        "a second list of import types on the page can drift from the mirror"
