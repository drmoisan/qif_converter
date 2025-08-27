from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class QifCode:
    code: str
    description: str
    used_in: str
    example: str

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, QifCode):
            return NotImplemented
        return self.code == other.code

    def __hash__(self) -> int:
        return hash(self.code)