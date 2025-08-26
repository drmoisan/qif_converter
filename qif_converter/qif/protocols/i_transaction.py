# qif_converter/qif/i_qif_transaction.py
from __future__ import annotations

from decimal import Decimal
from datetime import date
from typing import Protocol, runtime_checkable

from ..protocols import ISplit, ISecurity, IAccount, IHeader, ClearedStatus

@runtime_checkable
class ITransaction(Protocol):
    """Structural shape of a QIF transaction sufficient for file emission."""
    account: IAccount
    type: IHeader
    date: date
    action_chk: str
    amount: Decimal
    cleared: ClearedStatus
    payee: str
    memo: str
    category: str
    tag: str

    splits: list[ISplit]

    def security_exists(self) -> bool: ...
    @property
    def security(self) -> ISecurity: ...

    def emit_category(self) -> str: ...
    def emit_qif(self, *, with_account: bool = False, with_type: bool = False) -> str: ...

    def to_dict(self) -> dict: ...