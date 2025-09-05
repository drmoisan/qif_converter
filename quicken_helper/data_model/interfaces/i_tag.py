from __future__ import annotations

from typing import Protocol, runtime_checkable

from .i_comparable import IComparable
from .i_equatable import IEquatable
from .i_has_emit_qif import HasEmitQifWithHeader
from .i_header import IHeader
from .i_to_dict import IToDict


@runtime_checkable
class ITag(HasEmitQifWithHeader, Protocol, IComparable, IEquatable, IToDict):
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
