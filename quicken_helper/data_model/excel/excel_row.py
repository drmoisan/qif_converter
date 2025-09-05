from __future__ import annotations

from _decimal import Decimal
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ExcelRow:
    txn_id: str  # groups rows into a single transaction
    date: date
    amount: Decimal
    category: str
    idx: int = -1
    account: str = ""
    action_chk: str = ""
    cleared: str = ""
    payee: str = ""
    memo: str = ""
    rationale: str = ""
    tag: str = ""
    # Security transaction fields
    price: Decimal = Decimal("0")
    quantity: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    transfer_amount: Decimal = Decimal("0")
