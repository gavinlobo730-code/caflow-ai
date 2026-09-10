"""
Reading a SCANNED statement with a vision model — and the arithmetic that is the
only reason it is allowed to.

CSV and XLSX are parsed deterministically. A text PDF is parsed from real
characters at real coordinates. This path is a model looking at pixels, and it
will sometimes read 8 as 3 or drop a row at a page break. For an invoice that is
tolerable, because a human checks the six fields it produced. For a statement it
is not: nobody reads 300 lines to check them.

So on this path the arithmetic is MANDATORY and a reading that does not add up
is refused rather than imported. Two things can supply it — the totals the
statement prints on itself, read by a separate call that is shown no
transactions, or the balances the CA types — and either will do, which is why a
scan of a statement that states its own totals now needs nothing typed in.

What has NOT relaxed is the outcome: a scan is never imported unverified. What
changed is when the refusal lands. It used to come before any call at all, by
demanding the balances up front; whether they are needed is now a fact about the
picture, so the totals probe goes first, alone, on the last page, and the twenty
page reads behind it never happen. Most of what follows is that rule and the
ways round it that must not exist.

No network anywhere. The model is injected, so the real prompt, the real
parsing and the real refusals are all exercised against fabricated replies.
"""
from __future__ import annotations

import io
import json

import pytest
from fastapi import HTTPException

import routers.banking as banking
import routers.customers as cust
import routers.vendors as ven
import services.opening_balance_service as obs
import services.statement_vision as statement_vision
from domain.banking import vision
from domain.banking.normalizer import StatementParseError
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-VIS"
CLIENT = "CLI-VIS"
CALLER = {"firm_id": FIRM, "id": "u-int-1", "auth_user_id": "u1",
          "email": "ca@firm.test", "role": "Partner"}

_ROWS = [
    {"date": "01/04/2026", "description": "UPI ACME TRADERS", "reference": "R1",
     "debit": "", "credit": "50,000.00", "balance": "1,50,000.00"},
    {"date": "02/04/2026", "description": "NEFT SUPPLIER LTD", "reference": "R2",
     "debit": "20,000.00", "credit": "", "balance": "1,30,000.00"},
]


#: The default answer to the totals probe: "this page prints no totals row".
#: Deliberately the default, so every test that does not say otherwise runs in
#: the world where the CA's balances are the only evidence — which is the case
#: that has to keep working, and the case the refusals are written for.
NO_TOTALS = '{"label": null}'


class _Model:
    """A fake vision model that counts how often it was actually called.

    It answers by PROMPT, because the endpoint makes two different calls with
    two different jobs — transcribe the totals row on the last page, and read
    the transactions off every page — and a fake that answered both the same way
    could not tell them apart. `rows_calls` is the expensive one; `totals_calls`
    is the single page-sized probe that decides whether to make it.
    """
    def __init__(self, reply=None, raises=None, totals=NO_TOTALS):
        self.reply = json.dumps(_ROWS) if reply is None else reply
        self.totals = totals
        self.raises = raises
        self.calls = 0
        self.rows_calls = 0
        self.totals_calls = 0

    def __call__(self, *, image, mime, prompt):
        self.calls += 1
        if prompt is vision.TOTALS_PROMPT or prompt == vision.TOTALS_PROMPT:
            self.totals_calls += 1
            if self.raises:
                raise self.raises
            return self.totals
        self.rows_calls += 1
        if self.raises:
            raise self.raises
        return (self.reply if isinstance(self.reply, str)
                else self.reply[self.rows_calls - 1])


# ══════════════════════════════════════════════════════════════════════════════
# Reading the model's reply
# ══════════════════════════════════════════════════════════════════════════════

def test_it_parses_amounts_with_the_same_code_every_csv_row_uses():
    """The model is asked to copy what is printed, commas and all. Turning
    "1,50,000.00" into paise is _to_paise's job — the function every CSV and
    XLSX cell already goes through — so a date format or a Dr/Cr suffix is
    understood in ONE place rather than two."""
    txns = vision.read_statement([b"page"], call_model=_Model())
    assert [(t.debit_paise, t.credit_paise) for t in txns] == [
        (0, 50_000_00), (20_000_00, 0)]
    assert [t.balance_paise for t in txns] == [1_50_000_00, 1_30_000_00]
    assert [t.transaction_date for t in txns] == ["2026-04-01", "2026-04-02"]


def test_a_debit_written_with_a_dr_suffix_is_still_a_debit():
    model = _Model(json.dumps([
        {"date": "01/04/2026", "description": "CHQ", "debit": "1,000.00 Dr",
         "credit": "", "balance": "9,000.00"}]))
    txns = vision.read_statement([b"p"], call_model=model)
    assert (txns[0].debit_paise, txns[0].credit_paise) == (1_000_00, 0)


def test_a_fenced_reply_is_still_read():
    """Models wrap JSON in ``` more often than not."""
    model = _Model("```json\n" + json.dumps(_ROWS) + "\n```")
    assert len(vision.read_statement([b"p"], call_model=model)) == 2


@pytest.mark.parametrize("reply", [
    "I'm sorry, I can't read this image.",
    "",
    "{\"rows\": []}",
    "[not json at all",
])
def test_a_reply_that_is_not_a_row_array_is_refused_not_salvaged(reply):
    """A partial reading that then fails the tie-out is harder to act on than a
    clear "it could not read this"."""
    with pytest.raises(StatementParseError) as e:
        vision.read_statement([b"p"], call_model=_Model(reply))
    assert "could not be read" in str(e.value).lower()


def test_rows_that_are_not_transactions_are_dropped():
    """Sub-headings, wrapped continuation lines and anything with no money."""
    model = _Model(json.dumps([
        {"date": "", "description": "OPENING BALANCE", "debit": "", "credit": "",
         "balance": "1,00,000.00"},
        {"date": "01/04/2026", "description": "", "debit": "", "credit": "1.00"},
        {"date": "01/04/2026", "description": "A SUB HEADING", "debit": "",
         "credit": "", "balance": ""},
        {"date": "01/04/2026", "description": "REAL ONE", "debit": "", "credit": "5.00"},
    ]))
    txns = vision.read_statement([b"p"], call_model=model)
    assert [t.description for t in txns] == ["REAL ONE"]


def test_pages_are_read_in_order_and_concatenated():
    model = _Model([
        json.dumps([_ROWS[0]]),
        json.dumps([_ROWS[1]]),
    ])
    txns = vision.read_statement([b"p1", b"p2"], call_model=model)
    assert model.calls == 2
    assert [t.description for t in txns] == ["UPI ACME TRADERS", "NEFT SUPPLIER LTD"]


def test_a_provider_failure_names_the_page_and_not_the_provider():
    """Which vendor and model this uses is an internal detail and is not
    actionable for a CA — the same rule document_intelligence_v1 follows."""
    model = _Model(raises=RuntimeError("gemini-3.5-flash quota exceeded for project 42"))
    with pytest.raises(StatementParseError) as e:
        vision.read_statement([b"p1"], call_model=model)
    said = str(e.value)
    assert "page 1" in said
    assert "gemini" not in said.lower() and "quota" not in said.lower()


def test_reading_nothing_at_all_is_a_refusal_with_advice():
    with pytest.raises(StatementParseError) as e:
        vision.read_statement([b"p"], call_model=_Model("[]"))
    assert "no transactions" in str(e.value).lower()
    assert "csv" in str(e.value).lower()


def test_an_empty_page_list_is_refused():
    with pytest.raises(StatementParseError):
        vision.read_statement([], call_model=_Model())


# ══════════════════════════════════════════════════════════════════════════════
# Rasterising, and the page cap
# ══════════════════════════════════════════════════════════════════════════════

def _pdf(html: str) -> bytes:
    from xhtml2pdf import pisa
    buf = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html), dest=buf)
    return buf.getvalue()


def _blank_pdf(pages: int) -> bytes:
    body = '<div style="page-break-after: always">.</div>' * pages
    return _pdf(f"<html><body>{body}</body></html>")


def test_pages_become_images():
    images = vision.page_images(_blank_pdf(2))
    assert len(images) == 2
    assert all(im.startswith(b"\x89PNG") for im in images), "not PNG bytes"


def test_too_many_pages_is_refused_with_the_count():
    """A whole year exported as one scan is a large bill the CA never agreed to.
    It is refused BEFORE any page is sent, and the message says how many."""
    many = vision.MAX_PAGES + 2
    with pytest.raises(StatementParseError) as e:
        vision.page_images(_blank_pdf(many))
    assert str(many) in str(e.value)
    assert str(vision.MAX_PAGES) in str(e.value)


def test_a_truncated_pdf_is_a_parse_error_not_a_crash():
    with pytest.raises(StatementParseError) as e:
        vision.page_images(b"%PDF-1.4")
    assert "could not be opened" in str(e.value)


# ══════════════════════════════════════════════════════════════════════════════
# The endpoint — where the mandatory tie-out is enforced
# ══════════════════════════════════════════════════════════════════════════════

def _setup(monkeypatch, *, model=None, available=True):
    db = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    wire_e2e(monkeypatch, db, [banking, cust, ven, obs])
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM,
                        "financial_year_start": "2026-04-01"})
    seed_standard_coa(db, FIRM, CLIENT)
    model = model or _Model()
    monkeypatch.setattr(statement_vision, "call", model)
    monkeypatch.setattr(statement_vision, "available", lambda: available)
    return db, model


class _Upload:
    """The slice of UploadFile a SYNC route uses.

    The route is plain `def` (see tests/test_a_blocking_route_is_not_async.py),
    so Starlette runs it in a threadpool and it reads the upload through
    `.file` — the SpooledTemporaryFile — rather than awaiting `.read()`. That
    is what a real UploadFile offers, so the double offers it too.
    """
    def __init__(self, filename, content):
        self.filename, self._content = filename, content
        self.file = io.BytesIO(content)

    async def read(self):
        return self._content


def _upload(**kw):
    import asyncio
    return banking.upload_statement(
        file=_Upload(kw.pop("filename"), kw.pop("content")),
        client_id=CLIENT, bank_name="HDFC Bank", account_number=None,
        bank_account_id=None, column_mapping=None, save_mapping=False,
        opening_balance_paise=kw.pop("opening", None),
        closing_balance_paise=kw.pop("closing", None),
        allow_vision=kw.pop("allow_vision", False),
        acknowledge_totals_mismatch=kw.pop("acknowledge", None),
        current_user=CALLER)


SCAN = property(lambda self: None)


def _scan_pdf() -> bytes:
    """A PDF with no extractable text — what a scan looks like to the parser."""
    return _blank_pdf(1)


def test_a_scan_without_asking_for_ai_is_refused_and_says_how(monkeypatch):
    db, model = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _upload(filename="scan.pdf", content=_scan_pdf())
    assert e.value.status_code == 422
    assert "scan" in str(e.value.detail).lower()
    assert "opening and closing balances" in str(e.value.detail)
    assert model.calls == 0, "a model was called without being asked for"


def test_a_scan_with_no_totals_and_no_balances_is_refused_after_ONE_call(monkeypatch):
    """Nothing could check this reading, so it is refused — and the refusal
    costs one page-sized probe rather than the whole statement.

    This used to refuse before any call at all, by demanding the balances up
    front. It cannot any more: whether the balances are needed depends on
    whether the statement prints its own totals, and that is a fact about the
    picture. So the probe goes first, alone, on the last page — and the twenty
    page reads behind it never happen.
    """
    db, model = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True)
    assert e.value.status_code == 422
    assert "proves every line was read" in str(e.value.detail)
    assert model.totals_calls == 1
    assert model.rows_calls == 0, "it read the whole statement and then refused"


def test_an_unconfigured_deployment_refuses_before_rasterising(monkeypatch):
    db, model = _setup(monkeypatch, available=False)
    with pytest.raises(HTTPException) as e:
        _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True,
                opening=1_00_000_00, closing=1_30_000_00)
    assert "not configured" in str(e.value.detail)
    assert model.calls == 0


def test_a_scan_that_ties_out_imports_and_says_a_model_read_it(monkeypatch):
    db, model = _setup(monkeypatch)
    res = _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True,
                  opening=1_00_000_00, closing=1_30_000_00)
    assert model.rows_calls == 1
    assert res["data"]["tie_out"]["agrees"] is True
    assert res["data"]["read_with_ai"] is True, \
        "a CA reviewing these lines is entitled to know they came off a picture"
    assert db.rows("bank_transactions")
    assert db.rows("bank_statements")[0]["source_format"] == "pdf-scan"


def test_a_scan_that_does_NOT_tie_out_imports_nothing(monkeypatch):
    """The whole control. The model was confident and wrong; the arithmetic is
    what decides."""
    db, model = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True,
                opening=1_00_000_00, closing=9_99_999_00)
    assert e.value.status_code == 422
    assert "does not add up" in str(e.value.detail)
    assert not db.rows("bank_transactions"), "a refused scan wrote transactions"
    assert not db.rows("bank_statements")


def test_a_photograph_is_read_and_recorded_as_an_image(monkeypatch):
    db, model = _setup(monkeypatch)
    res = _upload(filename="statement.jpg", content=b"\xff\xd8\xff-not-really-a-jpeg",
                  allow_vision=True, opening=1_00_000_00, closing=1_30_000_00)
    assert model.rows_calls == 1
    assert res["data"]["read_with_ai"] is True
    assert db.rows("bank_statements")[0]["source_format"] == "image"


def test_a_TEXT_pdf_is_never_sent_to_the_model_even_when_ai_is_allowed(monkeypatch):
    """THE ORDERING RULE. A parse from real characters beats a reading of pixels
    and costs nothing, so the deterministic parsers run first and always."""
    db, model = _setup(monkeypatch)
    head = ("<tr><td>Date</td><td>Narration</td><td>Value Dt</td><td>Chq/Ref No</td>"
            "<td>Withdrawal Amt.</td><td>Deposit Amt.</td><td>Closing Balance</td></tr>")
    rows = ("<tr><td>01/04/2026</td><td>UPI ACME TRADERS</td><td>01/04/2026</td>"
            "<td>REF1</td><td></td><td>50000.00</td><td>150000.00</td></tr>"
            "<tr><td>02/04/2026</td><td>NEFT SUPPLIER LTD</td><td>02/04/2026</td>"
            "<td>REF2</td><td>20000.00</td><td></td><td>130000.00</td></tr>")
    res = _upload(filename="stmt.pdf",
                  content=_pdf(f'<html><body><table border="1">{head}{rows}</table></body></html>'),
                  allow_vision=True, opening=1_00_000_00, closing=1_30_000_00)
    assert model.calls == 0, "a readable PDF was sent to a model anyway"
    assert res["data"]["read_with_ai"] is False
    assert db.rows("bank_statements")[0]["source_format"] == "pdf"


def test_a_broken_csv_is_not_rescued_by_the_model(monkeypatch):
    """Vision is for what cannot be parsed, not for what parsed badly. A
    malformed CSV is a malformed CSV and a picture will not help."""
    db, model = _setup(monkeypatch)
    with pytest.raises(HTTPException):
        _upload(filename="stmt.csv", content=b"nonsense,without,any,columns\n1,2,3,4\n",
                allow_vision=True, opening=1, closing=2)
    assert model.calls == 0


# ══════════════════════════════════════════════════════════════════════════════
# The statement's own totals, on a scan
# ══════════════════════════════════════════════════════════════════════════════

_TOTALS = ('{"label": "Grand Total", "total_withdrawals": "20,000.00", '
           '"total_deposits": "50,000.00"}')


def test_the_totals_are_transcribed_from_the_page():
    got = vision.read_printed_totals(b"page", call_model=_Model(totals=_TOTALS))
    assert got == {"label": "Grand Total",
                   "total_debits_paise": 20_000_00,
                   "total_credits_paise": 50_000_00}


def test_the_totals_call_is_SHOWN_NO_TRANSACTIONS():
    """THE REASON THIS IS A SECOND CALL AT ALL.

    A model that produced the transactions and the totals in one reply can
    produce a total that agrees BY CONSTRUCTION — asked for a grand total beside
    a list it has just written out, it will add the list up. The check would be
    the reading verifying itself, which is worth nothing and looks exactly like
    a passing check.

    So the prompt this call sends must contain no transactions, and must tell
    the model to transcribe rather than compute. If either stops being true the
    independence is gone and the check is decoration.
    """
    seen = {}

    def spy(*, image, mime, prompt):
        seen["prompt"] = prompt
        return _TOTALS

    vision.read_printed_totals(b"page", call_model=spy)
    prompt = seen["prompt"]
    assert prompt == vision.TOTALS_PROMPT
    assert "TRANSCRIBE" in prompt
    assert "do NOT work either figure out from anything else" in " ".join(prompt.split())
    for row in _ROWS:
        assert row["description"] not in prompt, "the totals call saw the rows"
    assert "50,000.00" not in prompt, "the totals call saw an amount"


@pytest.mark.parametrize("reply, why", [
    ('{"label": null}', "the page prints no totals row"),
    ('{"label": "Sum of transactions", "total_withdrawals": "1", "total_deposits": "2"}',
     "an invented label is what a model that COMPUTED tends to write"),
    ('{"label": "Grand Total", "total_withdrawals": "", "total_deposits": "50,000.00"}',
     "half a pair is not a pair"),
    ('{"label": "Grand Total", "total_withdrawals": "about twenty thousand", '
     '"total_deposits": "50,000.00"}', "not money"),
    ("I could not find a totals row on this page.", "prose, not JSON"),
    ('["Grand Total", "20,000.00"]', "an array is the wrong shape"),
])
def test_anything_but_a_clean_transcription_is_None(reply, why):
    """None means "fall back to the balances the CA types". A plausible pair of
    invented numbers means a real import is refused, or a wrong one accepted —
    so the bar is high and everything else is None."""
    assert vision.read_printed_totals(b"page", call_model=_Model(totals=reply)) is None, why


def test_a_totals_call_that_fails_is_not_fatal():
    """The totals are the bonus half of the evidence on this path. Failing the
    whole upload because they could not be fetched would be the wrong trade —
    the balances still work, and the caller refuses if neither is available."""
    model = _Model(totals=_TOTALS, raises=RuntimeError("provider down"))
    assert vision.read_printed_totals(b"page", call_model=model) is None


def test_a_fenced_totals_reply_is_still_read():
    """Same tolerance _rows_from_reply extends, and now literally the same code
    (_strip_fence): a code fence is a formatting habit, not a failure to read."""
    fenced = "```json\n" + _TOTALS + "\n```"
    assert vision.read_printed_totals(b"page", call_model=_Model(totals=fenced))


# ── At the endpoint ──────────────────────────────────────────────────────────

def test_a_scan_that_prints_its_totals_needs_nothing_typed_in(monkeypatch):
    """The point of the change. A CA photographing a statement that ends with
    its own Grand Total no longer types two numbers off the same page."""
    db, model = _setup(monkeypatch, model=_Model(totals=_TOTALS))
    res = _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True)
    data = res["data"]
    assert data["verified"] is True
    assert data["totals_check"]["agrees"] is True
    assert data["tie_out"]["checked"] is False, "nothing was typed in"
    assert data["read_with_ai"] is True
    assert db.rows("bank_transactions")


def test_a_scan_whose_reading_misses_its_own_totals_imports_NOTHING(monkeypatch):
    """The control, with the balances out of the picture entirely. The model
    read two transactions; the statement says the withdrawals came to more than
    they add up to. A row was missed, so nothing is imported."""
    wrong = ('{"label": "Grand Total", "total_withdrawals": "35,000.00", '
             '"total_deposits": "50,000.00"}')
    db, model = _setup(monkeypatch, model=_Model(totals=wrong))
    with pytest.raises(HTTPException) as e:
        _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True)
    assert e.value.status_code == 422
    assert "Grand Total" in str(e.value.detail)
    assert not db.rows("bank_transactions"), "a refused scan wrote transactions"
    assert not db.rows("bank_statements")


def test_a_scan_cannot_be_imported_over_its_own_totals(monkeypatch):
    """BANK-01 added a way past a printed-totals mismatch — a written reason,
    recorded on the statement row. It stops at the door of this path, and the
    reason is not caution, it is that there is nothing left to appeal to: on a
    deterministic parse the CA can open the CSV and see the rows the parser saw,
    while here the ONLY reading of the file is the one whose arithmetic failed.
    Accepting it would be taking a model's word against the statement's own."""
    wrong = ('{"label": "Grand Total", "total_withdrawals": "35,000.00", '
             '"total_deposits": "50,000.00"}')
    db, model = _setup(monkeypatch, model=_Model(totals=wrong))
    with pytest.raises(HTTPException) as e:
        _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True,
                acknowledge="the statement's own total includes the brought-forward line")
    assert e.value.status_code == 422
    assert "scanned statement cannot be imported over a totals mismatch" in str(e.value.detail)
    assert not db.rows("bank_statements")


def test_the_totals_are_read_from_the_LAST_page(monkeypatch):
    """A statement prints its grand total at the end. Probing the first page
    would find a page header, or a "brought forward" line, on every multi-page
    scan."""
    seen = []

    class _Pages(_Model):
        def __call__(self, *, image, mime, prompt):
            if prompt == vision.TOTALS_PROMPT:
                seen.append(image)
            return super().__call__(image=image, mime=mime, prompt=prompt)

    # Three pages of the same two rows, so the totals the probe reports have to
    # cover all six or the import is refused before the assertion is reached.
    three_pages = ('{"label": "Grand Total", "total_withdrawals": "60,000.00", '
                   '"total_deposits": "1,50,000.00"}')
    _setup(monkeypatch, model=_Pages(totals=three_pages))
    pdf = _blank_pdf(3)
    _upload(filename="scan.pdf", content=pdf, allow_vision=True)
    assert len(seen) == 1, "one probe, not one per page"
    assert seen[0] == vision.page_images(pdf)[-1]


def test_both_kinds_of_evidence_are_checked_when_both_are_there(monkeypatch):
    """They answer different questions and neither implies the other, so a scan
    that has both gets both. The totals cannot say this file is the whole
    period; the balances cannot catch a misread that preserves their
    arithmetic."""
    db, model = _setup(monkeypatch, model=_Model(totals=_TOTALS))
    res = _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True,
                  opening=1_00_000_00, closing=1_30_000_00)
    assert res["data"]["totals_check"]["agrees"] is True
    assert res["data"]["tie_out"]["agrees"] is True


def test_matching_totals_do_not_excuse_balances_that_disagree(monkeypatch):
    """Verified means every check that ran passed, not that one of them did."""
    db, model = _setup(monkeypatch, model=_Model(totals=_TOTALS))
    with pytest.raises(HTTPException) as e:
        _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True,
                opening=1_00_000_00, closing=9_99_999_00)
    assert e.value.status_code == 422
    assert not db.rows("bank_transactions")
