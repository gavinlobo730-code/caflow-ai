"""
Batch accept / exclude (Tier 1.7) and attachments (Tier 1.8).

Two things here are worth more than the feature itself:

  * a bulk action over financial records must report what happened to EACH row.
    A partial success reported as a success is how a transaction quietly stays
    uncoded until year end.
  * an attachment URL is rendered as a link. A stored javascript: or data: URL
    is stored XSS, delivered by whoever uploaded the "receipt".
"""
import pytest
from fastapi import HTTPException

from domain.banking.attachments import (
    Attachment, AttachmentError, parse_attachments, add, remove,
    ALLOWED_SCHEMES, MAX_ATTACHMENTS, MAX_NAME_LENGTH,
)
from models.banking import BankBatchIn
from services.bank_batch_service import bank_batch_service, MAX_BATCH


# ══════════════════════════════════════════════════════════════════════════════
# 1.8 — the URL guard
# ══════════════════════════════════════════════════════════════════════════════

def test_an_ordinary_https_link_is_accepted():
    got = parse_attachments([{"name": "receipt.pdf", "url": "https://files.example.com/r.pdf"}])
    assert got == [Attachment("receipt.pdf", "https://files.example.com/r.pdf")]


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "  javascript:alert(1)  ",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
])
def test_a_link_that_can_run_code_or_read_disk_is_refused(url):
    """THE security case. This value is rendered as a link a CA will click, so
    the scheme vocabulary is closed rather than sanitised — sanitising is a
    losing game, allowing exactly http/https is not."""
    with pytest.raises(AttachmentError):
        parse_attachments([{"name": "x.pdf", "url": url}])


@pytest.mark.parametrize("url", [
    "javascript://evil.com/%0aalert(1)",
    "data://host,alert(1)",
    "vbscript://host/x",
])
def test_a_dangerous_scheme_that_carries_a_host_is_still_refused(url):
    """THE case the other refusal test does not reach.

    `javascript:alert(1)` has an empty netloc, so a "must have an address"
    check alone rejects it — which meant the scheme allow-list was doing no
    work in any test and could have been deleted unnoticed (mutation testing
    caught exactly that). `javascript://evil.com/%0aalert(1)` is a real payload
    that DOES parse a netloc: the newline ends the comment and the rest runs.
    Only the scheme allow-list stops it."""
    with pytest.raises(AttachmentError):
        parse_attachments([{"name": "x.pdf", "url": url}])


def test_the_allowed_schemes_are_exactly_http_and_https():
    assert set(ALLOWED_SCHEMES) == {"http", "https"}


def test_a_link_with_no_address_is_refused():
    with pytest.raises(AttachmentError):
        parse_attachments([{"name": "x.pdf", "url": "https://"}])


def test_an_over_long_link_is_refused():
    with pytest.raises(AttachmentError):
        parse_attachments([{"name": "x.pdf", "url": "https://e.com/" + "a" * 3000}])


# ── names ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["../../etc/passwd", "a/b.pdf", "a\\b.pdf", ".hidden"])
def test_a_name_that_looks_like_a_path_is_refused(name):
    """The name is display text AND what a download would be called."""
    with pytest.raises(AttachmentError):
        parse_attachments([{"name": name, "url": "https://e.com/x.pdf"}])


def test_a_blank_name_or_url_is_refused():
    with pytest.raises(AttachmentError):
        parse_attachments([{"name": "  ", "url": "https://e.com/x.pdf"}])
    with pytest.raises(AttachmentError):
        parse_attachments([{"name": "x.pdf", "url": "   "}])


def test_an_over_long_name_is_refused():
    with pytest.raises(AttachmentError):
        parse_attachments([{"name": "a" * (MAX_NAME_LENGTH + 1),
                            "url": "https://e.com/x.pdf"}])


def test_names_and_links_are_trimmed():
    got = parse_attachments([{"name": "  r.pdf  ", "url": "  https://e.com/r.pdf  "}])
    assert got[0].name == "r.pdf" and got[0].url == "https://e.com/r.pdf"


# ── the list ─────────────────────────────────────────────────────────────────

def test_an_empty_or_missing_list_is_fine():
    assert parse_attachments(None) == [] and parse_attachments([]) == []


@pytest.mark.parametrize("bad", ["a string", {"name": "x"}, b"bytes"])
def test_something_that_is_not_a_list_is_refused(bad):
    with pytest.raises(AttachmentError):
        parse_attachments(bad)


def test_too_many_attachments_are_refused():
    many = [{"name": f"{i}.pdf", "url": f"https://e.com/{i}.pdf"}
            for i in range(MAX_ATTACHMENTS + 1)]
    with pytest.raises(AttachmentError):
        parse_attachments(many)


def test_the_failing_attachment_is_named():
    with pytest.raises(AttachmentError) as ei:
        parse_attachments([{"name": "ok.pdf", "url": "https://e.com/a.pdf"},
                           {"name": "bad.pdf", "url": "javascript:alert(1)"}])
    assert "Attachment 2" in str(ei.value)


# ── add / remove ─────────────────────────────────────────────────────────────

def test_adding_appends_and_keeps_order():
    first = add([], "a.pdf", "https://e.com/a.pdf")
    second = add(first, "b.pdf", "https://e.com/b.pdf")
    assert [x["name"] for x in second] == ["a.pdf", "b.pdf"]


def test_adding_the_same_link_twice_is_refused():
    """Almost always a double-click, not two documents."""
    first = add([], "a.pdf", "https://e.com/a.pdf")
    with pytest.raises(AttachmentError):
        add(first, "again.pdf", "https://e.com/a.pdf")


def test_adding_revalidates_what_is_already_stored():
    """A row could have been written before a rule existed. Carrying a bad value
    forward because 'only the new one is checked' is how it survives a
    tightening."""
    with pytest.raises(AttachmentError):
        add([{"name": "old.pdf", "url": "javascript:alert(1)"}],
            "new.pdf", "https://e.com/new.pdf")


def test_adding_past_the_cap_is_refused():
    full = [{"name": f"{i}.pdf", "url": f"https://e.com/{i}.pdf"}
            for i in range(MAX_ATTACHMENTS)]
    with pytest.raises(AttachmentError):
        add(full, "one-more.pdf", "https://e.com/more.pdf")


def test_removing_drops_only_that_link():
    two = add(add([], "a.pdf", "https://e.com/a.pdf"), "b.pdf", "https://e.com/b.pdf")
    assert [x["name"] for x in remove(two, "https://e.com/a.pdf")] == ["b.pdf"]


def test_removing_something_absent_is_not_an_error():
    """The list ends up in the state the caller asked for."""
    one = add([], "a.pdf", "https://e.com/a.pdf")
    assert remove(one, "https://e.com/nope.pdf") == one


# ══════════════════════════════════════════════════════════════════════════════
# The service
# ══════════════════════════════════════════════════════════════════════════════

FIRM, CLIENT = "firm-1", "client-1"


class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op, self.payload = "select", None
        self.eqs, self.ins = [], []
        self.limit_ = None

    def select(self, *_a, **_k): self.op = "select"; return self
    def update(self, p): self.op, self.payload = "update", p; return self
    def eq(self, k, v): self.eqs.append((k, v)); return self
    def in_(self, k, vals): self.ins.append((k, set(vals))); return self
    def or_(self, *_a, **_k): return self
    def is_(self, k, _v): self.eqs.append((k, None)); return self
    def limit(self, n): self.limit_ = n; return self
    def order(self, *_a, **_k): return self

    def execute(self):
        rows = self.s.setdefault(self.t, [])
        m = [r for r in rows
             if not any(r.get(k) != v for k, v in self.eqs)
             and not any(r.get(k) not in vals for k, vals in self.ins)]
        if self.op == "update":
            for r in m:
                r.update(self.payload)
            return _Resp(m)
        return _Resp(m[:self.limit_] if self.limit_ else m)


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, n): return _Q(self.store, n)


def _db():
    db = FakeDB()
    db.store["bank_transactions"] = []
    db.store["bank_matching_rules"] = []
    return db


def _txn(db, id_, *, description="ACME RENT", posted=False, ignored=False,
         category=None, account_id=None, attachments=None, **kw):
    row = {"id": id_, "firm_id": FIRM, "client_id": CLIENT,
           "transaction_date": "2026-04-01", "description": description,
           "debit_paise": 100000, "credit_paise": 0, "category": category,
           "account_id": account_id, "payee_id": None, "payee_name": None,
           "posted_journal_id": "je-1" if posted else None,
           "posted_at": "2026-04-01" if posted else None,
           "match_status": "ignored" if ignored else "unmatched",
           "matched_entity_id": None, "attachments": attachments if attachments is not None else []}
    row.update(kw)
    db.store["bank_transactions"].append(row)
    return row


def _rule(db, **kw):
    base = {"id": "r1", "firm_id": FIRM, "client_id": CLIENT, "rule_name": "Rent",
            "is_active": True, "description_pattern": "RENT",
            "suggested_category": "Expense", "suggested_account_id": "acc-rent",
            "created_at": "2026-01-01"}
    base.update(kw)
    db.store["bank_matching_rules"].append(base)
    return base


@pytest.fixture(autouse=True)
def _silence(monkeypatch):
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None, raising=False)
    yield


# ── 1.7 accept — retired 2026-09-03 ─────────────────────────────────────────
# "Accept" (code a row from its rule or history, in bulk) was replaced by the
# entries model: every line is always drafted, and "Pass N ready" posts the
# drafts. Its properties — a rule outranks history, nothing is guessed, per-row
# outcomes, one bad row never rolls back the rest — are held by
# tests/test_bank_entry_service.py against bank_entry_service.pass_ready.

# ── 1.7 exclude / include ────────────────────────────────────────────────────

def test_exclude_and_include_round_trip():
    db = _db(); _txn(db, "t1")
    assert bank_batch_service.set_excluded(db, FIRM, ["t1"], True)["applied"] == 1
    assert db.store["bank_transactions"][0]["match_status"] == "ignored"
    assert bank_batch_service.set_excluded(db, FIRM, ["t1"], False)["applied"] == 1
    assert db.store["bank_transactions"][0]["match_status"] == "unmatched"


def test_excluding_something_already_excluded_is_reported_as_skipped():
    db = _db(); _txn(db, "t1", ignored=True)
    out = bank_batch_service.set_excluded(db, FIRM, ["t1"], True)
    assert out["skipped"] == 1 and "Already excluded" in out["results"][0]["reason"]


def test_a_posted_transaction_cannot_be_excluded():
    """Hiding a line that is on the books is the opposite of what exclusion
    means."""
    db = _db(); _txn(db, "t1", posted=True)
    out = bank_batch_service.set_excluded(db, FIRM, ["t1"], True)
    assert out["skipped"] == 1 and "cannot be excluded" in out["results"][0]["reason"]
    assert db.store["bank_transactions"][0]["match_status"] != "ignored"


# ── batch bounds ─────────────────────────────────────────────────────────────

def test_an_empty_batch_is_refused():
    db = _db()
    with pytest.raises(HTTPException) as ei:
        bank_batch_service.set_excluded(db, FIRM, [], True)
    assert ei.value.status_code == 422


def test_an_oversized_batch_is_refused():
    db = _db()
    with pytest.raises(HTTPException) as ei:
        bank_batch_service.set_excluded(db, FIRM, [f"t{i}" for i in range(MAX_BATCH + 1)], True)
    assert ei.value.status_code == 422


def test_the_model_refuses_an_empty_selection():
    with pytest.raises(ValueError):
        BankBatchIn(transaction_ids=[])


# ── 1.8 service ──────────────────────────────────────────────────────────────

def test_attaching_and_detaching_a_document():
    db = _db(); _txn(db, "t1")
    out = bank_batch_service.add_attachment(db, FIRM, "t1", "receipt.pdf",
                                            "https://e.com/r.pdf")
    assert out["attachments"] == [{"name": "receipt.pdf", "url": "https://e.com/r.pdf"}]
    out = bank_batch_service.remove_attachment(db, FIRM, "t1", "https://e.com/r.pdf")
    assert out["attachments"] == []


def test_a_dangerous_link_is_refused_at_the_service_too():
    db = _db(); _txn(db, "t1")
    with pytest.raises(HTTPException) as ei:
        bank_batch_service.add_attachment(db, FIRM, "t1", "x.pdf", "javascript:alert(1)")
    assert ei.value.status_code == 422
    assert db.store["bank_transactions"][0]["attachments"] == []


def test_a_posted_transaction_can_still_gain_a_document():
    """An attachment is evidence ABOUT a transaction, not part of its ledger
    entry — attaching the receipt after posting is normal and must keep working."""
    db = _db(); _txn(db, "t1", posted=True)
    out = bank_batch_service.add_attachment(db, FIRM, "t1", "r.pdf", "https://e.com/r.pdf")
    assert len(out["attachments"]) == 1


def test_listing_reports_a_stored_value_that_no_longer_validates():
    """Rather than handing it to the UI as though it were fine."""
    db = _db(); _txn(db, "t1", attachments=[{"name": "x", "url": "javascript:alert(1)"}])
    out = bank_batch_service.list_attachments(db, FIRM, "t1")
    assert out["attachments"] == [] and out["invalid"]


def test_another_firms_transaction_is_not_found_for_attachments():
    db = _db(); _txn(db, "t1", firm_id="other-firm")
    with pytest.raises(HTTPException) as ei:
        bank_batch_service.add_attachment(db, FIRM, "t1", "r.pdf", "https://e.com/r.pdf")
    assert ei.value.status_code == 404


# ── the endpoints ────────────────────────────────────────────────────────────

PARTNER = {"firm_id": FIRM, "role": "Partner", "auth_user_id": "p1", "id": "u1"}


def test_the_batch_endpoint_returns_the_standard_envelope(monkeypatch):
    import core.authz as authz
    import routers.banking as br
    db = _db(); _txn(db, "t1")
    monkeypatch.setattr(br, "_db", lambda: db)
    monkeypatch.setattr(authz, "_USE_MOCK", True)
    res = br.batch_exclude(BankBatchIn(transaction_ids=["t1"]), current_user=PARTNER)
    assert res["success"] is True and res["error"] is None
    assert res["data"]["applied"] == 1


def test_the_attachment_endpoints_round_trip(monkeypatch):
    import core.authz as authz
    import routers.banking as br
    from models.banking import BankAttachmentIn, BankAttachmentRemoveIn
    db = _db(); _txn(db, "t1")
    monkeypatch.setattr(br, "_db", lambda: db)
    monkeypatch.setattr(authz, "_USE_MOCK", True)
    br.add_transaction_attachment(
        "t1", BankAttachmentIn(name="r.pdf", url="https://e.com/r.pdf"), current_user=PARTNER)
    got = br.list_transaction_attachments("t1", current_user=PARTNER)
    assert len(got["data"]["attachments"]) == 1
    br.remove_transaction_attachment(
        "t1", BankAttachmentRemoveIn(url="https://e.com/r.pdf"), current_user=PARTNER)
    assert br.list_transaction_attachments("t1", current_user=PARTNER)["data"]["attachments"] == []
