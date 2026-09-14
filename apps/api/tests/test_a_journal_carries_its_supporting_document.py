"""ACC-25 — the supporting document on a manual journal.

`journal_entries.attachments` has existed since migration 138 and
`_create_journal` writes whatever it is handed. Two things were wrong with
that, and the second one is not in the finding.

  1. NOTHING SENT ONE. The journal editor had no control, so the receipt, the
     vendor invoice or the board note that justifies a coding lived in
     somebody's email and was gone the day they left.

  2. THE FIELD WAS UNVALIDATED. `JournalEntryIn.attachments` was a bare
     `list[dict]`, so a `javascript:` or `data:` URL went into the entry and
     became script execution in the app's own origin the moment a CA clicked
     the "supporting document" on a voucher — stored XSS, delivered by whoever
     uploaded the receipt. `domain/attachments` was written for exactly that on
     the bank side (migration 259) and closes the same hole here.

The 12 September probe pass is why the finding's own suggested `{name, url}`
payload was NOT taken as written: it is the shape that module exists to refuse.
"""
import pytest
from pydantic import ValidationError

from domain.attachments import (
    ALLOWED_SCHEMES, MAX_ATTACHMENTS, Attachment, AttachmentError,
    parse_attachments,
)
from models.accounting import JournalEntryIn

LINES = [
    {"account_id": "a1", "debit_paise": 100_00, "credit_paise": 0},
    {"account_id": "a2", "debit_paise": 0, "credit_paise": 100_00},
]


def _entry(attachments):
    return JournalEntryIn(client_id="CLI", entry_date="2026-06-01",
                          narration="Being x", attachments=attachments, lines=LINES)


# ── the hole, closed ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "data:text/html,<script>fetch('/api/clients')</script>",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
])
def test_a_link_that_can_execute_is_refused(url):
    """The scheme vocabulary is CLOSED rather than sanitised — sanitising is a
    losing game and http/https is a rule with no edge cases."""
    with pytest.raises(ValidationError) as e:
        _entry([{"name": "Receipt", "url": url}])
    assert "http" in str(e.value)


def test_only_http_and_https_are_allowed():
    assert set(ALLOWED_SCHEMES) == {"http", "https"}


def test_an_ordinary_link_goes_through_normalised():
    entry = _entry([{"name": "Receipt", "url": "https://drive.test/r.pdf"}])
    assert entry.attachments == [{"name": "Receipt", "url": "https://drive.test/r.pdf"}]


def test_what_reaches_the_kernel_is_the_PARSED_shape_not_what_was_sent():
    """Normalised, not merely checked. The validator returns the parser's own
    dicts, so whitespace is stripped and any key the module does not know is
    DROPPED rather than written into `journal_entries.attachments` — a JSONB
    column, so an unknown key would be stored verbatim and rendered by whatever
    reads it next.

    A first draft returned `v` after calling the parser for its exceptions
    alone; every refusal above still passed, which is why this case exists.
    """
    entry = _entry([{
        "name": "  Receipt  ",
        "url": "  https://drive.test/r.pdf  ",
        "note": "<img src=x onerror=alert(1)>",
        "document_id": None,
    }])
    assert entry.attachments == [{"name": "Receipt", "url": "https://drive.test/r.pdf"}]


def test_a_name_that_is_a_path_is_refused():
    """The name is display text AND what a download would be called."""
    with pytest.raises(ValidationError):
        _entry([{"name": "../../etc/passwd", "url": "https://x.test/a"}])


def test_a_document_backed_attachment_may_not_carry_a_url():
    """The store's own URLs are SIGNED and expire in an hour, so one written
    here would be a dead link by the time anybody audits the coding — the exact
    moment it is needed. Refused rather than having the url dropped: the two
    are different meanings."""
    with pytest.raises(ValidationError):
        _entry([{"name": "Receipt",
                 "document_id": "11111111-1111-1111-1111-111111111111",
                 "url": "https://x.test/signed?token=abc"}])


def test_a_document_backed_attachment_alone_is_fine():
    entry = _entry([{"name": "Receipt",
                     "document_id": "11111111-1111-1111-1111-111111111111"}])
    assert entry.attachments == [
        {"name": "Receipt", "document_id": "11111111-1111-1111-1111-111111111111"}]
    assert "url" not in entry.attachments[0]


def test_no_attachments_is_still_the_default():
    assert JournalEntryIn(client_id="CLI", entry_date="2026-06-01",
                          narration="x", lines=LINES).attachments == []


def test_too_many_attachments_is_refused():
    many = [{"name": f"R{i}", "url": f"https://x.test/{i}"} for i in range(MAX_ATTACHMENTS + 1)]
    with pytest.raises(ValidationError):
        _entry(many)


# ── one module, in one place ─────────────────────────────────────────────────

def test_the_rule_lives_outside_the_banking_namespace():
    """It was written for a bank transaction and `journal_entries` has carried
    the same shape since migration 138, so the moment a second subsystem needed
    it the module was in the wrong place: `models/accounting` importing
    `domain.banking` is the direction that ends in a cycle."""
    import domain.attachments as canonical
    import domain.banking.attachments as reexport
    assert reexport.parse_attachments is canonical.parse_attachments
    assert reexport.Attachment is canonical.Attachment
    assert reexport.ALLOWED_SCHEMES is canonical.ALLOWED_SCHEMES


def test_the_old_import_path_still_works_for_the_bank_side():
    """`services/bank_batch_service` and its tests import through the old path
    and must not have to move with it."""
    from domain.banking import attachments as att
    got = att.parse_attachments([{"name": "Cheque", "url": "https://x.test/c.jpg"}])
    assert got == [Attachment(name="Cheque", url="https://x.test/c.jpg")]


def test_the_shared_parser_is_what_the_model_calls():
    """A second implementation in models/ is how the journal and the bank line
    come to disagree about what a safe link is."""
    import inspect
    src = inspect.getsource(JournalEntryIn.attachments_are_safe.__func__)
    assert "parse_attachments" in src
    assert "AttachmentError" in src


def test_the_parser_error_is_a_sentence_for_a_ca():
    with pytest.raises(AttachmentError) as e:
        parse_attachments([{"name": "R", "url": "javascript:alert(1)"}])
    assert len(str(e.value)) > 30 and "http" in str(e.value)


# ── THE CORRECTION PATH, WHICH DROPPED THEM SILENTLY ────────────────────────
#
# The first half of ACC-25 gave the editor a control and the CREATE path a
# validated field. The PATCH kept neither: `JournalEntryUpdateIn` had no
# `attachments`, so a CA correcting a DRAFT to add the receipt typed a link
# into a control the screen rendered and lost it with no error. A field the
# screen offers and the server discards is worse than no field at all.

def test_the_correction_path_takes_documents_too():
    from models.accounting import JournalEntryUpdateIn
    got = JournalEntryUpdateIn(
        attachments=[{"name": "Receipt", "url": "https://x.test/r.pdf"}])
    assert got.attachments == [{"name": "Receipt", "url": "https://x.test/r.pdf"}]


def test_omitting_them_leaves_them_alone():
    """Every field on the update model is optional and means "unchanged" — a CA
    fixing a narration must not have to resend the documents."""
    from models.accounting import JournalEntryUpdateIn
    assert JournalEntryUpdateIn(narration="fixed").attachments is None


def test_an_EMPTY_list_is_a_real_answer():
    """It removes them, which is a different thing from not mentioning them.
    The service's header filter keeps `[]` and drops `None` for exactly this."""
    from models.accounting import JournalEntryUpdateIn
    assert JournalEntryUpdateIn(attachments=[]).attachments == []


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,<b>x",
                                 "file:///etc/passwd"])
def test_the_correction_path_refuses_what_the_create_path_refuses(url):
    """A validator on one door only is one PATCH from being none — and this is
    the door an attacker reaches SECOND, after the entry already looks
    legitimate."""
    from models.accounting import JournalEntryUpdateIn
    with pytest.raises(ValidationError):
        JournalEntryUpdateIn(attachments=[{"name": "R", "url": url}])


def test_both_doors_call_the_same_parser():
    import inspect
    from models.accounting import JournalEntryUpdateIn
    src = inspect.getsource(JournalEntryUpdateIn.attachments_are_safe.__func__)
    assert "parse_attachments" in src
    assert "AttachmentError" in src


def test_a_posted_entry_is_REFUSED_rather_than_silently_ignored():
    """`prevent_posted_journal_modification` (last defined in migration 274)
    lets a posted entry's HEADER change only inside
    `journal_edit_in_progress()`, which only `edit_posted_journal` sets — and
    that function rewrites LINES and carries no attachments. So the documents
    cannot move on a posted entry, and the service says so instead of
    discarding them, which is the defect this half exists to fix."""
    import inspect
    from services.manual_journal_service import ManualJournalService
    src = inspect.getsource(ManualJournalService.update)
    assert '"attachments" in data' in src
    assert "is_posted" in src
    # The refusal must come BEFORE the posted branch does anything, or a CA
    # gets the lines rewritten and the documents dropped in the same call.
    assert src.index('"attachments" in data') < src.index('if entry.get("is_posted"):\n            if lines is None')


def test_a_draft_correction_writes_them_to_the_header():
    import inspect
    from services.manual_journal_service import ManualJournalService
    src = inspect.getsource(ManualJournalService.update)
    header = src[src.index("header = {k: v for k, v in {"):]
    assert '"attachments": data.get("attachments")' in header
