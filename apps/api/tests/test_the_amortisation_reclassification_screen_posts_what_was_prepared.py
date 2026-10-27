"""The amortisation reclassification screen posts the preview the Partner looked at, and nothing it worked out itself (POST-A-345, stage 3).

WHY A SOURCE GUARD. The server holds every rule (`services/amortisation_reclass_service`): which assets move, what each entry is made of,
which dates they carry, every refusal. What is left for the browser to get wrong is the HANDOFF, and each of these is a wrong posting
rather than a wrong label:

    * posting a preview under a date or a ledger other than the one it was made for (the Partner edits the date after preparing, and
      the post sends the box and not the preview);
    * a post button the preview did not enable, or one a non-Partner can press;
    * a date defaulted for the Partner, when the date decides which balance sheets change;
    * a figure worked out in the browser (the server serves every total, count and date the confirmation sentence uses);
    * the ledger list taken from the accounts endpoint, which offers Cash in Hand, instead of from the server's candidates;
    * a second click on a button that writes.

It reads `apps/web/components/fixed-assets/AmortisationReclassification.tsx` as a browser-reading guard, so the `browser contract` CI job
selects it for a pull request that touches only the web app (`scripts/ci/tests_reading_the_browser.py`).
"""
from __future__ import annotations

import pathlib
import re

SCREEN = pathlib.Path(__file__).resolve().parents[2] / "web" / "components" / "fixed-assets" / "AmortisationReclassification.tsx"


def _source() -> str:
    text = SCREEN.read_text()
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//[^\n]*$", "", text)


def _between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def test_the_post_sends_the_date_and_ledger_the_preview_was_made_for_and_not_the_fields():
    src = _source()
    body = _between(src, "JSON.stringify({", "}),")
    assert "as_at: preview.as_at" in body and "preparedCarried" in body and "expected_total_paise: preview.total_to_move_paise" in body, body
    assert "asAt" not in body and "carriedId" not in body, "the fields can have been edited since the preview was made"
    assert "asset_ids: preview.assets.map" in body, "the assets are the preview's, not a selection made elsewhere"


def test_changing_the_date_throws_the_preview_away_and_choosing_a_ledger_prepares_again():
    src = _source()
    assert re.search(r"onChange=\{\(v\) => \{ setAsAt\(v\); discardPreview\(\); \}\}", src), "a date edit must discard the preview"
    assert re.search(r"onChange=\{\(e\) => \{ setCarriedId\(e\.target\.value\); void prepare\(e\.target\.value, true\); \}\}", src), \
        "choosing the ledger asks the server again, so the refusal and the figures are for that choice"


def test_the_post_button_needs_the_partners_permission_and_a_preview_the_server_called_ready():
    src = _source()
    assert 'can("accounting", "approve")' in src
    button = _between(src, "{canPost && preview.ready && (", "</Button>")
    assert "Post the reclassification" in button
    assert len(re.findall(r"Post the reclassification\s*</Button>", src)) == 1, "one post button"
    assert re.search(r"if \(!preview \|\| !preview\.ready \|\| preparing \|\| writing\.current\) return;", src), "the handler asks again, whatever is rendered"
    undo = _between(src, "{canPost && (\n                  <Button", "</Button>")
    assert "undo(" in undo, "the Undo button is a Partner's too"
    for handler in ("post()", "undo(a.asset_id, a.asset_code)", "prepare()"):
        assert f"onClick={{() => {handler}}}" in src, f"{handler}: a Button holds the promise it is handed, so a second click is ignored while it runs"


def test_a_button_that_writes_ignores_a_second_click():
    src = _source()
    for fn in ("async function post()", "async function undo("):
        body = src[src.index(fn):]
        body = body[:body.index("\n  }\n")]
        assert "writing.current = true" in body and "writing.current = false" in body, fn
        # the flag is READ before the request and again after the confirmation: assigning it alone stops nothing
        assert len(re.findall(r"if \([^\n]*writing\.current\) return", body)) >= 2, f"{fn}: the flag must be read before and after the confirm"


def test_the_date_is_never_defaulted_and_is_a_date_the_partner_typed():
    src = _source()
    assert 'useState("")' in src and re.search(r'\[asAt, setAsAt\] = useState\(""\)', src), "the as-at date starts empty"
    assert "todayLocalISO" not in src and "new Date(" not in src and "Date.now" not in src, "nothing here invents a date"
    assert "Say the date the reclassification is as at" in src, "an empty date is refused in words before any request"


def test_no_figure_the_confirmation_or_the_table_shows_is_worked_out_in_the_browser():
    src = _source()
    for needle in (" * 100", "/ 100", "toFixed", "Math.round", ".reduce(", "parseFloat", "Number(", "toLocaleString"):
        assert needle not in src, f"{needle!r}: the server serves every figure, count and date, and formatPaise/formatDate print them"
    assert "formatPaise(" in src and "formatDate(" in src
    assert "{preview.as_at}" not in src and "{result.as_at}" not in src, "a date a person reads goes through formatDate"


def test_the_ledgers_offered_are_the_servers_candidates_and_not_the_charts_accounts():
    src = _source()
    assert "/api/accounting/accounts" not in src and "assetLedgerChoices" not in src
    assert "preview.carried_over_candidates.map" in src and "preview.shared_ledger" in src, "the shared ledger is offered, and chosen on purpose"
    assert '<option value="">Choose the ledger…</option>' in src, "a blank is a question, never an answer"


def test_the_quiet_look_reads_the_summary_and_the_screen_says_when_the_chart_cannot_take_the_change():
    src = _source()
    assert "/api/fixed-assets/amortisation-reclassification/summary?client_id=" in src
    assert "summary?.refusal" in src, "the server's reason is shown, not a vanished panel"


def test_an_answer_that_is_not_the_newest_is_dropped_and_the_screen_is_remade_for_each_client():
    """A slow answer for an earlier date, ledger or client must never land on what the Partner is looking at now, and a client switch
    keeps the same component mounted unless it is keyed (the payroll page records the same fact)."""
    src = _source()
    assert src.count("mine !== prepareSeq.current") >= 2, "both the success and the failure of a prepare check they are still the newest"
    assert "mine === lookSeq.current" in src, "the summary's answer is checked the same way"
    assert "prepareSeq.current += 1" in src, "editing the date supersedes a prepare still on its way"
    page = (SCREEN.parents[2] / "app" / "clients" / "[id]" / "fixed-assets" / "page.tsx").read_text()
    assert "<AmortisationReclassification key={clientId}" in page, "state of the previous client is not carried over"


def test_post_is_held_off_while_the_server_is_being_asked_again():
    src = _source()
    assert "disabled={preparing}" in src and "|| preparing ||" in src
