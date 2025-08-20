from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from _decimal import Decimal


@dataclass(frozen=True)
class ExcelRow:
    idx: int                    # 0-based row index from Excel (after header)
    txn_id: str                 # groups rows into a single transaction
    date: date
    amount: Decimal
    item: str
    category: str
    rationale: str
