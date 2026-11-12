"""
GSTR-1 Table 13 says which document natures it did not look at, and counts the delivery challans it leaves out (POST-A-415, slice 1).

WHAT WAS WRONG
    Table 13 lists twelve document natures and `gstr1_builder._NATURE_OF` reads three. A client that issued a receipt voucher, a
    delivery challan or a self-invoice for a supply from an unregistered person filed a return whose Table 13 left it out, and the
    return said nothing: the cancelled count had a sentence (`GAP_CANCELLED_NOT_READ`), the other nine natures had none.

WHAT THIS HOLDS
    * the sentence is READ OFF the builder's own two constants, so a nature given a home leaves it with nothing else to edit;
    * it says what the build did not look at and never what the client must declare (a reading of the Rules nobody here has
      confirmed), in words a test fences;
    * the one concrete fact is a COUNT of the delivery challans issued in the window by the reason each was issued for, and it
      never names the Table 13 row a challan belongs in;
    * the count is the client's own, the firm's own, the window's own (a QRMP quarter included, both ends inclusive), counts a
      challan that left (issued or received back) and not a draft or a cancelled one;
    * a read that failed is not a nil: `read` False, `count` None, a sentence saying so, and the rest of the return still builds;
    * it is its OWN FIELD and not a gap: a gap is read by three things that mean something specific by it (the screen's
      "validated" status, the GSTR-3B tie-out's list of documents held out of the GSTR-1, the red "not declared" count), and a
      sentence true of every return would have made every return a draft for ever;
    * the rebuild that compares a filed return with the books does not pay for it.
"""
from __future__ import annotations

import services.gst_return_service as grs
import services.table_13_coverage_service as t13svc
from domain.gst import delivery_challan as dc
from domain.gst import gstr1_builder, registrations, table_13_coverage as t13
from tests.e2e_harness import FakeDB
import pytest

FIRM, OTHER_FIRM = "FIRM-13", "FIRM-OTHER"
CLIENT, OTHER_CLIENT = "CLI-13", "CLI-OTHER"
GSTIN = "27AAPFU0939F1ZV"
JUNE = "062026"

ALL = gstr1_builder._DOC_NATURES
DECLARED = set(gstr1_builder._NATURE_OF.values())
NINE = [
    "Invoices for inward supply from unregistered person",
    "Revised Invoice",
    "Receipt Voucher",
    "Payment Voucher",
    "Refund Voucher",
    "Delivery Challan for job work",
    "Delivery Challan for supply on approval",
    "Delivery Challan in case of liquid gas",
    "Delivery Challan in case other than by way of supply (excluding at S no. 9 to 11)",
]

#: Words that would turn "the build did not look" into "the client must declare", which is a reading of the Rules.
CLAIMS = ("must", "required", "liable", "mandatory", "shall", "obliged", "compulsory", "has to be declared", "should", "need ", "needs ", "owes", "owed",
          "ought", "has to", "have to", "entitled")


# ══════════════════════════════════════════════════════════════════════════════
# 1. The rule: derived from the builder's own constants
# ══════════════════════════════════════════════════════════════════════════════

def test_the_builder_reads_three_natures_and_does_not_look_for_the_other_nine():
    assert DECLARED == {"Invoices for outward supply", "Debit Note", "Credit Note"}
    out = gstr1_builder.table_13_coverage(None)
    assert out["not_read_natures"] == NINE
    assert out["declared_natures"] == ["Invoices for outward supply", "Debit Note", "Credit Note"]
    # The form's own order, not alphabetical and not the order the map happens to list them.
    assert out["not_read_natures"] == [n for n in ALL if n not in DECLARED]


def test_the_sentence_names_every_nature_it_did_not_look_at_in_the_forms_own_words():
    note = gstr1_builder.table_13_coverage({})["note"]
    for nature in NINE:
        assert nature in note, nature
    assert "It did not look for the other 9 natures the form lists" in note
    assert note.startswith("This build reads 3 natures of document for Table 13: ")
    head, _, tail = note.partition("It did not look for")
    for carried in DECLARED:
        assert carried in head and carried not in tail, carried


def test_a_nature_given_a_home_leaves_the_sentence_with_nothing_else_to_edit(monkeypatch):
    monkeypatch.setitem(gstr1_builder._NATURE_OF, "receipt_voucher", "Receipt Voucher")
    out = gstr1_builder.table_13_coverage(None)
    assert "Receipt Voucher" not in out["not_read_natures"]
    assert "Receipt Voucher" in out["declared_natures"]
    assert "the other 8 natures" in out["note"]
    assert out["note"].startswith("This build reads 4 natures of document for Table 13: ")
    assert "Receipt Voucher" in out["note"].partition("It did not look for")[0]


def test_one_nature_left_or_one_nature_read_is_singular():
    one_left = t13.natures_note(ALL, [n for n in ALL if n != "Revised Invoice"])
    assert "It did not look for the other 1 nature the form lists: Revised Invoice. " in one_left
    assert "the other 1 natures" not in one_left
    one_read = t13.natures_note(ALL, ["Credit Note"])
    assert one_read.startswith("This build reads 1 nature of document for Table 13: Credit Note. ")
    assert "reads 1 natures" not in one_read


def test_a_table_that_looked_at_everything_has_no_sentence_to_say():
    assert t13.natures_note(ALL, ALL) == ""
    assert t13.not_read(ALL, ALL) == []


def test_the_sentences_say_what_was_not_looked_at_and_never_what_the_client_must_declare():
    texts = [
        gstr1_builder.table_13_coverage(None)["note"],
        t13.challans_note({dc.REASON_JOB_WORK: 2, dc.REASON_ON_APPROVAL: 1, dc.REASON_INVOICE_TO_FOLLOW: 4}),
        t13.challans_note({}),
        t13.challans_note(None),
    ]
    for text in texts:
        low = text.lower()
        for word in CLAIMS:
            assert word not in low, (word, text)
        assert "paise" not in low
    assert "for the CA to settle against the form" in texts[0]
    assert "for the CA to settle against the form" in texts[1]


# ══════════════════════════════════════════════════════════════════════════════
# 2. The challan sentence: a count, in the reason's own words, never a Table 13 row
# ══════════════════════════════════════════════════════════════════════════════

def test_an_unreadable_challan_register_is_not_a_nil_and_a_real_zero_is_a_reading():
    assert t13.challans_note(None) == t13.CHALLANS_NOT_READ
    assert t13.challans_note({}) == t13.NO_CHALLANS
    assert t13.challans_note({dc.REASON_JOB_WORK: 0}) == t13.NO_CHALLANS
    assert t13.CHALLANS_NOT_READ != t13.NO_CHALLANS
    unread = t13.coverage(ALL, DECLARED, None)["challans"]
    assert unread == {"read": False, "count": None, "by_reason": [], "note": t13.CHALLANS_NOT_READ}
    none = t13.coverage(ALL, DECLARED, {})["challans"]
    assert none["read"] is True and none["count"] == 0 and none["by_reason"] == []


def test_the_count_is_by_reason_in_the_fixed_order_with_the_reasons_own_words():
    counts = {dc.REASON_ON_APPROVAL: 1, dc.REASON_JOB_WORK: 2, dc.REASON_LIQUID_GAS: 3}
    rows = t13.by_reason(counts)
    # The order of `delivery_challan.REASONS`, not the dict's and not alphabetical.
    assert [r["reason"] for r in rows] == [dc.REASON_LIQUID_GAS, dc.REASON_JOB_WORK, dc.REASON_ON_APPROVAL]
    assert [r["count"] for r in rows] == [3, 2, 1]
    note = t13.challans_note(counts)
    assert note.startswith("6 delivery challans were issued in this period and are not in this return's Table 13: ")
    for r in rows:
        assert f"{r['count']} for {dc.REASON_LABELS[r['reason']]}" in note


def test_one_challan_is_singular():
    note = t13.challans_note({dc.REASON_JOB_WORK: 1})
    assert note.startswith("1 delivery challan was issued in this period and is not in this return's Table 13: 1 for ")


def test_the_challan_sentence_names_no_table_13_row_because_which_row_is_the_cas_to_settle():
    # Rule 55(4) and (5) challans are issued for a supply, and whether the form files them under "other than by way of supply" is
    # the unconfirmed reading. A count by the reason's own words claims nothing about it.
    note = t13.challans_note({r: 1 for r in dc.REASONS})
    for nature in NINE:
        assert nature not in note, nature
    assert "S no" not in note and "Table 13 row" not in note
    assert "which row of the table each belongs in is for the CA to settle" in note
    # All six of the product's reasons are counted, including the two the form's four challan natures do not obviously take.
    assert len(t13.by_reason({r: 1 for r in dc.REASONS})) == len(dc.REASONS) == 6


def test_a_reason_outside_the_vocabulary_is_counted_in_its_own_word_after_the_known_ones():
    rows = t13.by_reason({"zzz_other": 2, dc.REASON_JOB_WORK: 1})
    assert [r["reason"] for r in rows] == [dc.REASON_JOB_WORK, "zzz_other"]
    assert rows[1]["label"] == "zzz_other"


# ══════════════════════════════════════════════════════════════════════════════
# 3. The service: the client's own challans in the window, and a failed read is said
# ══════════════════════════════════════════════════════════════════════════════

def _challan(db, *, on, reason=dc.REASON_JOB_WORK, status="issued", firm=FIRM, client=CLIENT, no=None):
    return db.seed("delivery_challans", {
        "firm_id": firm, "client_id": client, "document_date": on, "reason": reason, "status": status,
        "document_no": no or f"DC/{on}/{reason}/{status}/{firm}/{client}",
    })


def _coverage(db, period=JUNE, **kw):
    return grs.gstr1_from_books(db, FIRM, CLIENT, period, GSTIN, **kw)["table_13_coverage"]


def test_it_counts_what_left_this_clients_premises_in_this_window_and_nothing_else():
    db = FakeDB()
    _challan(db, on="2026-06-10")                                          # issued, job work
    _challan(db, on="2026-06-12", status="received_back")                  # left and came back
    _challan(db, on="2026-06-30", reason=dc.REASON_ON_APPROVAL)            # last day, inclusive
    _challan(db, on="2026-06-01", reason=dc.REASON_LIQUID_GAS)             # first day, inclusive
    _challan(db, on="2026-06-15", status="draft")                          # never left
    _challan(db, on="2026-06-16", status="cancelled", reason=dc.REASON_LIQUID_GAS)
    _challan(db, on="2026-05-31")                                          # the day before
    _challan(db, on="2026-07-01")                                          # the day after
    _challan(db, on="2026-06-10", client=OTHER_CLIENT)                     # another client of the same firm
    _challan(db, on="2026-06-10", firm=OTHER_FIRM)                         # another firm's, same client id
    cov = _coverage(db)["challans"]
    assert cov["read"] is True
    assert cov["count"] == 4
    assert {r["reason"]: r["count"] for r in cov["by_reason"]} == {
        dc.REASON_JOB_WORK: 2, dc.REASON_ON_APPROVAL: 1, dc.REASON_LIQUID_GAS: 1}
    assert cov["note"].startswith("4 delivery challans were issued in this period and are not in this return's Table 13: ")


def test_a_quarterly_filers_window_is_the_quarter_and_a_monthly_one_is_the_month():
    db = FakeDB()
    _challan(db, on="2026-04-20")
    _challan(db, on="2026-05-20")
    _challan(db, on="2026-06-20")
    quarter = grs.gstr1_from_books(db, FIRM, CLIENT, "042026", GSTIN,
                                   frequency=registrations.QUARTERLY)["table_13_coverage"]
    month = grs.gstr1_from_books(db, FIRM, CLIENT, "042026", GSTIN)["table_13_coverage"]
    assert quarter["challans"]["count"] == 3
    assert month["challans"]["count"] == 1


def test_a_client_with_no_challan_is_told_there_was_none_and_the_nine_natures_are_still_named():
    cov = _coverage(FakeDB())
    assert cov["challans"]["note"] == t13.NO_CHALLANS
    assert cov["not_read_natures"] == NINE


def test_a_failed_read_says_it_could_not_look_and_the_return_still_builds(monkeypatch):
    seen = []
    monkeypatch.setattr(t13svc, "capture_soft_failure", lambda exc, **ctx: seen.append((exc, ctx)))

    class Broken(FakeDB):
        def table(self, name):
            if name == "delivery_challans":
                raise RuntimeError("PGRST: could not read")
            return super().table(name)

    out = grs.gstr1_from_books(Broken(), FIRM, CLIENT, JUNE, GSTIN)
    cov = out["table_13_coverage"]["challans"]
    assert cov == {"read": False, "count": None, "by_reason": [], "note": t13.CHALLANS_NOT_READ}
    assert out["table_13_coverage"]["not_read_natures"] == NINE
    assert "payload" in out and isinstance(out["payload_gaps"], list)
    # It is reported to the people who run the service, not swallowed.
    assert len(seen) == 1 and seen[0][1]["operation"] == "gstr1.table_13_challans"
    assert seen[0][1]["firm_id"] == FIRM and seen[0][1]["client_id"] == CLIENT


def test_the_coverage_is_not_a_gap_so_it_cannot_make_a_return_a_draft_or_a_difference_in_the_tie_out():
    clean = grs.gstr1_from_books(FakeDB(), FIRM, CLIENT, JUNE, GSTIN)
    db = FakeDB()
    for reason in dc.REASONS:
        _challan(db, on="2026-06-10", reason=reason)
    with_challans = grs.gstr1_from_books(db, FIRM, CLIENT, JUNE, GSTIN)
    assert with_challans["table_13_coverage"]["challans"]["count"] == 6
    # Same gaps with six challans in the books as with none: nothing in `payload_gaps` is about them.
    assert ([g["kind"] for g in with_challans["payload_gaps"]]
            == [g["kind"] for g in clean["payload_gaps"]])
    assert not any("challan" in g["reason"].lower() or "Table 13" in g["reason"] for g in with_challans["payload_gaps"])
    # And no new gap kind exists for it.
    assert not [k for k in vars(gstr1_builder) if k.startswith("GAP_") and "CHALLAN" in k]


def test_the_rebuild_that_compares_a_filed_return_with_the_books_does_not_pay_for_it(monkeypatch):
    from services import gst_exception_service

    asked = {}

    def fake(db, firm_id, client_id, period, gstin, **kw):
        asked.update(kw)
        return {"payload": {}, "payload_gaps": []}

    monkeypatch.setattr(grs, "gstr1_from_books", fake)
    gst_exception_service.drift_since_filing(FakeDB(), FIRM, CLIENT, JUNE, GSTIN, {})
    assert asked.get("with_table_13_coverage") is False
    assert asked.get("reconcile_to_ledger") is False


def test_a_build_that_is_not_asked_for_it_reads_no_challan_and_says_none_not_zero():
    reads = []

    class Spy(FakeDB):
        def table(self, name):
            reads.append(name)
            return super().table(name)

    out = grs.gstr1_from_books(Spy(), FIRM, CLIENT, JUNE, GSTIN, with_table_13_coverage=False)
    assert out["table_13_coverage"] is None
    assert "delivery_challans" not in reads
    asked = grs.gstr1_from_books(Spy(), FIRM, CLIENT, JUNE, GSTIN)
    assert asked["table_13_coverage"] is not None


@pytest.fixture
def routed(monkeypatch):
    """The three routes that build a GSTR-1 from the books, driven for real over a FakeDB holding ONE issued challan in June 2026 (and one
    in another client's books). Only the access check, the registration lookup and the amendment fold are stubbed: whose books are read and
    what the fold carries are other tests' questions, and this one asks whether the key reaches the caller."""
    import routers.gst as g

    db = FakeDB()
    _challan(db, on="2026-06-10", reason=dc.REASON_JOB_WORK)
    _challan(db, on="2026-06-10", reason=dc.REASON_JOB_WORK, client=OTHER_CLIENT)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    monkeypatch.setattr(g, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(g, "_client_registration",
                        lambda *a, **k: registrations.Registration(gstin=GSTIN, state_code="27", is_primary=True))
    monkeypatch.setattr(g, "_with_outstanding_amendments", lambda *a, **k: ({}, {"included": True}))
    user = {"firm_id": FIRM, "id": "u-13", "auth_user_id": "auth-13", "email": "ca@13.test", "role": "Partner"}
    return g, user


def _one_challan(data):
    cov = data["table_13_coverage"]
    assert cov is not None, "the route dropped the coverage"
    assert cov["challans"]["read"] is True and cov["challans"]["count"] == 1
    assert [r["reason"] for r in cov["challans"]["by_reason"]] == [dc.REASON_JOB_WORK]
    assert cov["not_read_natures"] == NINE


def test_the_from_books_route_hands_the_coverage_on_with_the_amendments_in(routed):
    g, user = routed
    _one_challan(g.gstr1_from_books_endpoint(g.GSTR1FromBooksRequest(client_id=CLIENT, period=JUNE), current_user=user)["data"])


def test_the_from_books_route_hands_the_coverage_on_with_the_amendments_out(routed):
    g, user = routed
    req = g.GSTR1FromBooksRequest(client_id=CLIENT, period=JUNE, include_amendments=False)
    data = g.gstr1_from_books_endpoint(req, current_user=user)["data"]
    _one_challan(data)
    assert data["amendments"] == {"included": False}


def test_the_with_amendments_route_hands_the_coverage_on(routed):
    g, user = routed
    _one_challan(g.gstr1_with_amendments_endpoint(g.FromBooksRequest(client_id=CLIENT, period=JUNE), current_user=user)["data"])


def test_the_challan_read_is_scoped_to_the_firm_and_the_client_pages_and_sits_outside_the_return_builder():
    import inspect

    src = inspect.getsource(t13svc.issued_challans_by_reason)
    assert '.eq("firm_id", firm_id).eq("client_id", client_id)' in src
    assert "fetch_all(" in src
    assert "SENT_STATUSES" in src
    assert t13svc.SENT_STATUSES == ("issued", "received_back")
    # The return builder does not name the table: `test_no_return_builder_reads_any_of_the_six_tables` keeps the builders off documents that
    # do not declare a supply, and this module is the one reader, which counts and feeds no payload.
    assert "delivery_challans" not in inspect.getsource(grs)
    assert "delivery_challans" not in inspect.getsource(gstr1_builder)


# ══════════════════════════════════════════════════════════════════════════════
# 4. The browser drive speaks the server's sentences, word for word
# ══════════════════════════════════════════════════════════════════════════════

import json
import re
from pathlib import Path

DRIVE = (Path(__file__).resolve().parents[3] / "apps" / "web" / "scripts" / "drive" / "scenarios" / "table13Coverage.mjs")


def _drive_string(name: str) -> str:
    """The text of `const NAME = "…";` in the drive, JSON-decoded (the file writes it as a double-quoted literal)."""
    m = re.search(rf'const {name} = ("(?:[^"\\]|\\.)*");', DRIVE.read_text(encoding="utf-8"))
    assert m, f"{name} is no longer written as a constant in {DRIVE.name}, so the drive's copy of the server's sentence cannot be compared"
    return json.loads(m.group(1))


def _drive_list(name: str) -> list:
    m = re.search(rf"const {name} = (\[.*?\]);", DRIVE.read_text(encoding="utf-8"), re.S)
    assert m, name
    return json.loads(re.sub(r",\s*\]", "]", m.group(1)))


def test_the_drives_sentences_are_what_the_rule_says():
    out = gstr1_builder.table_13_coverage({})
    assert _drive_string("NOTE") == out["note"]
    assert _drive_list("NATURES") == out["declared_natures"]
    assert _drive_list("NOT_READ") == out["not_read_natures"]
    assert _drive_string("CHALLANS_THREE") == t13.challans_note({dc.REASON_JOB_WORK: 2, dc.REASON_ON_APPROVAL: 1})
    assert _drive_string("CHALLANS_UNREAD") == t13.CHALLANS_NOT_READ
    assert _drive_string("CHALLANS_NONE") == t13.NO_CHALLANS
    # And the labels the drive's rows quote are the reasons' own.
    rows = {r["reason"]: r["label"] for r in t13.by_reason({dc.REASON_JOB_WORK: 2, dc.REASON_ON_APPROVAL: 1})}
    drive = DRIVE.read_text(encoding="utf-8")
    for label in rows.values():
        assert label in drive, label
