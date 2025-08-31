# quicken_helper/data_model/interfaces/i_quicken_file.py
from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable, TYPE_CHECKING

# typing-only to avoid runtime import cycles
if TYPE_CHECKING:
    from .i_parser_emitter import IParserEmitter

from .enum_quicken_section import QuickenSections
from .i_account import IAccount
from .i_category import ICategory
from .i_has_emit_qif import HasEmitQifWithHeader
from .i_tag import ITag
from .i_transaction import ITransaction


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

    # --- optional back-reference to the emitter (typing-only) ---
    emitter: "IParserEmitter[IQuickenFile] | None"  # new