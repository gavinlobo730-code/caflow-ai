"""Every AI feature is named as PracticeSync AI on a screen, and its provider is named beside it (POST-A-448).

The owner asked on 16-11-2026 why the AI status page led with model codes instead of presenting the AI as the
product's own. The usage table showed each feature by its internal key (`invoice_extraction`) and its provider by an
id (`groq`). `domain/ai/budget.fold` now serves a name for each, and these tests hold the names to the code: every
feature the code records a call under has one, and a provider is named by the name the status page shows, because it is
the company that receives a CA's content and is never hidden behind the product's name.
"""
from __future__ import annotations

import pathlib
import re

from domain.ai import budget, gateway

API = pathlib.Path(__file__).resolve().parent.parent

#: `feature="..."` as a keyword argument in the production tree: what the gateway records each call under.
_FEATURE_KWARG = re.compile(r"""\bfeature\s*=\s*["']([a-z_]+)["']""")


def _features_the_code_records() -> set[str]:
    found: set[str] = set()
    for root in ("domain", "services", "routers", "jobs"):
        for path in (API / root).rglob("*.py"):
            if path == API / "domain" / "ai" / "budget.py":
                continue  # budget.check's own `feature="usage"` names no model call
            found |= set(_FEATURE_KWARG.findall(path.read_text(encoding="utf-8")))
    return found


def test_the_scan_finds_the_features_and_is_not_vacuous():
    found = _features_the_code_records()
    assert {"assistant", "firm_copilot", "invoice_extraction", "statement_scan"} <= found, found


def test_every_feature_the_code_records_has_a_name_with_the_products_name_in_it():
    missing = sorted(_features_the_code_records() - set(budget.FEATURE_LABELS))
    assert not missing, f"a feature records calls and has no name on the usage table: {missing}"
    for key, label in budget.FEATURE_LABELS.items():
        assert label.startswith("PracticeSync AI"), (key, label)


def test_no_name_is_kept_for_a_feature_the_code_no_longer_records():
    stale = sorted(set(budget.FEATURE_LABELS) - _features_the_code_records())
    assert not stale, f"named and never recorded: {stale}"


def test_a_provider_is_named_as_the_status_page_names_it():
    assert budget.PROVIDER_LABELS == {"groq": gateway.GROQ.name, "gemini": gateway.GEMINI.name}


def test_the_fold_serves_the_names_and_keeps_the_keys_and_the_models():
    rows = [{"feature": "invoice_extraction", "provider": "gemini", "model": "m-1", "calls": 2},
            {"feature": "something_new", "provider": "other", "model": "m-2", "calls": 1}]
    folded = budget.fold([], rows)
    by_key = {r["feature"]: r for r in folded["by_feature"]}
    named = by_key["invoice_extraction"]
    assert named["label"] == budget.FEATURE_LABELS["invoice_extraction"]
    assert named["provider_label"] == gateway.GEMINI.name
    assert named["models"] == ["m-1"], "the model codes still travel, for Technical details"
    unknown = by_key["something_new"]
    assert unknown["label"] is None and unknown["provider_label"] is None, \
        "a feature or provider with no name is shown by its key, never given a guessed name"
