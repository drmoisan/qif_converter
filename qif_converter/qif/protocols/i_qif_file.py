# qif_converter/qif/protocols/i_qif_file.py
from __future__ import annotations
from typing import Protocol, Iterable, runtime_checkable

from ..protocols import EnumQifSections, TagLike, CategoryLike, HasEmitQifWithHeader, QifTxnLike, QifAcctLike


@runtime_checkable
class QifFileLike(Protocol):
    # --- data ---
    sections: EnumQifSections
    tags: list[TagLike]
    categories: list[CategoryLike]
    accounts: list[QifAcctLike]
    transactions: list[QifTxnLike]

    # --- behavior ---
    def emit_section(self, xs: Iterable[HasEmitQifWithHeader]) -> str: ...
    def emit_transactions(self) -> str: ...
    def emit_qif(self) -> str: ...
