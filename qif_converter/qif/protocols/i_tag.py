from __future__ import annotations

from typing import runtime_checkable, Protocol
from ..protocols import HasEmitQifWithHeader, QifHeaderLike


@runtime_checkable
class TagLike(HasEmitQifWithHeader, Protocol):
    """
    Protocol for objects that behave like QifTag.

    Required attributes:
      - name: str
      - description: str

    Required members:
      - header -> QifHeader (read-only property)
      - emit_qif(with_header: bool = False) -> str

    Optional (declared for better structural typing/IDE hints):
      - __eq__(other: object) -> bool
      - __hash__() -> int
      - __repr__() -> str
    """

    # data attributes
    name: str
    description: str

    # read-only property
    @property
    def header(self) -> QifHeaderLike: ...

    # behavior
    #def emit_qif(self, with_header: bool = False) -> str: ...

    # (optional) special methods – not enforced at runtime, but help mypy/pyright
    def __eq__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...
