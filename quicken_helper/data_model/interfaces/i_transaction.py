# quicken_helper/data_model/i_qif_transaction.py
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from .enum_cleared_status import EnumClearedStatus
from .i_account import IAccount
from .i_comparable import IComparable
from .i_equatable import IEquatable
from .i_header import IHeader
from .i_security import ISecurity
from .i_split import ISplit
from .i_to_dict import IToDict


@runtime_checkable
class ITransaction(Protocol, IComparable, IEquatable, IToDict):
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

    # region Optional Fields With Sentinel Pattern

    # These fields may not be set, so we use a sentinel
    # value to indicate if it exists
    splits: list[ISplit]
    security: ISecurity

    def is_valid(self) -> bool: ...
    def security_exists(self) -> bool: ...
    def splits_exist(self) -> bool: ...

    # endregion Optional Fields With Sentinel Pattern

    # region Parser/Emitter

    def emit_category(self) -> str: ...
    def emit_qif(
        self, *, with_account: bool = False, with_type: bool = False
    ) -> str: ...

    # endregion Parser/Emitter
