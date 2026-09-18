"""
PAY-26's remaining half: a Chapter VI-A claim has a DOCUMENT, not a sentence
about one (migration 410).

`payroll_it_declaration_items.proof_reference` has been a bare TEXT column
since migration 296 — somebody types "LIC receipt 12345" and nothing holds the
receipt. §192(1) makes the EMPLOYER answerable for a correct deduction, and
migration 296's own header says a declaration that never grew a proof must stop
reducing tax before the year ends; the verifier had nothing to look at when
deciding that, so `amount_verified_paise` was recorded against a memory.

THREE RULES: the attachment rule is `domain/attachments`' and is not restated,
None means UNCHANGED while [] REMOVES, and `proof_reference` is kept.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from pydantic import ValidationError

from models.payroll import DeclarationItemIn

_API = pathlib.Path(__file__).resolve().parents[1]


def test_a_link_proof_is_accepted_and_normalised():
    item = DeclarationItemIn(section="80C", proof_attachments=[
        {"name": "LIC receipt", "url": "https://example.com/lic.pdf"}])
    assert item.proof_attachments == [
        {"name": "LIC receipt", "url": "https://example.com/lic.pdf"}]


@pytest.mark.parametrize("bad,fragment", [
    ([{"name": "r", "url": "javascript:alert(1)"}], "http or https"),
    ([{"name": "r", "url": "data:text/html,<script>"}], "http or https"),
    ([{"name": "../../etc/passwd", "url": "https://a.b/c"}], "cannot contain a path"),
])
def test_a_dangerous_proof_is_refused_at_the_door(bad, fragment):
    """An employee's own portal upload is untrusted input, and a stored
    `javascript:` or `data:` URL is script execution in the app's own origin
    the moment the CA clicks the "receipt". The scheme vocabulary is CLOSED
    rather than sanitised — sanitising is a losing game."""
    with pytest.raises(ValidationError) as e:
        DeclarationItemIn(section="80C", proof_attachments=bad)
    assert fragment in str(e.value)


def test_none_means_unchanged_and_an_empty_list_removes():
    """This model is the CREATE door and the VERIFY door both. An empty list
    default would wipe an employee's uploads every time a CA saved a verified
    amount without re-sending them — the shape `journal_entries.attachments`
    takes for exactly this reason."""
    assert DeclarationItemIn(section="80C").proof_attachments is None
    assert DeclarationItemIn(section="80C", proof_attachments=[]).proof_attachments == []


def test_the_verify_path_omits_the_column_when_the_request_did_not_send_it():
    """The half a `or []` would silently break. Read off the SOURCE, because
    the behaviour is an absent key in a patch dict and there is no way to
    observe it from the model alone."""
    src = (_API / "routers/payroll.py").read_text(encoding="utf-8")
    assert "if it.proof_attachments is not None:" in src
    assert 'patch["proof_attachments"] = it.proof_attachments' in src


def test_the_rule_is_not_restated_anywhere():
    """`domain/attachments` is the authority. A second, laxer copy in the
    payroll door is how the hole reopens."""
    tree = ast.parse((_API / "models/payroll.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) \
                and ast.get_docstring(node):
            node.body = node.body[1:]
    code = ast.dump(tree)
    assert "parse_attachments" in code
    for spelling in ("javascript", "ALLOWED_SCHEMES", "startswith"):
        assert spelling not in code, spelling


def test_proof_reference_is_kept_and_is_not_replaced():
    """It is the employee's own words about a proof that may only exist on
    paper. Dropping it would lose that; making it a caption for the attachment
    would make a row with paper evidence look empty."""
    item = DeclarationItemIn(section="80C", proof_reference="LIC 12345")
    assert item.proof_reference == "LIC 12345"
    assert item.proof_attachments is None


def test_the_migration_pairs_its_check_with_the_module_constant():
    from domain.attachments import MAX_ATTACHMENTS
    sql = (_API / "migrations/410_a_declared_deduction_has_a_document_behind_it.sql"
           ).read_text(encoding="utf-8")
    assert f"jsonb_array_length(proof_attachments) <= {MAX_ATTACHMENTS}" in sql
    assert "jsonb_typeof(proof_attachments) = 'array'" in sql
