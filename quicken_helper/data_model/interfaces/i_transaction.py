# quicken_helper/qif/i_qif_transaction.py
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from .enum_cleared_status import EnumClearedStatus
from .i_account import IAccount
from .i_header import IHeader
from .i_security import ISecurity
from .i_split import ISplit


@runtime_checkable
class ITransaction(Protocol):
    """Structural shape of a QIF transaction sufficient for file emission."""

    account: IAccount
    type: IHeader
    date: date
    action_chk: str
    amount: Decimal
    cleared: EnumClearedStatus
    payee: str
    memo: str
    category: str
    tag: str

    splits: list[ISplit]

    def security_exists(self) -> bool: ...
    @property
    def security(self) -> ISecurity: ...

    def emit_category(self) -> str: ...
    def emit_qif(
        self, *, with_account: bool = False, with_type: bool = False
    ) -> str: ...

    def to_dict(self) -> dict: ...
