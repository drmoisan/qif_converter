#qif_converter/qif/protocols/i_has_emit_qif.py
from __future__ import annotations
from typing import runtime_checkable, Protocol

@runtime_checkable
class HasEmitQifNoHeader(Protocol):
    """
    Minimal protocol for items that can emit QIF without a header flag.
    """
    def emit_qif(self) -> str: ...
    #def emit_qif_lines(self) -> Iterable[str]: ...


@runtime_checkable
class HasEmitQifWithHeader(Protocol):
    """
    Extended protocol for items that can optionally include a header.
    Implementations accept a keyword-only `with_header` flag.
    """
    def emit_qif(self, *, with_header: bool = True) -> str: ...
    #def emit_qif_lines(self, with_header: bool = True) -> Iterable[str]: ...


HasEmitQif = HasEmitQifNoHeader | HasEmitQifWithHeader
