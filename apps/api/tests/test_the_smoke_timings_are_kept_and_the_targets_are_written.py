"""The smoke run keeps its timings, a month of them makes a table, and the targets are written down (ops-12).

THE GAP
    `scripts/smoke_api.py` budgets are tripwires (20 s for the P&L). They fail a run that is badly wrong and are blind
    to a slow drift: the P&L can go from 1.5 s to 6 s over a month and never come near them. Nothing kept a run's
    response times, so "the reports feel slower lately" had no number behind it, and nothing said what "fast enough"
    was. `render.yaml`'s header holds the only readings, taken by hand once.

THE RULE, NOT A LIST OF TODAY'S STEPS
    * A budget FAILS ONE RUN; a target is judged over a month and FAILS NOTHING. Nothing here may turn a target into a
      gate: a number that fails a build on one unlucky sample is a number that gets ignored.
    * Every run that measured something leaves its timings, a failed run and a run in which the API never answered
      included, and the file holds NONE of what the run was given (a URL, a path, a client id, an address, a password):
      it is uploaded from a public repository.
    * A percentile is taken over the samples where the endpoint ANSWERED, so a 503 returning in 50 ms cannot flatter it;
      with too few samples the verdict says so; and the table says how many days it covers rather than calling a week
      a month.
    * Every check has a written target, no budget is tighter than twice its target, and the document's table and the
      code are the same table.

WHAT CANNOT BE ASSERTED HERE
    That GitHub keeps the artifact, that the run's token may list and download it, or that the summary page renders the
    table: no workflow can run from a mock-mode suite. The last step's SHELL is run here against a stand-in for `gh`, so
    its glue (which artifacts it picks, what it does when one will not download, that it never fails the run) is
    exercised; what is not is the API behind `gh`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]
sys.path.insert(0, str(API / "scripts"))
import smoke_api  # noqa: E402
import smoke_timings_report as report  # noqa: E402

WORKFLOW = REPO / ".github" / "workflows" / "smoke.yml"
DOC = REPO / "docs" / "operations" / "service-levels.md"

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)

# What a run is given. None of it may be in what the run keeps.
SECRETS = {
    "SMOKE_BASE_URL": "http://api-host-secret.example.test",
    "SUPABASE_URL": "http://supabase-secret.example.test",
    "SUPABASE_ANON_KEY": "anon-key-secret-value",
    "SMOKE_EMAIL": "ca-secret@example.test",
    "SMOKE_PASSWORD": "password-secret-123",
    "SMOKE_CLIENT_ID": "client-secret-uuid-0001",
}


# ── driving main() without a network ───────────────────────────────────────────

class _Clock:
    """A clock the handler can push forward, so a 'slow' answer is deterministic."""
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _drive(monkeypatch, tmp_path, *, handler=None, step=None, awake=(True, 1.2, "HTTP 200"),
           env=None, timings="timings/run.json"):
    """Run smoke_api.main() against a fake API. Returns (exit code, the timings path or None)."""
    clock = _Clock()
    monkeypatch.setattr(smoke_api.time, "monotonic", clock)
    step = step or (lambda path: 0.1)

    def default_handler(req: httpx.Request) -> httpx.Response:
        clock.t += step(req.url.path)
        return httpx.Response(200, json={"ok": True})

    real_client = httpx.Client
    monkeypatch.setattr(smoke_api.httpx, "Client", lambda *a, **k: real_client(
        transport=httpx.MockTransport(handler or default_handler), timeout=5))
    monkeypatch.setattr(smoke_api, "wake", lambda *a, **k: awake)
    monkeypatch.setattr(smoke_api, "sign_in", lambda *a, **k: "token")
    # Clear what a run may or may not carry, then set what it is given, and apply the
    # caller's own overrides LAST so a test can name any of them.
    for k in ("SMOKE_DEPLOYMENT", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_EVENT_NAME", "SMOKE_TIMINGS_FILE"):
        monkeypatch.delenv(k, raising=False)
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    path = None
    if timings:
        path = tmp_path / timings
        monkeypatch.setenv("SMOKE_TIMINGS_FILE", str(path))
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    return smoke_api.main, path


def _run(monkeypatch, tmp_path, **kw):
    main, path = _drive(monkeypatch, tmp_path, **kw)
    code = main()
    return code, path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ═══ 1. a run keeps its timings ═══════════════════════════════════════════════

def test_a_run_keeps_every_endpoints_time_budget_and_target(monkeypatch, tmp_path, capsys):
    code, path = _run(monkeypatch, tmp_path)
    assert code == 0
    data = _load(path)
    expected = smoke_api.checks("c", "2026-04-01", "2027-03-31")
    assert data["schema"] == smoke_api.TIMINGS_SCHEMA
    assert data["awake"] is True and data["all_passed"] is True
    assert [s["name"] for s in data["checks"]] == [c.name for c in expected]
    for sample, check in zip(data["checks"], expected, strict=True):
        assert isinstance(sample["elapsed_s"], float) and sample["elapsed_s"] > 0
        assert sample["budget_s"] == check.budget_s
        assert sample["target_s"] == check.target_s
        assert sample["status"] == 200 and sample["answered"] is True and sample["ok"] is True
    datetime.fromisoformat(data["generated_at"])
    assert data["deployment"] == "live"
    assert "timings written" in capsys.readouterr().out


def test_the_file_holds_none_of_what_the_run_was_given(monkeypatch, tmp_path):
    """It is uploaded from a PUBLIC repository. The checks' paths carry the client id, so only the NAME is kept."""
    _code, path = _run(monkeypatch, tmp_path)
    text = path.read_text(encoding="utf-8")
    for label, secret in SECRETS.items():
        assert secret not in text, f"{label} reached the timings file"
    assert "/api/" not in text and "client_id" not in text and "http" not in text


def test_a_run_that_failed_is_kept_and_says_which_check_did_not_answer(monkeypatch, tmp_path):
    def handler(req):
        if req.url.path.endswith("cash-flow"):
            return httpx.Response(500, json={"detail": "boom"})
        return httpx.Response(200, json={})
    code, path = _run(monkeypatch, tmp_path, handler=handler)
    assert code == 1
    data = _load(path)
    assert data["all_passed"] is False
    flow = next(s for s in data["checks"] if s["name"] == "accounting/cash-flow")
    assert flow["status"] == 500 and flow["answered"] is False and flow["ok"] is False
    assert all(s["answered"] for s in data["checks"] if s is not flow)


def test_an_over_budget_answer_is_kept_as_an_answer_that_failed(monkeypatch, tmp_path):
    """The most important latency sample there is: it answered, and slowly. It must stay IN the percentiles."""
    code, path = _run(monkeypatch, tmp_path,
                      step=lambda p: 25.0 if p.endswith("cash-flow") else 0.1)
    assert code == 1
    flow = next(s for s in _load(path)["checks"] if s["name"] == "accounting/cash-flow")
    assert flow["elapsed_s"] == 25.0 and flow["answered"] is True and flow["ok"] is False


def test_a_run_in_which_the_api_never_answered_is_kept_too(monkeypatch, tmp_path):
    code, path = _run(monkeypatch, tmp_path, awake=(False, 12.0, "ConnectError"))
    assert code == 1
    data = _load(path)
    assert data["awake"] is False and data["checks"] == [] and data["all_passed"] is False
    assert data["wake_detail"] == "ConnectError"


def test_a_run_with_no_credentials_measures_nothing_and_writes_nothing(monkeypatch, tmp_path, capsys):
    for k in SECRETS:
        monkeypatch.delenv(k, raising=False)
    path = tmp_path / "timings" / "run.json"
    monkeypatch.setenv("SMOKE_TIMINGS_FILE", str(path))
    assert smoke_api.main() == 0
    assert "skipped" in capsys.readouterr().out
    assert not path.exists() and not path.parent.exists()


def test_nothing_is_written_unless_a_path_is_given(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    code, _ = _run(monkeypatch, tmp_path, timings=None)
    assert code == 0
    assert list(tmp_path.iterdir()) == []


def test_a_file_that_cannot_be_written_never_changes_the_result(monkeypatch, tmp_path, capsys):
    """Telemetry about the check is not part of it: a full disk must not turn a green API red."""
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    code, _ = _run(monkeypatch, tmp_path, timings=None,
                   env={"SMOKE_TIMINGS_FILE": str(blocker / "sub" / "run.json")})
    assert code == 0
    assert "could not write the timings file" in capsys.readouterr().out


def test_the_deployment_is_live_unless_a_candidate_was_named(monkeypatch, tmp_path):
    _code, path = _run(monkeypatch, tmp_path, env={"SMOKE_DEPLOYMENT": "candidate"})
    assert _load(path)["deployment"] == "candidate"


def test_the_commit_run_and_event_come_from_the_environment(monkeypatch, tmp_path):
    main, path = _drive(monkeypatch, tmp_path)
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("GITHUB_RUN_ID", "987")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    main()
    data = _load(path)
    assert (data["commit"], data["run_id"], data["event"]) == ("abc123", "987", "schedule")


def test_a_cold_start_is_flagged_but_never_judged(monkeypatch, tmp_path):
    _code, path = _run(monkeypatch, tmp_path, awake=(True, 56.55, "HTTP 200"))
    data = _load(path)
    assert data["cold_start"] is True and data["wake_s"] == 56.55
    assert data["all_passed"] is True, "the wake is not counted against any budget"


# ═══ 2. a target is not a gate ════════════════════════════════════════════════

def test_a_target_never_changes_an_exit_status(monkeypatch, tmp_path, capsys):
    """Every endpoint is over its target (4 s) and under its budget: the run is green and SAYS it was over."""
    code, path = _run(monkeypatch, tmp_path, step=lambda p: 4.0)
    out = capsys.readouterr().out
    assert code == 0, out
    data = _load(path)
    assert all(s["elapsed_s"] > s["target_s"] for s in data["checks"])
    assert data["all_passed"] is True
    assert "over:" in out and "judged over 30 days, not on one run" in out


def test_the_targets_line_says_over_and_never_failed():
    samples = [
        {"name": "a", "elapsed_s": 5.0, "target_s": 3.0, "answered": True},
        {"name": "b", "elapsed_s": 1.0, "target_s": 3.0, "answered": True},
        {"name": "c", "elapsed_s": 0.05, "target_s": 3.0, "answered": False},   # a fast failure: not judged
        {"name": "d", "elapsed_s": 9.0, "target_s": None, "answered": True},    # no target: not judged
    ]
    line = smoke_api.targets_line(samples)
    assert "1 of 2" in line and "a 5.00s > 3s" in line
    assert "fail" not in line.lower().replace("failed", "")  # never calls a single sample a failure
    assert "no endpoint answered" in smoke_api.targets_line([])


def test_the_mfa_guard_refusing_a_password_grant_token_counts_as_an_answer():
    record: list = []
    perms = next(c for c in smoke_api.checks("c", "2026-04-01", "2027-03-31") if c.mfa_guarded)
    body = {"detail": smoke_api.MFA_REQUIRED_DETAIL}
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, json=body))) as c:
        ok, _ = smoke_api.run_check(c, "http://x", perms, "t", record=record)
    assert ok and record[0]["answered"] is True and record[0]["status"] == 403
    other = {"detail": "Account disabled. Contact your firm administrator."}
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, json=other))) as c:
        ok, _ = smoke_api.run_check(c, "http://x", perms, "t", record=record)
    assert not ok and record[1]["answered"] is False


def test_a_transport_error_is_recorded_as_not_answered():
    record: list = []

    def boom(req):
        raise httpx.ConnectError("refused")
    with httpx.Client(transport=httpx.MockTransport(boom)) as c:
        ok, line = smoke_api.run_check(c, "http://x", smoke_api.Check("h", "/health", 5), "t", record=record)
    assert not ok and "TRANSPORT ERROR" in line
    assert record[0]["status"] is None and record[0]["answered"] is False


# ═══ 3. the targets are written, and are the code ═════════════════════════════

CHECKS = smoke_api.checks("c", "2026-04-01", "2027-03-31")


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.name)
def test_every_check_has_a_target_and_its_budget_is_at_least_twice_it(check):
    """The floor `docs/operations/service-levels.md` §5 gives for tightening. A budget closer than that to its
    target would fail a run on an endpoint that is meeting its target."""
    assert check.target_s is not None and check.target_s > 0, f"{check.name} has no target"
    assert check.budget_s >= 2 * check.target_s, (
        f"{check.name}: budget {check.budget_s} s is under twice its {check.target_s} s target")


def _doc_rows() -> dict[str, tuple[float, float]]:
    section = DOC.read_text(encoding="utf-8").split("## 2. The targets", 1)[1].split("\n## ", 1)[0]
    rows = re.findall(r"^\|\s*`([^`]+)`\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|", section, re.M)
    return {name: (float(t), float(b)) for name, t, b in rows}


def test_the_documents_table_is_the_codes_table():
    rows = _doc_rows()
    assert rows, "no target table found in docs/operations/service-levels.md"
    assert set(rows) == {c.name for c in CHECKS}, "a check has no row, or a row names no check"
    for c in CHECKS:
        assert rows[c.name] == (float(c.target_s), float(c.budget_s)), (
            f"{c.name}: the document says {rows[c.name]}, the code says {(c.target_s, c.budget_s)}")


def test_no_availability_percentage_is_promised_without_an_instrument():
    """The marketing ledger lists the SLA as unproven because nothing measures uptime. A figure written here would
    be the first step to that claim with nothing behind it."""
    text = DOC.read_text(encoding="utf-8")
    assert not re.search(r"\b9\d(?:\.\d+)?\s*%", text), "an availability figure appeared in the service-levels document"


def test_the_document_says_it_has_not_been_run_on_github():
    text = DOC.read_text(encoding="utf-8")
    assert "Not verified" in text and "proposed" in text.lower()


# ═══ 4. the report ════════════════════════════════════════════════════════════

def _sample(name, elapsed, *, answered=True, budget=20, target=3):
    return {"name": name, "elapsed_s": elapsed, "budget_s": budget, "target_s": target,
            "status": 200 if answered else 503, "answered": answered, "ok": answered and elapsed <= budget}


def _run_record(days_ago, samples, *, deployment="live", run_id=None, **extra):
    at = NOW - timedelta(days=days_ago)
    return {"schema": 1, "generated_at": at.isoformat(), "deployment": deployment, "run_id": run_id,
            "awake": True, "wake_s": 1.0, "cold_start": False, "checks": samples, **extra}


def _summary(runs, **kw):
    usable = [report._usable(r) for r in runs]
    return report.summarise(sorted((u for u in usable if u), key=lambda r: r["at"]), now=NOW, **kw)


def test_the_percentile_is_the_nearest_rank_and_never_a_value_nobody_measured():
    assert report.percentile(list(range(1, 101)), 0.95) == 95
    assert report.percentile(list(range(1, 21)), 0.95) == 19          # ceil(0.95 * 20) = 19th
    assert report.percentile([7], 0.95) == 7 and report.percentile([], 0.95) is None
    assert report.percentile([3, 1, 2], 0.50) == 2


def test_latency_is_taken_over_answers_only_and_failures_are_counted_apart():
    """A 503 returning in 50 ms is not a fast answer. Without this the p95 of a service that is mostly down looks fine."""
    runs = [_run_record(1, [_sample("e", 2.0)]) for _ in range(20)]
    runs += [_run_record(1, [_sample("e", 0.05, answered=False)]) for _ in range(30)]
    e = _summary(runs)["endpoints"][0]
    assert e["answered"] == 20 and e["failed"] == 30
    assert e["p50"] == 2.0 and e["p95"] == 2.0


def test_the_verdicts_within_over_not_enough_and_none():
    fast = [_run_record(1, [_sample("fast", 1.0)]) for _ in range(25)]
    slow = [_run_record(1, [_sample("slow", 9.0)]) for _ in range(25)]
    few = [_run_record(1, [_sample("few", 99.0)]) for _ in range(5)]
    none = [_run_record(1, [_sample("none", 9.0, target=None)]) for _ in range(25)]
    by = {e["name"]: e["verdict"] for e in _summary(fast + slow + few + none)["endpoints"]}
    assert by == {"fast": "within target", "slow": "OVER target", "few": "not enough samples", "none": "no target"}


def test_one_slow_sample_in_a_month_does_not_make_an_endpoint_over_its_target():
    """That is the point of a percentile, and the reason a target cannot be a gate on one run."""
    runs = [_run_record(1, [_sample("e", 1.0)]) for _ in range(99)] + [_run_record(1, [_sample("e", 19.0)])]
    e = _summary(runs)["endpoints"][0]
    assert e["p95"] == 1.0 and e["verdict"] == "within target" and e["max"] == 19.0


def test_the_table_says_how_many_days_it_covers_and_does_not_call_a_week_a_month():
    week = [_run_record(d, [_sample("e", 1.0)]) for d in range(0, 5)]
    text = report.render(_summary(week))
    assert "not available yet" in text and "of the 30 days asked for" in text
    month = [_run_record(d, [_sample("e", 1.0)]) for d in range(0, 30)]
    s = _summary(month)
    assert s["complete_window"] is True
    assert "not available yet" not in report.render(s)


def test_runs_outside_the_window_are_left_out():
    runs = [_run_record(40, [_sample("old", 1.0)]), _run_record(2, [_sample("new", 1.0)])]
    assert [e["name"] for e in _summary(runs)["endpoints"]] == ["new"]


def test_the_weekly_table_has_a_column_per_iso_week():
    runs = [_run_record(d, [_sample("e", 1.0 + d)]) for d in (1, 9, 17, 25)]
    e = _summary(runs)["endpoints"][0]
    assert len(e["weekly_p95"]) == 4
    text = report.render(_summary(runs))
    assert "95th percentile by ISO week" in text and "2026-W" in text


def test_a_candidate_deployment_is_excluded_and_counted():
    runs = [_run_record(1, [_sample("e", 1.0)]), _run_record(1, [_sample("e", 50.0)], deployment="candidate")]
    s = _summary(runs)
    assert s["runs"] == 1 and s["candidate_runs_excluded"] == 1
    assert s["endpoints"][0]["max"] == 1.0
    assert "candidate deployment were excluded" in report.render(s)


def test_a_run_in_which_the_api_never_answered_is_counted_in_the_table():
    runs = [_run_record(1, [_sample("e", 1.0)]), _run_record(1, [], awake=False)]
    s = _summary(runs)
    assert s["runs_api_never_answered"] == 1
    assert "never answered /health in 1 run" in report.render(s)


def test_the_files_that_could_not_be_read_are_named_and_never_stop_the_report(tmp_path):
    good = _run_record(1, [_sample("e", 1.0)], run_id="1")
    (tmp_path / "good.json").write_text(json.dumps(good))
    (tmp_path / "garbage.json").write_text("{not json")
    (tmp_path / "otherschema.json").write_text(json.dumps({**good, "schema": 2}))
    (tmp_path / "nodate.json").write_text(json.dumps({**good, "generated_at": "yesterday"}))
    (tmp_path / "notadict.json").write_text("[1, 2]")
    runs, unreadable = report.load([tmp_path])
    assert len(runs) == 1
    assert sorted(unreadable) == ["garbage.json", "nodate.json", "notadict.json", "otherschema.json"]
    text = report.render(report.summarise(runs, now=NOW, unreadable=unreadable))
    assert "4 file(s) could not be read" in text and "garbage.json" in text


def test_a_naive_timestamp_is_read_as_utc():
    naive = _run_record(1, [_sample("e", 1.0)])
    naive["generated_at"] = (NOW - timedelta(days=1)).replace(tzinfo=None).isoformat()
    assert report._usable(naive)["at"].tzinfo is not None


def test_one_run_found_twice_is_counted_once(tmp_path):
    """This run's own file and the listing's copy of it."""
    run = _run_record(1, [_sample("e", 1.0)], run_id="55")
    for d in ("timings", "history/55"):
        (tmp_path / d).mkdir(parents=True)
        (tmp_path / d / "smoke-timings.json").write_text(json.dumps(run))
    runs, _ = report.load([tmp_path / "history", tmp_path / "timings"])
    assert len(runs) == 1


def test_the_report_exits_zero_whatever_it_finds(tmp_path, capsys):
    """A target is not a gate."""
    for i in range(25):
        (tmp_path / f"{i}.json").write_text(json.dumps(
            _run_record((i + 1) / 24, [_sample("slow", 9.0)], run_id=str(i))))
    assert report.main([str(tmp_path), "--now", NOW.isoformat()]) == 0
    assert "OVER target" in capsys.readouterr().out
    assert report.main([]) == 2


def test_the_schema_the_report_reads_is_the_schema_the_script_writes():
    assert report.SCHEMA == smoke_api.TIMINGS_SCHEMA


def test_what_write_timings_writes_the_report_reads(tmp_path):
    samples: list = []
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))) as c:
        for check in CHECKS:
            smoke_api.run_check(c, "http://x", check, "t", record=samples)
    path = tmp_path / "t" / "smoke-timings.json"
    assert smoke_api.write_timings(str(path), awake=True, wake_s=1.0, wake_detail="HTTP 200",
                                   samples=samples, now=NOW - timedelta(days=1))
    runs, unreadable = report.load([tmp_path])
    assert unreadable == [] and len(runs) == 1
    summary = report.summarise(runs, now=NOW)
    assert {e["name"] for e in summary["endpoints"]} == {c.name for c in CHECKS}


# ═══ 5. the workflow ══════════════════════════════════════════════════════════

def _code(path: Path) -> str:
    return "\n".join(l for l in path.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))


def _step(name: str) -> str:
    """One step's text, from its `- name:` line to the next step or the end."""
    code = _code(WORKFLOW)
    start = code.index(f"- name: {name}")
    nxt = code.find("\n      - name:", start + 1)
    return code[start: nxt if nxt != -1 else len(code)]


def test_every_run_uploads_its_timings_even_a_failed_one_for_ninety_days():
    step = _step("Keep this run's timings")
    assert "if: always()" in step and re.search(r"actions/upload-artifact@v\d+", step)
    assert "retention-days: 90" in step
    assert "if-no-files-found: ignore" in step, "a skipped run measures nothing and leaves no file"
    assert "github.run_id" in step and "github.run_attempt" in step, "two artifacts of one name would collide"
    assert "smoke-timings-${{ inputs.base_url && 'candidate' || 'live' }}-" in step


def test_the_uploaded_path_is_the_one_the_script_is_told_to_write():
    code = _code(WORKFLOW)
    env_path = re.search(r"SMOKE_TIMINGS_FILE:\s*(\S+)", code).group(1)
    upload = re.search(r"path:\s*(apps/api/\S+)", _step("Keep this run's timings")).group(1)
    assert upload == f"apps/api/{env_path}", "the script writes one file and the workflow uploads another"
    assert code.index("SMOKE_TIMINGS_FILE") < code.index("Keep this run's timings")


def test_a_candidate_run_is_labelled_so_it_cannot_enter_the_live_history():
    code = _code(WORKFLOW)
    assert "SMOKE_DEPLOYMENT: ${{ inputs.base_url && 'candidate' || 'live' }}" in code
    assert 'startswith(\\"smoke-timings-live-\\")' in _step("Summarise the last 30 days of timings")


def test_the_workflow_asks_for_read_permissions_and_nothing_that_writes():
    head = _code(WORKFLOW).split("\njobs:")[0]
    perms = re.search(r"^permissions:\n((?:\s+\S.*\n)+)", head + "\n", re.M).group(1)
    assert "contents: read" in perms and "actions: read" in perms
    assert "write" not in perms


def test_the_summary_step_can_never_fail_the_run_and_still_runs_after_a_failed_one():
    step = _step("Summarise the last 30 days of timings")
    assert "if: always()" in step and "continue-on-error: true" in step
    assert "--days 30" in step and "GITHUB_STEP_SUMMARY" in step


def test_it_is_not_one_of_the_required_checks_and_still_has_no_pr_trigger():
    """CLAUDE.md, CI: a path filter or a PR trigger on a workflow carrying a required check makes PRs unmergeable.
    This is not one, and nothing here made it one."""
    head = _code(WORKFLOW).split("\njobs:")[0]
    assert "pull_request" not in head and "push:" not in head and "paths:" not in head


# ── the last step's shell, run against a stand-in for `gh` ─────────────────────

def _step_script() -> str:
    """The `run: |` block of the summary step, dedented, exactly as the runner would execute it."""
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Summarise the last 30 days of timings")
    run = text.index("run: |\n", start) + len("run: |\n")
    block = []
    for line in text[run:].splitlines():
        if line.strip() and not line.startswith("          "):
            break
        block.append(line)
    return textwrap.dedent("\n".join(block))


FAKE_GH = r"""#!/usr/bin/env bash
# A stand-in for `gh api`. Args are the real ones the step passes.
set -u
args=("$@")
endpoint=""
jq_expr=""
i=0
while [ $i -lt ${#args[@]} ]; do
  case "${args[$i]}" in
    api|--paginate) ;;
    --jq) i=$((i+1)); jq_expr="${args[$i]}" ;;
    *) endpoint="${args[$i]}" ;;
  esac
  i=$((i+1))
done
case "$endpoint" in
  *"/artifacts?per_page=100")
    [ -f "$FAKE_GH_DIR/list_fails" ] && { echo "HTTP 502" >&2; exit 1; }
    jq -r "$jq_expr" "$FAKE_GH_DIR/artifacts.json" ;;
  *"/zip")
    id="$(echo "$endpoint" | sed -E 's#.*/artifacts/([0-9]+)/zip#\1#')"
    [ "$id" = "$(cat "$FAKE_GH_DIR/bad_id" 2>/dev/null)" ] && { echo "HTTP 410" >&2; exit 1; }
    cat "$FAKE_GH_DIR/zips/$id.zip" ;;
  *) echo "unexpected endpoint $endpoint" >&2; exit 9 ;;
esac
"""


@pytest.fixture
def step_env(tmp_path):
    if not (shutil.which("jq") and shutil.which("unzip") and shutil.which("bash")):
        pytest.skip("needs jq, unzip and bash (all present on a GitHub runner)")
    fake = tmp_path / "fake_gh"
    (fake / "zips").mkdir(parents=True)
    (fake / "bin").mkdir()
    (fake / "bin" / "gh").write_text(FAKE_GH)
    (fake / "bin" / "gh").chmod(0o755)

    work = tmp_path / "work"
    work.mkdir()
    (work / "scripts").symlink_to(API / "scripts")      # the step runs `python3 scripts/smoke_timings_report.py`

    now = datetime.now(timezone.utc)
    arts = []

    def add_artifact(art_id, name, days_ago, *, expired=False, run_days_ago=None, samples=None):
        arts.append({"id": art_id, "name": name, "expired": expired,
                     "created_at": (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")})
        run = {"schema": 1, "generated_at": (now - timedelta(days=run_days_ago if run_days_ago is not None else days_ago)).isoformat(),
               "deployment": "live", "run_id": str(art_id), "awake": True, "wake_s": 1.0, "cold_start": False,
               "checks": samples or [_sample("accounting/profit-loss", 1.0 + art_id / 1000)]}
        with zipfile.ZipFile(fake / "zips" / f"{art_id}.zip", "w") as z:
            z.writestr("smoke-timings.json", json.dumps(run))

    summary = tmp_path / "summary.md"
    summary.write_text("")

    def run_step():
        (fake / "artifacts.json").write_text(json.dumps({"total_count": len(arts), "artifacts": arts}))
        env = {**os.environ, "PATH": f"{fake / 'bin'}:{os.environ['PATH']}", "FAKE_GH_DIR": str(fake),
               "GH_TOKEN": "x", "REPO": "o/r", "GITHUB_STEP_SUMMARY": str(summary)}
        proc = subprocess.run(["bash", "-c", _step_script()], cwd=work, env=env,
                              capture_output=True, text=True, timeout=60)
        return proc, summary.read_text(encoding="utf-8")

    return type("StepEnv", (), {"add": staticmethod(add_artifact), "run": staticmethod(run_step),
                                "fake": fake, "work": work})


def test_the_summary_step_builds_its_table_from_the_live_artifacts_in_the_window(step_env):
    step_env.add(11, "smoke-timings-live-100-1", 1)
    step_env.add(16, "smoke-timings-live-99-1", 15)
    step_env.add(12, "smoke-timings-candidate-101-1", 1)              # a candidate: not live history
    step_env.add(13, "smoke-timings-live-90-1", 20, expired=True)     # expired: cannot be downloaded
    step_env.add(14, "smoke-timings-live-80-1", 50)                   # outside the window
    step_env.add(15, "docker-image-report", 1)                        # another workflow's
    proc, summary = step_env.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "### Smoke timings, last 30 days" in summary
    assert "| accounting/profit-loss | 2 |" in summary, "exactly the two live artifacts in the window"


def test_an_artifact_that_will_not_download_is_left_out_and_named_not_fatal(step_env):
    step_env.add(21, "smoke-timings-live-1-1", 1)
    step_env.add(22, "smoke-timings-live-2-1", 2)
    (step_env.fake / "bad_id").write_text("22")
    proc, summary = step_env.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "could not fetch artifact 22" in proc.stdout
    assert "| accounting/profit-loss | 1 |" in summary


def test_a_listing_that_fails_still_reports_and_still_exits_zero(step_env):
    (step_env.fake / "list_fails").write_text("1")
    proc, summary = step_env.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "could not list earlier artifacts" in proc.stdout
    assert "### Smoke timings, last 30 days" in summary, "the report is written even with nothing to read"
    assert "has left a timings file" in summary


def test_this_runs_own_file_counts_once_even_when_the_listing_shows_it_too(step_env):
    step_env.add(31, "smoke-timings-live-31-1", 1)
    (step_env.work / "timings").mkdir()
    run = json.loads(zipfile.ZipFile(step_env.fake / "zips" / "31.zip").read("smoke-timings.json"))
    (step_env.work / "timings" / "smoke-timings.json").write_text(json.dumps(run))
    proc, summary = step_env.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "| accounting/profit-loss | 1 |" in summary
