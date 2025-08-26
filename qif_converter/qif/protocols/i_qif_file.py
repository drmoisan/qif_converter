# qif_converter/qif/protocols/i_qif_file.py
from __future__ import annotations
from typing import Protocol, Iterable, runtime_checkable

from ..protocols import EnumQifSections, ITag, ICategory, HasEmitQifWithHeader, ITransaction, IAccount


@runtime_checkable
class IQifFile(Protocol):
    # --- data ---
    sections: EnumQifSections
    tags: list[ITag]
    categories: list[ICategory]
    accounts: list[IAccount]
    transactions: list[ITransaction]

    # --- behavior ---
    def emit_section(self, xs: Iterable[HasEmitQifWithHeader]) -> str: ...
    def emit_transactions(self) -> str: ...
    def emit_qif(self) -> str: ...
