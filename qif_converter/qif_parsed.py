from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class ParsedQIF:
    transactions: List[Dict[str, Any]] = field(default_factory=list)
    accounts: List[Dict[str, Any]] = field(default_factory=list)
    categories: List[Dict[str, Any]] = field(default_factory=list)
    memorized_payees: List[Dict[str, Any]] = field(default_factory=list)
    securities: List[Dict[str, Any]] = field(default_factory=list)
    business_list: List[Dict[str, Any]] = field(default_factory=list)  # classes/business
    payees: List[Dict[str, Any]] = field(default_factory=list)
    other_sections: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
