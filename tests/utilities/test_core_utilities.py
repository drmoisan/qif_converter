from __future__ import annotations

import pytest
from qif_converter.utilities.core_util import parse_date_string

# ---------- _parse_qif_date ----------
@pytest.mark.parametrize(
    "raw,expect_iso",
    [
        ("12/31'24", "2024-12-31"),
        ("12/31/2024", "2024-12-31"),
        ("2024-12-31", "2024-12-31"),
        ("2024/12/31", "2024-12-31"),
    ],
)
def test__parse_qif_date_formats(raw, expect_iso):
    d = parse_date_string(raw)
    assert d.isoformat() == expect_iso
