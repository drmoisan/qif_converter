from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from _decimal import Decimal
from typing import Tuple

from .excel_row import ExcelRow


@dataclass(frozen=True)
class ExcelTxnGroup:
    """
    Represents one Excel 'transaction' (group of split rows with the same TxnID).
    The 'date' is taken as the earliest date among the group's rows (stable & deterministic).
    """
    gid: str
    date: date
    total_amount: Decimal
    rows: Tuple[ExcelRow, ...]  # immutable tuple for safety
