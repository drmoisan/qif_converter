# qif_converter/qif/i_header.py
from __future__ import annotations
from typing import Protocol, runtime_checkable

@runtime_checkable
class QifHeaderLike(Protocol):
    # data attributes
    code: str
    description: str
    type: str

    # behavior
    def QifEntry(self) -> str: ...
    def __eq__(self, other: object, /) -> bool: ...
    def __hash__(self) -> int: ...
