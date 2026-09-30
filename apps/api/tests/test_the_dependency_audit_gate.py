"""The dependency audit gate fails on what is NEW, and never calls a tool that did not run "clean" (engineering-05).

WHY THE GATE IS A RATCHET (the long version is audit_gate.py's header)
    On 30-09-2026 the backend resolved to 87 packages with 30 advisories in 5 of them, apps/web had 70
    production advisories (2 critical) and apps/marketing 28. A step that failed on any advisory would have
    been red from its first run. So the gate fails on an advisory the reviewed baseline does not name.

WHAT THESE TESTS PIN
    1. It reads the REAL shapes: the two fixtures are trimmed from the actual pip-audit and pnpm reports.
    2. A finding is matched by ANY of its names: pip-audit and pnpm use different ones for one advisory.
    3. Severity: pnpm is gated at a threshold and pip-audit, which reports none, counts everything.
    4. A report that is missing, is not JSON, or audited NOTHING is exit 2 and never "clean". An empty audit
       passes every check in the world.
    5. The baseline can only be written in one shape, with no duplicate and no stray text.
    6. Round trip: printing a baseline from a report and reading it back gives "nothing new" — which is what
       makes the committed baselines reproducible by a human.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "audit"


def _load():
    spec = importlib.util.spec_from_file_location("audit_gate", API / "scripts" / "ci" / "audit_gate.py")
    mod = importlib.util.module_from_spec(spec)
    # Registered BEFORE it runs: @dataclass looks its own module up in sys.modules to resolve postponed
    # annotations, and a module loaded by path is not there until it is put there.
    sys.modules["audit_gate"] = mod
    spec.loader.exec_module(mod)
    return mod


gate = _load()
PIP = json.loads((FIXTURES / "pip-audit-sample.json").read_text(encoding="utf-8"))
PNPM = json.loads((FIXTURES / "pnpm-audit-sample.json").read_text(encoding="utf-8"))


def _ids(findings):
    return sorted(f.primary for f in findings)


# ── 1. the real shapes ──────────────────────────────────────────────────────────

def test_the_fixtures_carry_the_keys_the_gate_reads():
    """Vacuity guard. If the fixtures drift from what the tools emit, every test below is about nothing."""
    dep = next(d for d in PIP["dependencies"] if d["vulns"])
    assert {"name", "version", "vulns"} <= set(dep)
    assert {"id", "fix_versions", "aliases", "description"} <= set(dep["vulns"][0])
    adv = next(iter(PNPM["advisories"].values()))
    assert {"github_advisory_id", "severity", "module_name", "patched_versions", "findings", "title"} <= set(adv)
    assert PNPM["metadata"]["totalDependencies"] > 0


def test_pip_findings_count_an_advisory_once_and_carry_its_aliases():
    findings = gate.pip_findings(PIP)
    # The fixture lists one of gunicorn's two advisories TWICE, the way pip-audit does.
    assert len(findings) == 2
    assert all(f.package == "gunicorn" and f.severity is None for f in findings)
    first = findings[0]
    assert first.primary in first.ids and len(first.ids) >= 2, "an advisory goes by more than one name"


def test_pnpm_findings_carry_severity_and_the_ghsa_id():
    findings = {f.primary: f for f in gate.pnpm_findings(PNPM)}
    assert set(findings) == {"GHSA-P293-QW3H-JR36", "GHSA-4R6H-8V6P-XVW6", "GHSA-9G9P-9GW9-JX7F"}
    assert {f.severity for f in findings.values()} == {"critical", "high", "moderate"}


# ── 2. any of its names ─────────────────────────────────────────────────────────

def test_a_baseline_line_may_carry_any_name_the_advisory_goes_by():
    findings = gate.pip_findings(PIP)
    alias = sorted(findings[0].ids - {findings[0].primary})[0]
    base = {alias: "by its alias", findings[1].primary: "by its id"}
    verdict = gate.judge(findings, base, None)
    assert verdict.new == () and len(verdict.accepted) == 2


# ── 3. severity ─────────────────────────────────────────────────────────────────

def test_pnpm_is_gated_at_the_threshold_and_a_lower_severity_is_not_counted():
    findings = gate.pnpm_findings(PNPM)
    v = gate.judge(findings, {}, "high")
    assert sorted(f.severity for f in v.new) == ["critical", "high"]
    assert [f.severity for f in v.below] == ["moderate"]
    # ...and raising the bar to critical leaves one.
    assert [f.severity for f in gate.judge(findings, {}, "critical").new] == ["critical"]
    # ...and the moderate one is counted when the bar is lowered to it.
    assert len(gate.judge(findings, {}, "moderate").new) == 3


def test_pip_audit_reports_no_severity_so_every_unbaselined_advisory_counts():
    findings = gate.pip_findings(PIP)
    # A floor is irrelevant to a finding with no severity: it is never "below" it.
    assert len(gate.judge(findings, {}, None).new) == 2
    assert len(gate.judge(findings, {}, "critical").new) == 2


def test_an_accepted_advisory_is_not_new_and_a_stale_baseline_line_is_named():
    findings = gate.pnpm_findings(PNPM)
    base = {"GHSA-P293-QW3H-JR36": "x", "GHSA-0000-0000-0000": "an upgrade removed this one"}
    v = gate.judge(findings, base, "high")
    assert [f.primary for f in v.new] == ["GHSA-4R6H-8V6P-XVW6"]
    assert [f.primary for f in v.accepted] == ["GHSA-P293-QW3H-JR36"]
    assert v.stale == ("GHSA-0000-0000-0000",)


def test_a_fixed_advisory_goes_stale_and_does_not_fail_the_run(tmp_path, capsys):
    """The ratchet is one-directional: a baseline line for something already upgraded is a NOTE to delete it, not a
    failure — otherwise merging an upgrade would turn CI red until somebody tidied a text file."""
    v = gate.judge(gate.pnpm_findings(PNPM), {"GHSA-FFFF-FFFF-FFFF": "gone"}, "critical")
    assert v.stale == ("GHSA-FFFF-FFFF-FFFF",)
    baseline = "GHSA-P293-QW3H-JR36\nGHSA-4R6H-8V6P-XVW6\nGHSA-FFFF-FFFF-FFFF  # upgraded away\n"
    assert _run(tmp_path, "pnpm", PNPM, baseline) == 0
    out = capsys.readouterr().out
    assert "GHSA-FFFF-FFFF-FFFF" in out and "delete them" in out


# ── 4. a tool that did not run ─────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [None, [], "text", {}, {"dependencies": "nope"}, {"dependencies": []}])
def test_a_pip_report_that_audited_nothing_is_refused(bad):
    with pytest.raises(gate.AuditError):
        gate.pip_findings(bad)


@pytest.mark.parametrize("bad", [
    None, [], {}, {"error": {"code": "ERR_PNPM_AUDIT_BAD_RESPONSE", "message": "registry"}},
    {"advisories": {}, "metadata": {"totalDependencies": 0}},
    {"advisories": {}, "metadata": {}},
])
def test_a_pnpm_report_that_audited_nothing_is_refused(bad):
    """`{"error": ...}` is what a registry failure prints. `advisories: {}` over ZERO dependencies is the
    wrong-directory case — and both would otherwise read as a spotless result."""
    with pytest.raises(gate.AuditError):
        gate.pnpm_findings(bad)


def test_a_clean_audit_of_real_dependencies_is_fine_and_is_not_refused():
    v = gate.judge(gate.pnpm_findings({"advisories": {}, "metadata": {"totalDependencies": 12}}), {}, "high")
    assert v.new == () and v.accepted == ()


def test_an_advisory_with_no_id_to_match_on_is_refused_not_ignored():
    bad = json.loads(json.dumps(PNPM))
    key = next(iter(bad["advisories"]))
    bad["advisories"][key]["github_advisory_id"] = None
    bad["advisories"][key]["cves"] = []
    with pytest.raises(gate.AuditError, match="no GHSA or CVE id"):
        gate.pnpm_findings(bad)


def test_an_unknown_severity_is_refused_not_guessed():
    bad = json.loads(json.dumps(PNPM))
    bad["advisories"][next(iter(bad["advisories"]))]["severity"] = "catastrophic"
    with pytest.raises(gate.AuditError, match="unknown severity"):
        gate.pnpm_findings(bad)


def _run(tmp_path, kind, report, baseline="", *extra, env=None):
    rep = tmp_path / "report.json"
    if report is not None:
        rep.write_text(report if isinstance(report, str) else json.dumps(report), encoding="utf-8")
    base = tmp_path / "baseline.txt"
    base.write_text(baseline, encoding="utf-8")
    return gate.main(["--kind", kind, "--report", str(rep), "--baseline", str(base), *extra], env=env or {})


def test_exit_codes_are_0_clean_1_new_and_2_did_not_run(tmp_path, capsys):
    assert _run(tmp_path, "pnpm", PNPM, "GHSA-P293-QW3H-JR36\nGHSA-4R6H-8V6P-XVW6\n") == 0
    assert _run(tmp_path, "pnpm", PNPM, "GHSA-P293-QW3H-JR36\n") == 1
    out = capsys.readouterr().out
    assert "NEW" in out and "GHSA-4R6H-8V6P-XVW6" in out and "fix:" in out

    assert _run(tmp_path, "pip", None) == 2, "a report file that was never written"
    assert _run(tmp_path, "pip", "<html>502 Bad Gateway</html>") == 2, "not JSON"
    assert _run(tmp_path, "pip", {"dependencies": []}) == 2, "audited nothing"
    assert _run(tmp_path, "pnpm", {"error": {"code": "ERR_X"}}) == 2, "a registry failure"
    # ...and a baseline that is itself malformed is the same kind of refusal, not a pass.
    assert _run(tmp_path, "pnpm", PNPM, "not an id at all\n") == 2


def test_the_log_says_when_it_ran_under_github_actions_and_writes_the_step_summary(tmp_path, capsys):
    summary = tmp_path / "summary.md"
    code = _run(tmp_path, "pnpm", PNPM, "", env={"GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": str(summary)})
    assert code == 1
    out = capsys.readouterr().out
    assert "::error title=New vulnerable dependency::" in out
    text = summary.read_text(encoding="utf-8")
    assert "Dependency audit" in text and "GHSA-P293-QW3H-JR36" in text

    assert _run(tmp_path, "pip", None, env={"GITHUB_ACTIONS": "true"}) == 2
    assert "::error title=Dependency audit did not run::" in capsys.readouterr().out


def test_min_severity_is_honoured_on_the_command_line(tmp_path):
    only_moderate_left = "GHSA-P293-QW3H-JR36\nGHSA-4R6H-8V6P-XVW6\n"
    assert _run(tmp_path, "pnpm", PNPM, only_moderate_left, "--min-severity", "high") == 0
    assert _run(tmp_path, "pnpm", PNPM, only_moderate_left, "--min-severity", "moderate") == 1


# ── 5. the baseline's own shape ─────────────────────────────────────────────────

def test_a_baseline_holds_one_id_per_line_and_comments():
    text = "# a header\n\nGHSA-AAAA-BBBB-CCCC   # pkg 1.0 [high] — a title\nPYSEC-2026-12\n   \n# trailing\n"
    assert gate.read_baseline(text) == {"GHSA-AAAA-BBBB-CCCC": "pkg 1.0 [high] — a title", "PYSEC-2026-12": ""}


def test_a_duplicate_or_malformed_baseline_line_is_refused():
    with pytest.raises(gate.AuditError, match="listed twice"):
        gate.read_baseline("GHSA-AAAA-BBBB-CCCC\nghsa-aaaa-bbbb-cccc  # same id, different case\n")
    with pytest.raises(gate.AuditError, match="not an advisory id"):
        gate.read_baseline("please upgrade starlette\n")


# ── 6. the round trip ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,report,floor", [("pip", PIP, None), ("pnpm", PNPM, "moderate")])
def test_a_printed_baseline_read_back_leaves_nothing_new(kind, report, floor):
    findings = gate.pip_findings(report) if kind == "pip" else gate.pnpm_findings(report)
    printed = gate.render_baseline(findings)
    base = gate.read_baseline(printed)
    assert len(base) == len(findings)
    v = gate.judge(findings, base, floor)
    assert v.new == () and v.stale == ()


def test_print_baseline_prints_only_what_the_gate_would_count(tmp_path, capsys):
    rep = tmp_path / "r.json"
    rep.write_text(json.dumps(PNPM), encoding="utf-8")
    assert gate.main(["--kind", "pnpm", "--report", str(rep), "--baseline", "/dev/null",
                      "--print-baseline", "--min-severity", "high"], env={}) == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(lines) == 2 and all("[moderate]" not in l for l in lines)
