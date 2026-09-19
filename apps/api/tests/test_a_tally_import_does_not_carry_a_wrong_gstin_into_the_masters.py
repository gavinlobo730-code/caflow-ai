"""
A Tally export's customer and vendor identifiers, and what reaches the masters.

THE DEFECT

    `validate_migration_data` tested a CUSTOMER's GSTIN against a private
    shape regex, appended a sentence to `validation_errors`, and left the
    item's `status` at "validated". Nothing reads `validation_errors`: the
    preview counts only items whose status is "failed", `execute_import`
    skips only those, and `_import_single_item` wrote `data.get("gstin")`
    straight into `customers.gstin` over PostgREST — the one door
    `models/parties.CustomerIn` does not stand in front of. The error was
    recorded and moved nothing.

    Three more things around it. The VENDOR branch asked nothing at all,
    and the vendor side is where a wrong GSTIN costs the client their input
    tax credit under CGST s.16(2)(aa). The regex was a shape, so every
    transposition inside the PAN passed it — which is the whole reason
    `domain/gst/gstin.problem_with` exists, and CLAUDE.md names the
    BULK-IMPORT paths as ones that must ask it. And the PAN was never looked
    at, although `domain/tds/tds_computer.has_pan` reads any non-empty value
    as a PAN on file, so a malformed one suppresses the s.206AA floor and
    s.40(a)(ia) disallows the whole expenditure for the under-deduction.

THE DECISIONS THIS PINS, BECAUSE EACH IS TEMPTING TO REVERSE

    The party IS imported and the job is NOT blocked. Marking the item
    "failed" would both drop a customer whose name, address and email are
    perfectly good AND disable the migration screen's import button on the
    whole export — one typo among two thousand legacy customers making a
    migration impossible for the clients who most need one.

    The identifier is WITHHELD rather than imported with a warning, because
    the direction of the error is not symmetric: an absent GSTIN makes the
    party B2C and their credit waits until somebody records the real number,
    while a well-formed WRONG one declares a stranger's registration on every
    invoice and is correctable only by a s.37(3) amendment inside a window.

    `tally_data` keeps what the export actually said. The withholding happens
    at the INSERT, so the record of what Tally held is not destroyed by the
    act of refusing to import it.
"""
import ast
import pathlib

import pytest

import domain.tally.migration_service as svc
from domain.tally import party_identifiers as pid

API = pathlib.Path(__file__).resolve().parent.parent
SERVICE = API / "domain" / "tally" / "migration_service.py"

# A real registration and its own PAN. The check digit is computed, not typed:
# see domain/gst/gstin.checksum_char.
GOOD_GSTIN = "27AAPFU0939F1ZV"
GOOD_PAN = "AAPFU0939F"
# The same GSTIN with two characters of the PAN swapped. Well-formed; not a
# registration. This is the value a shape regex cannot tell from the one above.
TRANSPOSED = "27AAPFU0399F1ZV"


def _ledger(name, gstin=None, pan=None):
    return {"tally_id": name, "name": name, "gstin": gstin, "pan": pan,
            "email": "", "address": "", "group": ""}


# ── the rule ────────────────────────────────────────────────────────────────

def test_a_real_gstin_and_pan_come_through_untouched():
    r = pid.resolve(GOOD_GSTIN, GOOD_PAN)
    assert r.gstin == GOOD_GSTIN
    assert r.pan == GOOD_PAN
    assert r.withheld == ()
    assert not r.anything_withheld


def test_a_transposed_gstin_is_withheld_and_named():
    r = pid.resolve(TRANSPOSED, GOOD_PAN)
    assert r.gstin is None, "a GSTIN that fails its own check digit reached the master"
    assert r.pan == GOOD_PAN, "the PAN is a separate identifier and was fine"
    assert len(r.withheld) == 1
    assert TRANSPOSED in r.withheld[0]


def test_the_shape_regex_the_importer_used_would_have_passed_it():
    """The premise. Without this the fix is untestable: it says the OLD check
    could not have caught the value the NEW one does."""
    import re
    old = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
    assert old.match(TRANSPOSED), "the transposed fixture is not a shape the old regex accepted"
    assert pid.resolve(TRANSPOSED, None).gstin is None


def test_a_malformed_pan_is_withheld_and_names_section_206aa():
    r = pid.resolve(None, "AAPFU0939")
    assert r.pan is None
    assert len(r.withheld) == 1
    assert "206AA" in r.withheld[0]


def test_the_two_reasons_are_not_interchangeable():
    """A party may be wrong about both, and what the CA does about each
    differs — one is a registration to re-key, the other a PAN to collect."""
    r = pid.resolve(TRANSPOSED, "AAPFU0939")
    assert len(r.withheld) == 2
    gst_reason, pan_reason = r.withheld
    assert "16(2)(aa)" in gst_reason and "206AA" not in gst_reason
    assert "206AA" in pan_reason and "16(2)(aa)" not in pan_reason


def test_a_blank_identifier_is_not_a_fault():
    """A party who is not registered has no GSTIN. Saying something about it
    would put every unregistered customer in a list of things to fix."""
    for blank in (None, "", "   "):
        r = pid.resolve(blank, blank)
        assert r.gstin is None and r.pan is None
        assert r.withheld == (), f"{blank!r} was reported as a problem"


def test_whitespace_and_case_are_rescued_not_refused():
    """Tally fields routinely carry trailing space and lower case. A party
    whose only fault is a stray space keeps their registration."""
    r = pid.resolve(f"  {GOOD_GSTIN.lower()} ", f" {GOOD_PAN.lower()}  ")
    assert r.gstin == GOOD_GSTIN
    assert r.pan == GOOD_PAN
    assert r.withheld == ()


def test_the_rule_reaches_no_database():
    """It is a rule, not a fetch: it must be callable from the preview and
    from the insert without either becoming a round trip."""
    src = (API / "domain" / "tally" / "party_identifiers.py").read_text()
    for forbidden in ("supabase", "_supabase", ".table(", "execute()"):
        assert forbidden not in src, f"party_identifiers mentions {forbidden}"


# ── the wiring: validation ──────────────────────────────────────────────────

@pytest.mark.parametrize("kind,key", [("customer", "customers"), ("vendor", "vendors")])
def test_both_party_kinds_are_asked(kind, key):
    """The vendor branch performed NO check at all, and the vendor side is
    where a wrong GSTIN costs the input tax credit."""
    items, errors = svc.validate_migration_data(
        {key: [_ledger("Acme", TRANSPOSED, GOOD_PAN)]}, [key]
    )
    assert len(items) == 1
    item = items[0]
    assert item["item_type"] == kind
    assert item["validation_errors"], f"{kind} GSTIN was not judged"
    assert TRANSPOSED in item["validation_errors"][0]


@pytest.mark.parametrize("key", ["customers", "vendors"])
def test_a_withheld_identifier_does_not_fail_the_item_or_block_the_job(key):
    """THE DECISION. `get_migration_preview`'s error_count counts failed
    items and the screen disables the import button on it, so failing here
    would refuse the whole export over one typed identifier."""
    items, errors = svc.validate_migration_data(
        {key: [_ledger("Acme", TRANSPOSED, "AAPFU0939")]}, [key]
    )
    assert items[0]["status"] == "validated"
    assert errors == [], "a withheld identifier was raised to a job-level error"


@pytest.mark.parametrize("key", ["customers", "vendors"])
def test_the_export_s_own_value_survives_in_tally_data(key):
    """Refusing to import a value must not destroy the record of what the
    export held — that is what the CA re-keys from."""
    items, _ = svc.validate_migration_data(
        {key: [_ledger("Acme", TRANSPOSED, GOOD_PAN)]}, [key]
    )
    assert items[0]["tally_data"]["gstin"] == TRANSPOSED


def test_a_clean_party_is_reported_clean():
    items, _ = svc.validate_migration_data(
        {"customers": [_ledger("Acme", GOOD_GSTIN, GOOD_PAN)]}, ["customers"]
    )
    assert items[0]["validation_errors"] == []


# ── the wiring: the insert ──────────────────────────────────────────────────

class _FakeTable:
    def __init__(self, sink, name):
        self._sink, self._name = sink, name

    def insert(self, row):
        self._sink.append((self._name, row))
        return self

    def execute(self):
        class R:
            data = [{"id": "new-id"}]
        return R()


class _FakeSb:
    def __init__(self):
        self.writes = []

    def table(self, name):
        return _FakeTable(self.writes, name)


@pytest.mark.parametrize("kind,table", [("customer", "customers"), ("vendor", "vendors")])
def test_the_insert_writes_the_resolved_value_not_the_export_s(kind, table):
    sb = _FakeSb()
    item = {"item_type": kind,
            "tally_data": _ledger("Acme", TRANSPOSED, "AAPFU0939")}
    created_id, created_type = svc._import_single_item("firm-1", "client-1", item, sb)

    assert created_type == table
    assert len(sb.writes) == 1
    written_table, row = sb.writes[0]
    assert written_table == table
    assert row["gstin"] is None, "a GSTIN failing its check digit reached the master"
    assert row["pan"] is None, "a malformed PAN reached the master"
    assert row["name"] == "Acme", "the party itself was lost with its identifier"


@pytest.mark.parametrize("kind", ["customer", "vendor"])
def test_a_good_identifier_still_reaches_the_master_normalised(kind):
    sb = _FakeSb()
    item = {"item_type": kind,
            "tally_data": _ledger("Acme", f" {GOOD_GSTIN.lower()}", GOOD_PAN)}
    svc._import_single_item("firm-1", "client-1", item, sb)
    _, row = sb.writes[0]
    assert row["gstin"] == GOOD_GSTIN
    assert row["pan"] == GOOD_PAN


# ── the preview names them ──────────────────────────────────────────────────

def test_the_preview_names_every_withheld_party_and_slices_none(monkeypatch):
    """`by_type` is sliced to ten because it is a sample; this list is a list
    of ACTIONS, and a truncated one reads as the whole of them."""
    parties = [_ledger(f"Cust {i}", TRANSPOSED, GOOD_PAN) for i in range(25)]
    items, _ = svc.validate_migration_data({"customers": parties}, ["customers"])
    monkeypatch.setitem(svc._MOCK_ITEMS, "job-1", items)

    preview = svc.get_migration_preview("firm-1", "job-1")

    assert preview["error_count"] == 0
    assert preview["can_import"] is True
    withheld = preview["withheld_identifiers"]
    assert len(withheld) == 25, "the list of parties to re-key was truncated"
    assert {w["item_type"] for w in withheld} == {"customer"}
    assert withheld[0]["name"] == "Cust 0"
    assert withheld[0]["reasons"]


def test_a_clean_export_reports_nothing_withheld(monkeypatch):
    items, _ = svc.validate_migration_data(
        {"customers": [_ledger("Acme", GOOD_GSTIN, GOOD_PAN)]}, ["customers"]
    )
    monkeypatch.setitem(svc._MOCK_ITEMS, "job-2", items)
    assert svc.get_migration_preview("firm-1", "job-2")["withheld_identifiers"] == []


# ── no second implementation ────────────────────────────────────────────────

def test_the_importer_carries_no_gstin_pattern_of_its_own():
    """core/validators no longer holds a GSTIN pattern for the same reason:
    the pattern is an invitation to answer the question the cheap way."""
    src = SERVICE.read_text()
    tree = ast.parse(src)
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    for lit in literals:
        assert "Z[0-9A-Z]" not in lit and "[A-Z]{5}" not in lit, (
            f"migration_service.py carries a GSTIN-shaped pattern of its own: {lit!r}"
        )


def test_the_importer_asks_the_rule_at_both_ends():
    """Validation names the withholding for the preview; the insert performs
    it — the preview is the insert's own walk, so what a CA is shown held back
    is what is held back.

    THE RULE IS WHICH FUNCTIONS ASK, NOT HOW MANY TIMES. This first asserted
    `len(calls) == 2`, which is a SPELLING of the rule and not the rule: the
    insert branch had to be split back into one call site per party kind so
    `test_backend_columns_exist_pg` could still read the table names, and a
    correct change broke a guard that had counted them. Same lesson this
    repository has recorded four times over — write the rule.
    """
    tree = ast.parse(SERVICE.read_text())
    asked_in: set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "resolve"
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "party_identifiers"):
                asked_in.add(fn.name)

    assert "validate_migration_data" in asked_in, (
        "the preview cannot name what will be withheld: validation never asks "
        "party_identifiers.resolve"
    )
    assert "_import_single_item" in asked_in, (
        "the insert writes the export's raw value: the insert never asks "
        "party_identifiers.resolve"
    )


def test_this_module_is_not_vacuous():
    """Every assertion above rests on TRANSPOSED being a value the old shape
    check accepted and the new rule refuses. If that stops holding, the whole
    module passes while proving nothing."""
    assert pid.resolve(GOOD_GSTIN, GOOD_PAN).withheld == ()
    assert pid.resolve(TRANSPOSED, GOOD_PAN).withheld != ()
