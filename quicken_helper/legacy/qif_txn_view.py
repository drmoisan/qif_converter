from __future__ import annotations

from _decimal import Decimal
from dataclasses import dataclass
from datetime import date

from quicken_helper.legacy.qif_item_key import QIFItemKey


@dataclass
class QIFTxnView:
    """
    Transaction-level view used for matching. We always match whole transactions,
    not individual QIF splits. If a txn has splits, its 'amount' is the sum of splits;
    otherwise it is the txn amount field.
    """

    key: QIFItemKey  # split_index must be None here
    date: date
    amount: Decimal
    payee: str
    memo: str
    category: str
