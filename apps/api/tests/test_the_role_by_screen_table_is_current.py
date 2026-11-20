"""POST-A-447, part 3: the role-by-screen table in the docs is generated from the menus and the permission table,
and a change to either that moves what a role is offered moves the document in the same commit.

`docs/architecture/12-what-each-role-is-offered.md` is what `scripts/role_by_screen.py` prints. The second test holds
the reader to what it claims: it reads every entry the panels declare (a nested parent such as GST under Deadlines
included), and it answers from `core/permissions.py` rather than from a copy of the matrix.
"""
import importlib.util
from pathlib import Path

API = Path(__file__).resolve().parents[1]
# The generator reads the browser's menus from here; built the way CI's browser-test finder recognises, so a change to
# apps/web alone still runs this test.
WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
_spec = importlib.util.spec_from_file_location("role_by_screen", API / "scripts" / "role_by_screen.py")
rbs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rbs)


def test_the_committed_table_is_what_the_code_says():
    assert rbs.WEB == WEB
    assert rbs.DOC.read_text() == rbs.build(), (
        "The role-by-screen table is out of date: run `python3 scripts/role_by_screen.py --write` in apps/api.")


def test_the_reader_reads_nested_entries_and_the_permission_table():
    text = rbs.build()
    # A parent whose children are nested inside it is still an entry of its own.
    assert "| GST | `/gst` |" in text and "| GSTR-1 | `/gst/gstr1` |" in text
    # A pair is answered from core/permissions.py: Retainers asks billing read, which only a Partner holds. (The example was
    # Fee Receivables until POST-A-532 moved that screen to the My practice menu, where the tile itself is the Partner's.)
    from core.permissions import PERMISSIONS, Role
    assert PERMISSIONS["billing"]["read"] == {Role.PARTNER}
    assert "| Retainers | `/accounting/retainer` | `billing` `read` | yes | - | - | - |" in text
    assert "| Earlier fee receivables | `/accounting/receivables` | the tile only | yes | - | - | - |" in text
    # The client workspace's Payroll section asks payroll read (POST-A-447), which an Executive does not hold.
    assert "| Payroll | `payroll` `read` | yes | yes | - | - |" in text
