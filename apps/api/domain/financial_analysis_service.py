"""
AI-generated financial statement analysis — a short narrative plus a handful
of liquidity/profitability ratios summarizing a client's P&L and Balance
Sheet. Ratios are computed here from the SAME backend-authoritative paise
totals the reporting engine (domain/reporting) already returns — no figure is
derived anywhere else.

Uses Groq API (llama-3.3-70b-versatile), same call shape as
domain/ai_copilot_service.py. The prompt contains ONLY the numbers computed
below; the model is instructed to use no other knowledge and invent nothing,
since a hallucinated figure in a CA's working file is a real risk. When Groq
is unavailable (no GROQ_API_KEY, or the call fails) this falls back to a
deterministic, non-AI narrative built from the same numbers, so the panel is
never empty and a Groq outage never surfaces as a broken UI. Advisory only —
never used to auto-file or auto-submit anything.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

_logger = logging.getLogger("caflow.financial_analysis")

_GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
_MODEL = "llama-3.3-70b-versatile"

_SYSTEM_PROMPT = """You are a financial analysis assistant for an Indian Chartered Accountant reviewing a client's Profit & Loss and Balance Sheet.

Rules you MUST follow:
1. Use ONLY the figures given to you in the user message — never invent, estimate, or assume any number you were not given.
2. Write 2-4 concise sentences in plain English. No bullet points, no headings, no markdown.
3. Point out the most notable trend(s): revenue/expense/profit movement versus the prior year if given, and anything about liquidity (current ratio) worth the CA's attention.
4. This is advisory context for the CA's own review, not a final determination — phrase computed ratios as observations, not conclusions.
5. Do not mention GST, TDS, or any tax filing — this analysis is about the financial statements only."""

# Schedule III captions (domain/reporting/schedule_iii.bs_bucket output) this
# app treats as CURRENT — used for the current ratio. Lines are routed through
# bs_bucket() below, NOT matched on raw account_subtype: the raw subtypes are
# seed-vocabulary words ("Receivable", "Cash", "Inventory", …) that never
# equal these caption labels, so the old exact-match sets summed 0 on every
# balance sheet and the current ratio was permanently None.
_CURRENT_ASSET_BUCKETS = {
    "Trade Receivables", "Cash & Cash Equivalents", "Short Term Loans & Advances",
    "Other Current Assets", "Inventories",
}
_CURRENT_LIAB_BUCKETS = {
    "Short Term Borrowings", "Trade Payables", "Other Current Liabilities",
}


def _pct_change(curr: int, prev: int) -> Optional[float]:
    if prev == 0:
        return None
    return round((curr - prev) / abs(prev) * 100, 1)


def _rupees(paise: int) -> str:
    return f"Rs {paise / 100:,.2f}"


def _sum_by_bucket(bs: dict, section_key: str, buckets: set) -> int:
    from domain.reporting.schedule_iii import bs_bucket
    total = 0
    for section in (bs.get(section_key) or []):
        for line in section.get("lines", []):
            cap = bs_bucket(line.get("account_type", ""), line.get("account_subtype"))
            if cap in buckets:
                total += line.get("balance_paise", 0)
    return total


def compute_ratios(pl: dict, bs: dict) -> dict:
    """Money comparisons happen on the backend's integer-paise totals; only the
    final quotient (a dimensionless ratio, not a rupee amount) is a float."""
    revenue = pl.get("revenue", {}).get("total_paise", 0)
    expenses = pl.get("operating_expenses", {}).get("total_paise", 0)
    net_profit = pl.get("net_profit_paise", 0)

    net_margin_pct = round(net_profit / revenue * 100, 1) if revenue else None
    expense_ratio_pct = round(expenses / revenue * 100, 1) if revenue else None

    current_assets = _sum_by_bucket(bs, "assets", _CURRENT_ASSET_BUCKETS)
    current_liabilities = _sum_by_bucket(bs, "liabilities", _CURRENT_LIAB_BUCKETS)
    current_ratio = round(current_assets / current_liabilities, 2) if current_liabilities else None

    return {
        "net_margin_pct": net_margin_pct,
        "expense_ratio_pct": expense_ratio_pct,
        "current_ratio": current_ratio,
        "current_assets_paise": current_assets,
        "current_liabilities_paise": current_liabilities,
    }


def _deterministic_narrative(pl: dict, prev_pl: Optional[dict], ratios: dict) -> str:
    """Non-AI fallback — used when Groq is unavailable. Built from the exact
    same numbers the AI prompt would have received, so it is never a "feature
    is broken" placeholder, just a plainer version of the same content."""
    revenue = pl.get("revenue", {}).get("total_paise", 0)
    parts = []
    if prev_pl:
        rev_change = _pct_change(revenue, prev_pl.get("revenue", {}).get("total_paise", 0))
        if rev_change is not None:
            direction = "up" if rev_change >= 0 else "down"
            parts.append(f"Revenue is {direction} {abs(rev_change)}% versus the prior year.")
    if ratios.get("net_margin_pct") is not None:
        parts.append(f"Net margin is {ratios['net_margin_pct']}% for the period.")
    if ratios.get("current_ratio") is not None:
        cr = ratios["current_ratio"]
        note = "comfortable" if cr >= 1 else "tight"
        parts.append(f"Current ratio is {cr}x, which looks {note}.")
    if not parts:
        parts.append("Not enough posted data yet to compute a meaningful trend.")
    return " ".join(parts)


async def _call_groq(messages: list[dict]) -> Optional[str]:
    if not _GROQ_API_KEY:
        return None
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {_GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": _MODEL, "messages": messages, "max_tokens": 300, "temperature": 0.3},
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except Exception as exc:
        _logger.error("Groq API error (statement analysis): %s", exc)
        return None


async def generate_statement_analysis(
    pl: dict, bs: dict, prev_pl: Optional[dict], financial_year: str, prev_financial_year: str,
) -> dict:
    ratios = compute_ratios(pl, bs)

    numbers = [
        f"FY {financial_year} Revenue: {_rupees(pl.get('revenue', {}).get('total_paise', 0))}",
        f"FY {financial_year} Expenses: {_rupees(pl.get('operating_expenses', {}).get('total_paise', 0))}",
        f"FY {financial_year} Net Profit: {_rupees(pl.get('net_profit_paise', 0))}",
    ]
    if prev_pl:
        numbers += [
            f"FY {prev_financial_year} Revenue: {_rupees(prev_pl.get('revenue', {}).get('total_paise', 0))}",
            f"FY {prev_financial_year} Expenses: {_rupees(prev_pl.get('operating_expenses', {}).get('total_paise', 0))}",
            f"FY {prev_financial_year} Net Profit: {_rupees(prev_pl.get('net_profit_paise', 0))}",
        ]
    if ratios["net_margin_pct"] is not None:
        numbers.append(f"Net margin: {ratios['net_margin_pct']}%")
    if ratios["current_ratio"] is not None:
        numbers.append(
            f"Current ratio: {ratios['current_ratio']}x "
            f"(current assets {_rupees(ratios['current_assets_paise'])} / "
            f"current liabilities {_rupees(ratios['current_liabilities_paise'])})"
        )

    prompt = "Here are this client's financial figures:\n" + "\n".join(numbers)
    narrative = await _call_groq([
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ])
    ai_generated = narrative is not None
    if narrative is None:
        narrative = _deterministic_narrative(pl, prev_pl, ratios)

    return {"narrative": narrative.strip(), "ai_generated": ai_generated, "ratios": ratios}
