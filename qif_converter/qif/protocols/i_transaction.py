# qif_converter/qif/i_qif_transaction.py
from __future__ import annotations

from decimal import Decimal
from datetime import date
from typing import Protocol, runtime_checkable

from ..protocols import QifSplitLike, QifSecurityTxnLike, QifAcctLike, QifHeaderLike, ClearedStatus

@runtime_checkable
class QifTxnLike(Protocol):
    """Structural shape of a QIF transaction sufficient for file emission."""
    account: QifAcctLike
    type: QifHeaderLike
    date: date
    action_chk: str
    amount: Decimal
    cleared: ClearedStatus
    payee: str
    memo: str
    category: str
    tag: str

    splits: list[QifSplitLike]

    def security_exists(self) -> bool: ...
    @property
    def security(self) -> QifSecurityTxnLike: ...

    def emit_category(self) -> str: ...
    def emit_qif(self, *, with_account: bool = False, with_type: bool = False) -> str: ...
