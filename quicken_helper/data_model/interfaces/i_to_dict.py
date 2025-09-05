# quicken_helper/data_model/interfacts/i_to_dict.py
from __future__ import annotations

from typing import runtime_checkable

from typing_extensions import Protocol, TypeAlias

RecursiveDictStr: TypeAlias = str | dict[str, "RecursiveDictStr"]


@runtime_checkable
class IToDict(Protocol):
    def to_dict(self) -> dict[str, RecursiveDictStr]: ...
