"""Bank-feed foundation (Banking B.1): statement normalization + dedup.

Pure, DB-agnostic. Bank-specific column layouts live ONLY in normalizer._ADAPTERS;
everything downstream works on the single NormalizedTxn format.
"""
from .normalizer import (
    NormalizedTxn,
    parse_statement,
    parse_csv,
    parse_xlsx,
    detect_format,
    StatementParseError,
)
from .dedup import transaction_hash, file_hash
from .categories import CATEGORIES, CATEGORY_SET, is_valid_category
from .rules import suggest_category, match_rule, rule_matches, RuleSuggestion
from .narration import (
    ParsedNarration, parse_narration, party_matches, normalise_party_name,
    describe as describe_narration,
)
from .matcher import (
    Candidate, Suggestion, rank_suggestions,
    NEAR_MATCH_BAND_BPS, NEAR_MATCH_CONFIDENCE_CAP, TDS_RATES_BPS, TDS_TOLERANCE_PAISE,
    near_match_floor_paise, detect_tds_rate_bps,
)
from .charge_gst import (
    ChargeSplit, split_inclusive_charge, build_charge_lines,
    ALLOWED_RATES_BPS as CHARGE_GST_RATES_BPS,
)
from .history import (
    HistorySuggestion, CodingOption, learning_key, summarise as summarise_history,
    describe as describe_history, same_payee,
)
from .register import (
    RegisterLine, build_register, first_divergence, summarise as summarise_register,
    derive_cleared, CLEARED_NONE, CLEARED_PENDING, CLEARED_RECONCILED,
)

__all__ = [
    "NormalizedTxn", "parse_statement", "parse_csv", "parse_xlsx",
    "detect_format", "StatementParseError", "transaction_hash", "file_hash",
    "CATEGORIES", "CATEGORY_SET", "is_valid_category",
    "suggest_category", "match_rule", "rule_matches", "RuleSuggestion",
    "ParsedNarration", "parse_narration", "party_matches", "normalise_party_name",
    "describe_narration",
    "Candidate", "Suggestion", "rank_suggestions",
    "NEAR_MATCH_BAND_BPS", "NEAR_MATCH_CONFIDENCE_CAP",
    "TDS_RATES_BPS", "TDS_TOLERANCE_PAISE",
    "near_match_floor_paise", "detect_tds_rate_bps",
    "ChargeSplit", "split_inclusive_charge", "build_charge_lines",
    "CHARGE_GST_RATES_BPS",
    "RegisterLine", "build_register", "first_divergence", "summarise_register",
    "derive_cleared", "CLEARED_NONE", "CLEARED_PENDING", "CLEARED_RECONCILED",
    "HistorySuggestion", "CodingOption", "learning_key", "summarise_history",
    "describe_history", "same_payee",
]
