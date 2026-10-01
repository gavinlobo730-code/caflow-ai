"""market_and_trust-09 — a capability or security sentence on the marketing site is
written down in the claims ledger, with the test that proves it, or the required
backend check fails.

WHAT WAS WRONG. `test_the_marketing_site_does_not_claim_what_the_code_does_not_do.py`
and `test_the_marketing_site_says_what_the_product_does.py` ban invented proof
(testimonials, customer counts, uptime, ratings) and a list of filing verbs and
phrasings somebody had already found false. That is a record of drift and not a defence
against the next one: it had no pattern and no map for CAPABILITY and SECURITY claims,
which is exactly where the drift happened — Tally import, SSO, two-factor, "who viewed",
a portal upload — so a sentence promising something new passed every guard because
nobody had yet been bitten by it.

THE RULE. `_marketing_vocabulary.topics_of` decides whether a sentence is promising
something about what the product does, how it protects data or what the vendor will do.
`_marketing_claims.CLAIMS` lists every such sentence on the site — exact text, the files
it appears in — under the fact it asserts and the test that proves the fact. The two
sets must be EQUAL: a sentence on the site that is not in the ledger is a promise nobody
has reviewed, and a ledger sentence that is not on the site is a review that no longer
describes anything (and would silently keep a reworded sentence's old proof).

THE RATCHETS. `proven` claims name tests and each name is checked against the test
file's own AST, so a rename cannot leave a claim pointing at nothing. The `unproven` and
`commitment` claims are FROZEN LISTS asserted as equalities — a number somebody raises
means nothing, a named list can only shrink, and a claim cannot be moved from `proven`
to `commitment` to avoid writing the test without that showing up in this file.

THE VERIFY CLAUSE, as tests: adding "SSO for every plan" to a marketing file makes the
check fail, and removing it passes (`test_an_unmapped_sentence_is_named_*`).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests import _marketing_claims as ledger
from tests._marketing_copy import MARKETING, copy_sentences
from tests._marketing_vocabulary import EXEMPT_PREFIXES, is_exempt, topics_of

API_ROOT = Path(__file__).resolve().parents[1]

# What the owner has still to decide. A claim leaves this list when it is built, proved
# or removed from the site — in the same commit — and joins it only by being written here.
UNPROVEN_CLAIMS = {"sso", "database-encrypted", "sla-and-account-manager"}

# Facts no test can read. Frozen for the same reason: "commitment" must not become the
# place a hard-to-test claim goes to stop being tested.
COMMITMENT_CLAIMS = {"database-in-mumbai", "support-service", "onboarding-service"}


# ── the two halves, as pure functions so the verify clause can be exercised ───

def detected(copy: dict[str, set[str]]) -> dict[str, tuple[str, ...]]:
    """{sentence: non-exempt files} for every sentence that is a capability claim."""
    out: dict[str, tuple[str, ...]] = {}
    for sentence, files in copy.items():
        live = tuple(sorted(f for f in files if not is_exempt(f)))
        if live and topics_of(sentence):
            out[sentence] = live
    return out


def ledger_sentences() -> dict[str, tuple[str, ...]]:
    """{sentence: files} as the ledger records them; one entry per sentence."""
    out: dict[str, tuple[str, ...]] = {}
    for claim in ledger.CLAIMS:
        for says in claim.says:
            previous = out.setdefault(says.text, says.where)
            assert previous == says.where, (
                f"{says.text!r} is listed under two claims with different files: "
                f"{previous} against {says.where}")
    return out


def unmapped(found: dict[str, tuple[str, ...]], known: dict[str, tuple[str, ...]]) -> list[str]:
    return sorted(set(found) - set(known))


def stale(found: dict[str, tuple[str, ...]], known: dict[str, tuple[str, ...]]) -> list[str]:
    return sorted(set(known) - set(found))


@pytest.fixture(scope="module")
def site() -> dict[str, tuple[str, ...]]:
    return detected(copy_sentences(2))


# ── the sweep reads the site ─────────────────────────────────────────────────

def test_the_sweep_reads_the_site(site):
    copy = copy_sentences(2)
    assert len(copy) > 600, "the marketing copy was not found — the guard would be vacuous"
    assert len(site) >= 90, (
        f"only {len(site)} capability sentences detected — the vocabulary or the extractor "
        "stopped seeing the site, and an empty sweep passes for ever")
    assert len(ledger.CLAIMS) >= 30


@pytest.mark.parametrize("prefix,reason", EXEMPT_PREFIXES)
def test_an_exemption_names_a_directory_that_holds_files(prefix, reason):
    folder = MARKETING / prefix
    assert reason, "an exemption states why"
    assert folder.is_dir() and any(folder.rglob("*.tsx")), (
        f"{prefix} holds nothing: an exemption for a path that does not exist is a "
        "way to exempt a file added there later without anybody deciding to")


# ── the guard ────────────────────────────────────────────────────────────────

def test_every_capability_sentence_is_in_the_ledger(site):
    missing = unmapped(site, ledger_sentences())
    assert not missing, (
        "These sentences promise something about what the product does, how it protects "
        "data or what the vendor will do, and the claims ledger does not know them.\n"
        "Add each to a claim in tests/_marketing_claims.py (with the test that proves the "
        "fact), or — if the fact is not true — reword the sentence. Do not loosen the "
        "vocabulary.\n\n"
        + "\n".join(f"  - {s!r}\n      in {', '.join(site[s])}" for s in missing))


def test_every_ledger_sentence_is_still_on_the_site(site):
    gone = stale(site, ledger_sentences())
    assert not gone, (
        "These ledger sentences are no longer on the site as written — they were removed "
        "or reworded. Update the ledger in the same commit, so the new wording is reviewed "
        "against its proof rather than inheriting the old one:\n"
        + "\n".join(f"  - {s!r}" for s in gone))


def test_where_a_sentence_appears_is_what_the_ledger_says(site):
    wrong = [(s, files, site[s]) for s, files in ledger_sentences().items()
             if s in site and files != site[s]]
    assert not wrong, (
        "A sentence is now made in a different set of files than the ledger records — a "
        "new place the claim is made:\n"
        + "\n".join(f"  - {s!r}\n      ledger {a}\n      site   {b}" for s, a, b in wrong))


# ── the verify clause ────────────────────────────────────────────────────────

def test_an_unmapped_sentence_is_named_and_removing_it_passes(site):
    """'SSO for every plan' added to a marketing file makes the check fail; taking it out
    makes it pass. Exercised on the same pure functions the guard above runs."""
    sentence = "SSO for every plan"
    copy = copy_sentences(2)
    copy[sentence] = {"app/(site)/pricing/page.tsx"}
    with_it = detected(copy)
    assert sentence in with_it, "the vocabulary no longer recognises SSO as a capability claim"
    assert unmapped(with_it, ledger_sentences()) == [sentence]
    del copy[sentence]
    assert unmapped(detected(copy), ledger_sentences()) == []


@pytest.mark.parametrize("sentence", [
    "SSO for every plan",
    "Single sign-on (SSO)",
    "SOC 2 Type II certified",
    "99.9% uptime guaranteed",
    "Bank-grade encryption for every client file",
    "Integrates with Zoho Books and Razorpay",
    "Syncs live with your bank every night",
    "Files your GST return for you in one click",
    "One-click e-filing for every return",
    "Auto-submits to the GST portal on the due date",
    "Automatic WhatsApp reminders to your clients",
    "Webhooks for every event in the practice",
    "Two-factor on every sign-in",
    "Your data is stored in India",
    "24/7 phone support",
    "Penetration tested every quarter",
    "Clients upload their documents to the portal",
    "Import your ledgers and journals from Tally",
])
def test_the_vocabulary_catches_what_it_is_for(sentence):
    assert topics_of(sentence), f"{sentence!r} would pass the site unreviewed"


@pytest.mark.parametrize("sentence", [
    "Start free trial",
    "Book a demo",
    "Client portal",
    "Is there a free trial?",
    "Does PracticeSync file returns for me?",
    "Simple pricing for firms of every size.",
    "Billed monthly · save ~2 months on annual",
    "GSTR-1 — 11th of the following month",
    "What's included",
])
def test_the_vocabulary_leaves_a_label_a_question_and_a_price_alone(sentence):
    assert not topics_of(sentence), f"{sentence!r} is not a promise"


# ── the entries themselves ───────────────────────────────────────────────────

def test_a_claim_is_named_once_and_says_each_sentence_once():
    ids = [c.id for c in ledger.CLAIMS]
    assert len(ids) == len(set(ids)), "two claims share an id"
    for claim in ledger.CLAIMS:
        texts = [s.text for s in claim.says]
        assert len(texts) == len(set(texts)), f"{claim.id} lists a sentence twice"
        assert claim.fact.strip(), claim.id


def test_every_ledger_sentence_belongs_to_a_topic_of_the_vocabulary():
    """An entry for a sentence the vocabulary does not call a claim is noise that makes the
    equality above unreachable — it could never be 'detected'."""
    for claim in ledger.CLAIMS:
        for says in claim.says:
            assert topics_of(says.text), f"{claim.id}: {says.text!r} is not a capability sentence"


def _tests_defined_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


@pytest.mark.parametrize("claim", [c for c in ledger.CLAIMS if c.proofs], ids=lambda c: c.id)
def test_every_proof_names_a_test_that_exists(claim):
    for proof in claim.proofs:
        assert "::" in proof, f"{claim.id}: {proof!r} is not file::test"
        rel, name = proof.split("::", 1)
        path = API_ROOT / rel
        assert path.name.startswith("test_") and path.suffix == ".py", f"{claim.id}: {rel} is not a test module"
        assert path.is_file(), f"{claim.id}: {rel} does not exist — the claim points at nothing"
        assert name.startswith("test_") and name in _tests_defined_in(path), (
            f"{claim.id}: {rel} defines no {name} — it was renamed or deleted, so what "
            "proves this claim now?")


def test_a_proof_is_not_a_test_that_only_reads_the_site():
    """The marketing guards prove the SENTENCE is present, which is the wrong direction for
    a fact — except for the few sentences whose whole claim is 'the site says X' (the MFA
    scope and the hosting regions), which are allowed by name."""
    allowed = {
        "test_the_mfa_sentence_names_who_is_asked",
        "test_the_render_region_the_site_names_is_the_one_render_uses",
        "test_the_hosting_sentence_names_the_database_and_the_rest",
        "test_the_site_does_not_make_this_claim",
        "test_the_product_is_described_the_same_way_everywhere",
    }
    own = {"test_the_marketing_site_does_not_claim_what_the_code_does_not_do.py",
           "test_the_marketing_site_says_what_the_product_does.py"}
    for claim in ledger.CLAIMS:
        for proof in claim.proofs:
            rel, name = proof.split("::", 1)
            if Path(rel).name in own:
                assert name in allowed, (
                    f"{claim.id}: {proof} reads the marketing copy, not the product — "
                    "name a test that pins the FACT")


# ── the ratchets ─────────────────────────────────────────────────────────────

def test_the_unproven_claims_are_exactly_the_ones_the_owner_has_yet_to_decide():
    now = {c.id for c in ledger.CLAIMS if c.status == ledger.UNPROVEN}
    assert now == UNPROVEN_CLAIMS, (
        f"unproven claims are {sorted(now)}, the list says {sorted(UNPROVEN_CLAIMS)}. "
        "A claim that is now proved, built or removed comes OFF the list in this commit; "
        "one that joins it is a promise on the public site nothing backs, and says so here.")


def test_the_commitments_are_exactly_the_ones_no_test_can_read():
    now = {c.id for c in ledger.CLAIMS if c.status == ledger.COMMITMENT}
    assert now == COMMITMENT_CLAIMS, (
        f"commitments are {sorted(now)}, the list says {sorted(COMMITMENT_CLAIMS)}")


def test_an_unproven_claim_is_still_visible_on_the_site_it_is_asked_about():
    """The decision is only live while the sentence is. If the bullet is removed the claim
    must be deleted from the ledger, not left as an open question about nothing."""
    on_site = set(detected(copy_sentences(2)))
    for claim in ledger.CLAIMS:
        if claim.status == ledger.UNPROVEN:
            assert any(s.text in on_site for s in claim.says), claim.id
