"""AS 18 — who the note names, and what it refuses to guess.

The defect this pins: `related_party_report`'s test was a literal set of six
role names, against a client screen that offers ELEVEN. So a Karta of an HUF,
a Proprietor and a Beneficiary of a trust were dropped from a statutory
disclosure in silence. A note that omits a related party is a WRONG note.

⚠️ EVERY THRESHOLD IS `[S]`-GRADED — egress is refused at this environment's
proxy, so AS 18's text is recorded from knowledge rather than read. Each
figure is pinned EXACTLY below, so a later correction is a deliberate edit
rather than a drift. `disclosure.VERIFIED` is False and a test asserts it,
because promoting it is a claim about provenance and must be made on purpose.
"""
import pytest

from domain.related_party import disclosure as d


# ── the constants, pinned exactly ────────────────────────────────────────────

def test_the_module_does_not_claim_to_be_verified():
    assert d.VERIFIED is False


def test_significant_influence_is_twenty_percent():
    assert d.SIGNIFICANT_INFLUENCE_PERCENT == 20


def test_the_transfer_pricing_threshold_is_one_crore_in_paise():
    assert d.TRANSFER_PRICING_THRESHOLD_PAISE == 1_00_00_000_00
    # Read the other way round, because the literal's underscores are grouped
    # the Indian way and are easy to miscount: one crore RUPEES, in paise.
    assert d.TRANSFER_PRICING_THRESHOLD_PAISE == 1_00_00_000 * 100


# ── the three the old literal set dropped ────────────────────────────────────

@pytest.mark.parametrize("role", ["Karta (HUF)", "Proprietor", "Beneficiary"])
def test_the_roles_the_old_set_dropped_are_related_parties(role):
    """The regression this module exists for. Each was offered by the screen
    and absent from the report's literal set, so each vanished from the note
    without a word."""
    rule = d.standing_for(role, None)
    assert rule.standing is d.Standing.INCLUDED, role
    assert rule.reason, "an included party must carry the reason printed beside it"


@pytest.mark.parametrize("role", ["Director", "Partner", "Trustee", "Manager"])
def test_the_roles_that_were_already_right_stay_right(role):
    assert d.standing_for(role, None).standing is d.Standing.INCLUDED


# ── the three answers are three, and none collapses into another ─────────────

def test_a_guarantor_is_not_a_related_party_by_that_role_alone():
    rule = d.standing_for("Guarantor", None)
    assert rule.standing is d.Standing.EXCLUDED
    assert "director" in rule.reason.lower(), (
        "the reason must say a director who guarantees is caught as a director, "
        "or a reader concludes guarantors are simply ignored"
    )


def test_an_authorised_signatory_is_undetermined_rather_than_guessed():
    rule = d.standing_for("Authorized Signatory", None)
    assert rule.standing is d.Standing.UNDETERMINED


def test_an_unknown_role_is_undetermined_and_never_silently_dropped():
    rule = d.standing_for("Company Secretary's Cousin", None)
    assert rule.standing is d.Standing.UNDETERMINED
    assert rule.reason


def test_the_three_standings_carry_three_different_reasons():
    """On the ANSWERS, not on the data — so moving a role between buckets
    cannot make this vacuous."""
    reasons = {
        d.standing_for("Director", None).reason,
        d.standing_for("Guarantor", None).reason,
        d.standing_for("Authorized Signatory", None).reason,
    }
    assert len(reasons) == 3


# ── a shareholder turns on the holding, not the label ────────────────────────

def test_a_small_shareholder_is_not_a_related_party():
    rule = d.standing_for("Shareholder", 1)
    assert rule.standing is d.Standing.EXCLUDED
    assert "1%" in rule.reason and "20%" in rule.reason


def test_a_shareholder_at_the_threshold_is_included():
    """At, not above: significant influence is taken from 20% inclusive, and a
    strict `>` would exclude a holding of exactly 20%."""
    assert d.standing_for("Shareholder", 20).standing is d.Standing.INCLUDED
    assert d.standing_for("Shareholder", 19.99).standing is d.Standing.EXCLUDED


def test_a_shareholder_with_no_holding_recorded_is_undetermined():
    """Both guesses are wrong in the ordinary case: assuming IN inflates a
    statutory note with every name on the register, assuming OUT hides a
    controlling shareholder."""
    rule = d.standing_for("Shareholder", None)
    assert rule.standing is d.Standing.UNDETERMINED
    assert "no holding is recorded" in rule.reason.lower()


def test_a_directors_holding_does_not_change_their_standing():
    """A director is key management personnel whether or not they hold a
    share, so ownership must not be consulted for a role it does not decide."""
    for pct in (None, 0, 1, 51):
        assert d.standing_for("Director", pct).standing is d.Standing.INCLUDED


# ── the note ─────────────────────────────────────────────────────────────────

def _party(name, role, *, pan="AAAAA1111A", pct=None, dealings=None):
    rule = d.standing_for(role, pct)
    return d.Party(
        entity_id=f"e-{name}", name=name, pan=pan, role=role,
        ownership_percent=pct, standing=rule.standing, reason=rule.reason,
        dealings=dealings,
    )


def _build(parties, **kw):
    return d.build(
        client_id="c1", parties=parties,
        section_185_loans=kw.get("loans", []),
        transfer_pricing_flags=kw.get("tp", []),
        entity_relationships=kw.get("edges", []),
    )


def test_disclosure_is_required_by_a_party_existing_not_by_a_figure():
    """AS 18 asks for the relationship to be disclosed where control exists,
    whether or not anything was transacted."""
    note = _build([_party("A Director", "Director",
                          dealings=d.Dealings(matched_on_pan=True))])
    assert note.disclosure_required is True
    assert note.included and not note.undetermined


def test_an_undetermined_party_does_not_make_a_disclosure_required():
    note = _build([_party("Somebody", "Authorized Signatory")])
    assert note.disclosure_required is False
    assert note.undetermined


def test_a_party_with_no_pan_is_named_rather_than_reported_as_nil():
    note = _build([_party("No PAN Ltd", "Director", pan=None)])
    assert any("No PAN Ltd" in g for g in note.gaps)
    assert any("absent rather than nil" in g for g in note.gaps)


def test_a_matched_party_raises_no_unmatched_gap():
    note = _build([_party("Matched", "Director",
                          dealings=d.Dealings(matched_on_pan=True))])
    assert not any("No PAN is recorded" in g for g in note.gaps)


def test_undetermined_parties_are_named_and_held_out_of_the_note():
    note = _build([_party("Maybe", "Authorized Signatory")])
    assert any("could not be decided" in g for g in note.gaps)
    assert any("NOT in the note above" in g for g in note.gaps)


def test_every_note_carries_the_standing_gaps_whatever_it_found():
    """A nil beside a heading must never read as "there were none"."""
    for parties in ([], [_party("A", "Director", dealings=d.Dealings(True))]):
        note = _build(parties)
        for g in d.STANDING_GAPS:
            assert g in note.gaps


def test_relatives_are_named_as_the_largest_gap():
    note = _build([])
    assert any("RELATIVES" in g for g in note.gaps)


def test_the_note_says_it_is_as_18_and_not_ind_as_24():
    note = _build([])
    assert any("Ind AS 24" in n for n in note.notes)


def test_the_note_says_nothing_is_filed_or_posted():
    note = _build([])
    assert any("filed" in n.lower() for n in note.notes)


# ── vacuity controls ─────────────────────────────────────────────────────────

def test_the_role_map_covers_every_role_the_screen_offers():
    """The premise. If the screen grows a role, it must get a rule or this
    fails — which is the whole mechanism the literal set lacked.

    The list is the client screen's own dropdown, transcribed. It is asserted
    to be NON-EMPTY first, so a future edit that empties it cannot make the
    loop below vacuous.
    """
    screen_offers = [
        "Director", "Shareholder", "Partner", "Trustee", "Proprietor",
        "Guarantor", "Authorized Signatory", "Karta (HUF)", "Beneficiary",
        "Manager", "Other",
    ]
    assert len(screen_offers) == 11
    for role in screen_offers:
        rule = d.standing_for(role, None)
        assert isinstance(rule.standing, d.Standing)
        assert rule.reason, f"{role} resolves with no reason to print"


def test_a_role_absent_from_the_map_still_gets_a_reason():
    """The negative control for the test above: `standing_for` must answer for
    a role nobody listed, or "covers every role" is satisfied by a lookup that
    would KeyError on the twelfth."""
    assert d.standing_for("Other", None).reason == d.UNKNOWN_ROLE.reason


def test_role_lookup_is_exact_and_trims_only_whitespace():
    """`ROLE_RULES` is keyed on what the screen stores. Trimming is safe;
    case-folding is not offered, because "director" reaching the Director rule
    would also make "DIRECTOR" reach it and the column has one spelling."""
    assert d.standing_for("  Director  ", None).standing is d.Standing.INCLUDED
    assert d.standing_for("director", None).standing is d.Standing.UNDETERMINED
