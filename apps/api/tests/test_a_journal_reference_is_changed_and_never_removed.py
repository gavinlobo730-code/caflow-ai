"""A manual journal's reference is changed and never removed, and the screen and the server say so in one sentence (POST-A-399).

WHAT WAS WRONG
    The journal editor sent an emptied Reference box as `reference_no: null`. Every field of the update model reads null as "not sent",
    so the old reference stayed and the screen said the entry was corrected. The survey of 22-11-2026 recorded this as the one remaining
    edit where an emptied box is silently kept, and as needing a migration, because the posted path keeps the old value in SQL
    (`COALESCE(p_reference_no, reference_no)` in `edit_posted_journal`).

WHY IT IS A REFUSAL AND NOT A CLEAR, AND SO NEEDS NO MIGRATION
    A reference is not a soft particular an entry may be without. `manual_journal_service.create` gives every manual journal one
    (`MJ-` and eight characters) when none is typed, and the posting kernel's guard against posting one voucher twice is keyed on the
    client, the reference and the date. `models/clearable.py` states the rule this follows: a value that every document of its kind
    carries is corrected and not cleared (a due date is the precedent). So the database function is right to keep the reference when
    none is passed, and the defect was only that nobody said so.

WHAT IS ASSERTED
    * a blank reference on an edit is refused by the model in the one sentence, in every blank spelling;
    * null is still "not sent" (the key is absent from what the route hands the service), and a typed reference is trimmed;
    * the reference is not on the model's clearable set (it has none), and the route stays on the list of routes that cannot clear;
    * the premise the sentence states is true of the create path: a blank reference is replaced by a generated one;
    * the screen's sentence is the server's, character for character, and the page refuses before it sends.
"""
from __future__ import annotations

import inspect
import pathlib

import pytest
from pydantic import ValidationError

from models.accounting import JOURNAL_REFERENCE_NOT_REMOVED, JournalEntryUpdateIn
from models.clearable import clearable_fields
from services.manual_journal_service import ManualJournalService

API = pathlib.Path(__file__).resolve().parents[1]
WEB_SENTENCE = API.parent / "web" / "lib" / "accounting" / "journalReference.ts"   # apps/web/lib/accounting/journalReference.ts
WEB_PAGE = API.parent / "web" / "app" / "clients" / "[id]" / "accounting" / "journal" / "[entryId]" / "edit" / "_page.tsx"   # apps/web/app/clients/[id]/accounting/journal/[entryId]/edit/_page.tsx


@pytest.mark.parametrize("blank", ["", " ", "   ", "\t", "\n"])
def test_a_blank_reference_on_an_edit_is_refused_in_the_one_sentence(blank):
    with pytest.raises(ValidationError) as refused:
        JournalEntryUpdateIn(reference_no=blank)
    assert JOURNAL_REFERENCE_NOT_REMOVED in str(refused.value)


def test_null_is_still_not_sent_and_a_typed_reference_is_trimmed():
    assert "reference_no" not in JournalEntryUpdateIn(reference_no=None, narration="Year-end accrual").model_dump(exclude_none=True)
    assert "reference_no" not in JournalEntryUpdateIn(narration="Year-end accrual").model_dump(exclude_none=True)
    assert JournalEntryUpdateIn(reference_no="  JV/2026/014 ").model_dump(exclude_none=True) == {"reference_no": "JV/2026/014"}


def test_the_reference_is_not_something_an_edit_may_clear():
    assert clearable_fields(JournalEntryUpdateIn()) == frozenset()
    still_listed = (API / "tests" / "fixtures" / "patch_handlers_that_cannot_clear.txt").read_text(encoding="utf-8")
    assert "routers/accounting.py::update_journal_entry\n" in still_listed


def test_a_new_entry_with_no_reference_is_given_one():
    """The premise of the sentence ("every entry carries one"): the create path replaces a missing reference with a generated one."""
    source = inspect.getsource(ManualJournalService.create)
    assert 'data.get("reference_no") or f"MJ-' in source, "the create path no longer gives a reference when none is typed: the sentence is untrue"


def test_the_sentence_names_what_to_do_and_why():
    assert JOURNAL_REFERENCE_NOT_REMOVED.startswith("A journal entry's reference can be changed but not removed: enter the new reference.")
    assert "posted twice" in JOURNAL_REFERENCE_NOT_REMOVED


def test_the_screen_says_the_servers_sentence_and_refuses_before_it_sends():
    web = WEB_SENTENCE.read_text(encoding="utf-8")
    # The TypeScript constant is two string literals joined by `+`; read them and join them.
    start = web.index("export const JOURNAL_REFERENCE_NOT_REMOVED =")
    body = web[start:web.index(";", start)]
    said = "".join(part for part in body.split('"')[1::2])
    assert said == JOURNAL_REFERENCE_NOT_REMOVED

    page = WEB_PAGE.read_text(encoding="utf-8")
    refusal = page.index("removedJournalReferenceProblem(entry?.reference_no, payload.reference_no)")
    sent = page.index("api.accounting.updateJournalEntry(")
    assert refusal < sent, "the journal edit page sends the request before it asks whether the reference was emptied"
    assert "reference_no: payload.reference_no || null" not in page, "the page still sends an emptied reference as null, which reads as not sent"
