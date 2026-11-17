"""The income-tax filing season at firm level (POST-A-068): every in-scope client's return for a year by stage, and a bulk re-run of the
computations that can be run again.

THE LIST reads three firm-scoped, paged sets (the firm's live clients, its return records for the year, its saved computations for the
year, the last without their bodies), narrows them to the caller's clients, and hands them to `domain/income_tax/filing_season`, which
names the stage. It never claims a step the records cannot answer (documents received, e-verification: `NOT_TRACKED`).

THE BULK RUN computes only what the engine can compute from RECORDED inputs. A computation's inputs (salary, deductions, regime, the CA's
choices) are typed by the CA on the client's computation screen and are not held anywhere else: the books give no salary and no
Chapter VI-A claim. So the run takes each selected client's LATEST saved computation for the year, and where that computation kept the
inputs it was made from (`computation_json.inputs`, kept since this change), runs them through the very function the computation screen
calls (`routers.income_tax.compute_itr`) at today's rates and records. A result that differs is saved as the next version, DRAFT, and
nothing else moves: no return status, no review, nothing filed or sent anywhere. A result that came to the same figures saves nothing and
says so. A client the run could not compute is answered in words: no saved computation, one saved before inputs were kept, the engine's
own refusal, a brought-forward loss record that is gone, a client outside the caller's scope. The run states what it did not do.
# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this prepares a draft computation. It transmits nothing to any portal.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import HTTPException

from core.authz import effective_client_ids, filter_by_client
from core.db_paging import fetch_all, fetch_all_in
from core.exceptions import ValidationError
from core.observability import capture_soft_failure
from domain.income_tax import filing_season as rule

_logger = logging.getLogger("caflow.itr.season")

#: Rows a screen asks for at once. The counts are always the whole year's.
DEFAULT_PAGE = 100
MAX_PAGE = 500


def _clients(db, firm_id: str) -> list[dict]:
    return fetch_all(lambda: db.table("clients").select("id, client_name, entity_type, status")
                     .eq("firm_id", firm_id).eq("is_internal", False).is_("deleted_at", "null")
                     .neq("status", "archived"), label="filing_season.clients")


def season(db, current_user: dict, financial_year: str, *, stage: Optional[str] = None,
           limit: int = DEFAULT_PAGE, offset: int = 0) -> dict:
    """Every in-scope client's return for `financial_year`, one row each, with the counts by stage for the whole set."""
    firm_id = current_user["firm_id"]
    if stage is not None and stage not in rule.STAGES:
        raise ValidationError("stage", f"Unknown stage '{stage}'. One of: {', '.join(rule.STAGES)}.")
    clients = [{**c, "client_id": c["id"]} for c in filter_by_client(current_user, _clients(db, firm_id), key="id")]
    filings = fetch_all(lambda: db.table("itr_filings")
                        .select("id, client_id, status, itr_form, acknowledgement_number, filing_date, created_at")
                        .eq("firm_id", firm_id).eq("financial_year", financial_year), label="filing_season.filings")
    snaps = fetch_all(lambda: db.table("tax_computation_snapshots")
                      .select("id, client_id, version, status, regime, net_payable_paise, is_refund, created_at")
                      .eq("firm_id", firm_id).eq("financial_year", financial_year), label="filing_season.snapshots")
    latest_filing = rule.latest_by_client(filings, "created_at")
    latest_snap = rule.latest_by_client(snaps, "version")

    rows, counts = [], {s: 0 for s in rule.STAGES}
    for c in sorted(clients, key=lambda c: (str(c.get("client_name") or "").lower(), str(c["id"]))):
        cid = str(c["id"])
        f, s = latest_filing.get(cid), latest_snap.get(cid)
        st = rule.stage_of(f, s)
        counts[st] += 1
        rows.append({
            "client_id": cid, "client_name": c.get("client_name"), "entity_type": c.get("entity_type"),
            "stage": st, "stage_label": rule.STAGE_LABELS[st],
            "itr_form": (f or {}).get("itr_form"), "filing_status": (f or {}).get("status"),
            "acknowledgement_number": (f or {}).get("acknowledgement_number"), "filing_date": (f or {}).get("filing_date"),
            "computation_version": (s or {}).get("version"), "computation_status": (s or {}).get("status"),
            "net_payable_paise": (s or {}).get("net_payable_paise"), "is_refund": (s or {}).get("is_refund"),
        })
    shown = [r for r in rows if stage is None or r["stage"] == stage]
    limit = max(1, min(int(limit), MAX_PAGE))
    return {
        "financial_year": financial_year,
        "total_clients": len(rows),
        "counts": counts,
        "stage_labels": rule.STAGE_LABELS,
        "matching": len(shown),
        "limit": limit, "offset": max(0, int(offset)),
        "rows": shown[max(0, int(offset)):max(0, int(offset)) + limit],
        "not_tracked": list(rule.NOT_TRACKED),
        "max_bulk_clients": rule.MAX_BULK_CLIENTS,
    }


def _snapshots_for(db, firm_id: str, financial_year: str, client_ids: list[str]) -> dict[str, dict]:
    rows = fetch_all_in(lambda: db.table("tax_computation_snapshots").select("*")
                        .eq("firm_id", firm_id).eq("financial_year", financial_year),
                        "client_id", client_ids, label="filing_season.latest_snapshots")
    return rule.latest_by_client(rows, "version")


def _result(client_id: str, name: Any, state: str, message: str, **extra: Any) -> dict:
    return {"client_id": client_id, "client_name": name, "state": state, "message": message, **extra}


def bulk_compute(db, current_user: dict, financial_year: str, client_ids: list[str]) -> dict:
    """Run the saved inputs of each selected client's latest computation again, and report one answer per client."""
    from routers.income_tax import ComputeITRRequest, compute_itr
    from domain.income_tax.computation_workspace import save_computation_snapshot
    firm_id = current_user["firm_id"]
    ids = list(dict.fromkeys(str(c) for c in client_ids))
    if not ids:
        raise ValidationError("client_ids", "Choose at least one client.")
    if len(ids) > rule.MAX_BULK_CLIENTS:
        raise ValidationError("client_ids", f"Choose at most {rule.MAX_BULK_CLIENTS} clients at a time; "
                                            f"{len(ids)} were chosen. Run the rest in another batch.")
    names = {str(c["id"]): c.get("client_name") for c in _clients(db, firm_id)}
    allowed = effective_client_ids(current_user)
    snaps = _snapshots_for(db, firm_id, financial_year, [i for i in ids if i in names and (allowed is None or i in allowed)])
    results: list[dict] = []
    for cid in ids:
        name = names.get(cid)
        if cid not in names or (allowed is not None and cid not in allowed):
            results.append(_result(cid, None, "not_your_client", "This is not one of your clients, so nothing was run for it."))
            continue
        snap = snaps.get(cid)
        if snap is None:
            results.append(_result(cid, name, "no_saved_computation",
                                   f"No computation is saved for FY {financial_year}. The inputs (salary, deductions, the regime) are "
                                   "entered on the client's Tax Computation screen, so there is nothing to run again."))
            continue
        inputs = rule.inputs_of(snap)
        if inputs is None:
            results.append(_result(cid, name, "saved_without_inputs",
                                   f"The latest computation (version {snap.get('version')}) was saved before computations kept their "
                                   "inputs, so it cannot be run again from here. Compute it once on the client's Tax Computation screen.",
                                   version=snap.get("version")))
            continue
        try:
            answer = compute_itr(ComputeITRRequest(**inputs), current_user=current_user)
        except HTTPException as refusal:
            results.append(_result(cid, name, "refused", str(refusal.detail), version=snap.get("version")))
            continue
        except Exception as exc:                                         # noqa: BLE001 - one client's failure must not stop the batch
            capture_soft_failure(exc, operation="filing_season.bulk_compute", firm_id=firm_id, client_id=cid)
            results.append(_result(cid, name, "failed", "The computation could not be run for this client. Nothing was saved.",
                                   version=snap.get("version")))
            continue
        data = answer.get("data") or {}
        problems = data.get("validation_errors") or []
        if not answer.get("success") or problems:
            results.append(_result(cid, name, "refused", " ".join(problems) or (answer.get("error") or "The engine refused these inputs."),
                                   version=snap.get("version")))
            continue
        if rule.same_answer(snap.get("computation_json") or {}, data):
            results.append(_result(cid, name, "unchanged",
                                   f"Run again at today's rates and records, it comes to the same figures as version {snap.get('version')}, "
                                   "so nothing new was saved.", version=snap.get("version")))
            continue
        try:
            saved = save_computation_snapshot(
                firm_id=firm_id, client_id=cid, financial_year=financial_year,
                assessment_year=snap.get("assessment_year") or "", regime=str(data.get("regime") or snap.get("regime") or ""),
                income={
                    "gross_salary_paise": inputs.get("gross_salary_paise", 0),
                    "business_income_paise": inputs.get("business_income_paise", 0),
                    "other_income_paise": inputs.get("other_income_paise", 0),
                    "total_disallowances_paise": inputs.get("disallowances_paise", 0),
                    "advance_tax_paid_paise": inputs.get("advance_tax_paid_paise", 0),
                    "tds_deducted_paise": inputs.get("tds_deducted_paise", 0),
                    "taxable_income_paise": (data.get("income") or {}).get("taxable_income_paise", 0),
                    "tax_liability_paise": (data.get("tax") or {}).get("total_tax_paise", 0),
                    "net_payable_paise": (data.get("payable") or {}).get("net_payable_paise", 0),
                    "is_refund": ((data.get("payable") or {}).get("net_payable_paise", 0)) < 0,
                },
                computation_result=data, created_by=current_user["id"],
                notes=f"Run again in bulk from version {snap.get('version')}'s saved inputs. Draft: review it before relying on it.")
        except Exception as exc:                                         # noqa: BLE001
            capture_soft_failure(exc, operation="filing_season.bulk_compute.save", firm_id=firm_id, client_id=cid)
            results.append(_result(cid, name, "failed", "The new figures could not be saved. Nothing was changed.",
                                   version=snap.get("version")))
            continue
        results.append(_result(cid, name, "computed",
                               f"Saved as version {saved.get('version')}, a draft: the figures differ from version {snap.get('version')}. "
                               "It still needs a person's review.", version=saved.get("version"),
                               previous_version=snap.get("version")))
    tally: dict[str, int] = {}
    for r in results:
        tally[r["state"]] = tally.get(r["state"], 0) + 1
    return {
        "financial_year": financial_year, "results": results, "tally": tally,
        "did_not": ["Move any return to another status.", "Review or approve any computation.",
                    "File or send anything to any portal.", "Take any figure from the books: the inputs are the ones saved with each computation."],
    }
