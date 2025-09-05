# quicken_helper/data_model/i_header.py
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .i_comparable import IComparable
from .i_equatable import IEquatable
from .i_to_dict import IToDict


@runtime_checkable
class IHeader(Protocol, IComparable, IEquatable, IToDict):
    # data attributes
    code: str
    description: str
    type: str

    # behavior
    def qif_entry(self) -> str: ...
