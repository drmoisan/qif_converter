from __future__ import annotations

import pytest

from quicken_helper.utilities.core_util import parse_date_string


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


def test__open_for_read_uses_builtins_open(monkeypatch, tmp_path):
    # Arrange
    from quicken_helper.utilities.core_util import _open_for_read

    opened = {"called": False}
    expected = "hello world"

    class FakeReadable:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            pass

        def read(self, *_, **__):
            return expected

    def fake_open(file, mode="r", encoding=None, newline=None, **kwargs):
        opened["called"] = True
        # basic sanity: _open_for_read should open in text mode by default
        assert "b" not in mode
        return FakeReadable()

    monkeypatch.setattr("builtins.open", fake_open, raising=True)
    p = tmp_path / "sample.qif"

    # Act
    with _open_for_read(p) as f:
        data = f.read()

    # Assert
    assert opened["called"] is True, "Expected _open_for_read to call builtins.open"
    assert (
        data == expected
    ), "File-like object returned by _open_for_read should be readable"
