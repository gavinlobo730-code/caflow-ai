"""The sentence the API refuses a stale authenticator code with is the sentence the platform page recognises
(POST-A-484). The browser decides to ask for a code by that sentence, so the two copies are pinned to each other, the
way the multi-factor refusal's are (`tests/test_the_mfa_policy_reaches_the_people_it_locks_out.py`)."""
import re
from pathlib import Path

from core.auth_time import FRESH_CODE_SENTENCE

WEB = Path(__file__).resolve().parents[2] / "web" / "lib" / "auth" / "freshCode.ts"


def test_the_browser_holds_the_same_sentence():
    src = WEB.read_text(encoding="utf-8")
    m = re.search(r'FRESH_CODE_SENTENCE\s*=\s*\n?\s*"([^"]+)"', src)
    assert m, "lib/auth/freshCode.ts does not export FRESH_CODE_SENTENCE"
    assert m.group(1) == FRESH_CODE_SENTENCE
