from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Tuple, Optional
from .match_excel import fuzzy_autopairs

import pandas as pd

class CategoryMatchSession:
    """
    Manages category name mapping (Excel → QIF):
      - qif_cats: canonical names from QIF
      - excel_cats: names from Excel
      - mapping: excel_name -> qif_name
    """
    def __init__(self, qif_cats: List[str], excel_cats: List[str]):
        self.qif_cats = list(qif_cats)
        self.excel_cats = list(excel_cats)
        self.mapping: Dict[str, str] = {}

    def auto_match(self, threshold: float = 0.84):
        pairs, _, _ = fuzzy_autopairs(self.qif_cats, self.excel_cats, threshold)
        for qif_name, excel_name, _score in [(p[0], p[1], p[2]) for p in pairs]:
            self.mapping[excel_name] = qif_name

    def manual_match(self, excel_name: str, qif_name: str) -> Tuple[bool, str]:
        if excel_name not in self.excel_cats:
            return False, "Excel category not in list."
        if qif_name not in self.qif_cats:
            return False, "QIF category not in list."
        # ensure one-to-one by removing any other excel that mapped to this qif_name
        for k, v in list(self.mapping.items()):
            if v == qif_name and k != excel_name:
                self.mapping.pop(k, None)
        self.mapping[excel_name] = qif_name
        return True, "Matched."

    def manual_unmatch(self, excel_name: str) -> bool:
        return self.mapping.pop(excel_name, None) is not None

    def unmatched(self) -> Tuple[List[str], List[str]]:
        used_q = set(self.mapping.values())
        used_e = set(self.mapping.keys())
        uq = [q for q in self.qif_cats if q not in used_q]
        ue = [e for e in self.excel_cats if e not in used_e]
        return uq, ue

    def apply_to_excel(
        self,
        xlsx_in: Path,
        xlsx_out: Optional[Path] = None,
        col_name: str = "Canonical MECE Category",
    ) -> Path:
        """
        Writes a new Excel with the Canonical MECE Category values replaced by
        mapped QIF names where a mapping exists. Unmapped rows remain unchanged.
        """
        df = pd.read_excel(xlsx_in)
        if col_name not in df.columns:
            raise ValueError(f"Excel missing '{col_name}' column.")

        def _map_cell(v):
            s = str(v).strip() if pd.notna(v) else ""
            return self.mapping.get(s, s)

        df[col_name] = df[col_name].map(_map_cell)
        out = xlsx_out or xlsx_in.with_name(xlsx_in.stem + "_normalized.xlsx")
        df.to_excel(out, index=False)
        return out
