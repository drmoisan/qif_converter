from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..interfaces import HasEmitQifWithHeader, IHeader


@runtime_checkable
class ITag(HasEmitQifWithHeader, Protocol):
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
    def header(self) -> IHeader: ...

    # behavior
    #def emit_qif(self, with_header: bool = False) -> str: ...

    # (optional) special methods – not enforced at runtime, but help mypy/pyright
    def __eq__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...
