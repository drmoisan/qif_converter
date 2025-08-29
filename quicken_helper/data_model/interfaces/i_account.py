from __future__ import annotations

from typing import Protocol, runtime_checkable
from decimal import Decimal
from datetime import date

from .i_header import IHeader

# Assumes you’ve defined QifHeaderLike elsewhere.
# If not, replace "QifHeaderLike" below with the concrete QifHeader.


@runtime_checkable
class IAccount(Protocol):
    # --- data attributes ---
    name: str
    type: str
    description: str
    limit: Decimal | None = None
    balance_date: date | None = None
    balance_amount: Decimal | None = None

    # --- header (read-only) ---
    @property
    def header(self) -> IHeader: ...

    # --- QIF emission ---
    def qif_entry(self, with_header: bool = False) -> str: ...

    # --- (optional) special methods to mirror equality/hash semantics ---
    def __eq__(self, other: object, /) -> bool: ...
    def __hash__(self) -> int: ...
