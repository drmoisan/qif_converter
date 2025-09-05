from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from .i_comparable import IComparable
from .i_equatable import IEquatable
from .i_header import IHeader
from .i_to_dict import IToDict

# Assumes you’ve defined QifHeaderLike elsewhere.
# If not, replace "QifHeaderLike" below with the concrete QifHeader.


@runtime_checkable
class IAccount(Protocol, IComparable, IEquatable, IToDict):
    # --- data attributes ---
    name: str
    type: str
    description: str
    limit: Decimal
    balance_date: date
    balance_amount: Decimal

    # --- header (read-only) ---
    @property
    def header(self) -> IHeader: ...

    # --- QIF emission ---
    def qif_entry(self, with_header: bool = False) -> str: ...
