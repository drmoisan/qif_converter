# quicken_helper/qif/interfaces/i_qif_file.py
from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from .i_has_emit_qif import HasEmitQifWithHeader
from .i_account import IAccount
from .i_category import ICategory
from .i_tag import ITag
from .i_transaction import ITransaction
from .enum_quicken_section import QuickenSections


@runtime_checkable
class IQuickenFile(Protocol):
    # --- data ---
    sections: QuickenSections
    tags: list[ITag]
    categories: list[ICategory]
    accounts: list[IAccount]
    transactions: list[ITransaction]

    # --- behavior ---
    def emit_section(self, xs: Iterable[HasEmitQifWithHeader]) -> str: ...
    def emit_transactions(self) -> str: ...
    def emit_qif(self) -> str: ...
