# quicken_helper/controllers/qif_loader.py
from __future__ import annotations

import warnings

# --- ADD near the top of the file (after existing imports) ---
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from quicken_helper.data_model import QAccount, QifHeader, QuickenFile, IQuickenFile

# Protocols (structural typing) and enums
from quicken_helper.data_model.interfaces import (
    EnumClearedStatus,
    IAccount,
    IHeader,
    ISplit,
    ITransaction,
)
from quicken_helper.data_model.qif_parsers_emitters.qif_file_parser_emitter import QifFileParserEmitter

# Re-use your established transaction parser (handles splits etc.)
from quicken_helper.legacy.qif_parsed import ParsedQIF
from quicken_helper.utilities.core_util import open_for_read


@dataclass
class UnifiedQifProtocol:
    transactions: List[ITransaction]
    accounts: List[IAccount]
    headers: List[IHeader]
    other_sections: Mapping[str, Any]  # keep whatever structure you already use


# --------------------------
# Unified, robust QIF loader
# --------------------------
def parse_qif_unified_protocol(path: Path, encoding: str = "utf-8") -> IQuickenFile:
    """
    Unified QIF loader.
    - Transactions: delegated to parse_qif (your current canonical parser).
    - Lists (Accounts, Categories, Memorized, Securities, Class/Business, Payees): parsed here,
      tolerant to format variants; unknown sections are preserved in other_sections.
    """
    with open_for_read(path=path, binary=False, encoding=encoding, errors="replace") as f:
        text = f.read()
    parser = QifFileParserEmitter()
    quicken_file = parser.parse(text)
    return quicken_file


def load_transactions_protocol(
    path: Path, encoding: str = "utf-8"
) -> List[ITransaction]:
    """
    Return transactions adapted to the ITransaction/ISplit interfaces.
    Delegates parsing to parse_qif(...) and adapts each dict record.
    """
    transactions = parse_qif_unified_protocol(path, encoding=encoding).transactions
    return transactions
    # raw = open_and_parse_qif(path, encoding=encoding)
    # return [_adapt_txn(rec) for rec in raw]


# --------------------------------------
# Internal helpers for non-transactional
# --------------------------------------
# Known section headers (seen in the wild, plus tolerant synonyms)
_SECTION_NORMALIZE = {
    "!account": "Account",
    "!type:cat": "Category",
    "!type:category": "Category",
    "!type:memorized": "Memorized",
    "!type:memorized payee": "Memorized",
    "!type:security": "Security",
    "!type:class": "Class",  # business/class list
    "!type:payee": "Payee",
}

# A minimal single-char → key map per section family.
# Unrecognized letters are placed under 'raw'.
_FIELD_MAP = {
    "Account": {
        "N": "name",
        "D": "description",
        "T": "type",
        "L": "limit",  # not standard everywhere; store if present
    },
    "Category": {
        "N": "name",
        "D": "description",
        # Flags: lines that appear without values (e.g., E, I) become booleans.
        "E": ("flag", "expense"),
        "I": ("flag", "income"),
        "T": "tax_line",  # sometimes used for tax line info
        "B": "budget",  # if present, keep the value as-is
    },
    "Memorized": {
        "N": "name",
        "M": "memo",
        "T": "type",  # type of txn (payment, deposit, etc.)
        "A": "address",  # can repeat; we’ll join lines
        "L": "category",
    },
    "Security": {
        "N": "name",
        "S": "symbol",
        "T": "type",
        "D": "description",
    },
    "Class": {
        "N": "name",
        "D": "description",
    },
    "Payee": {
        "N": "name",
        "A": "address",
        "M": "memo",
    },
}

