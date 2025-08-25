from __future__ import annotations
from typing import Protocol, runtime_checkable
from ..protocols import QifHeaderLike

# Assumes you’ve defined QifHeaderLike elsewhere.
# If not, replace "QifHeaderLike" below with the concrete QifHeader.

@runtime_checkable
class QifAcctLike(Protocol):
    # --- data attributes ---
    name: str
    type: str
    description: str

    # --- header (read-only) ---
    @property
    def header(self) -> QifHeaderLike: ...

    # --- QIF emission ---
    def QifEntry(self, with_header: bool = False) -> str: ...

    # --- (optional) special methods to mirror equality/hash semantics ---
    def __eq__(self, other: object, /) -> bool: ...
    def __hash__(self) -> int: ...
