# tests/test_qif_file.py
from __future__ import annotations

import pytest
from typing import cast
from qif_converter.qif import QuickenFile, QuickenSections, ITag, ICategory, HasEmitQifWithHeader


class _StubCategory:
    def __init__(self, name="DefaultCatName", description="DefaultCatDescription"):
        self.name = name
        self.description = description
        self.calls: list[bool] = []

    @property
    def header(self):
        # Return a real header to keep serialization realistic
        from qif_converter.qif.qif_header import QifHeader
        return QifHeader(code="!Type:Category", description="Category list", type="Category")

    def emit_qif(self, with_header: bool = False) -> str:
        body = f"N{self.name}\nD{self.description}\n^"
        self.calls.append(with_header)
        if with_header:
            return f"{self.header.code}\n{body}"
        return body

class _StubTag:
    def __init__(self, name="DefaultTagName", description="DefaultTagDescription"):
        self.name = name
        self.description = description
        self.calls: list[bool] = []

    @property
    def header(self):
        # Return a real header to keep serialization realistic
        from qif_converter.qif.qif_header import QifHeader
        return QifHeader(code="!Type:Tag", description="Tag list", type="Tag")

    def emit_qif(self, with_header: bool = False) -> str:
        body = f"N{self.name}\nD{self.description}\n^"
        self.calls.append(with_header)
        if with_header:
            return f"{self.header.code}\n{body}"
        return body


class _StubItem:
    """
    Minimal stub that mimics QifFile.HasEmitQif: it exposes
    emit_qif(with_header=bool) and records how it was called.
    """
    def __init__(self, body: str, header: str = "!Stub"):
        self.body = body
        self.header = header
        self.calls: list[bool] = []

    # match keyword-only param exactly
    def emit_qif(self, with_header: bool) -> str:
        self.calls.append(with_header)
        return f"{self.header}\n{self.body}" if with_header else self.body


def test_constructor_initializes_empty_lists_and_none_section():
    # Arrange
    f = QuickenFile()  # account arg is ignored in current impl

    # Act / Assert
    # (AAA: no special Act needed—constructor state is asserted directly.)
    assert f.sections == QuickenSections.NONE
    assert f.tags == []
    assert f.categories == []
    assert f.accounts == []
    assert f.transactions == []


def test_emit_section_sets_with_header_true_only_for_first_item():
    # Arrange
    f = QuickenFile()
    a = _StubItem("A")
    b = _StubItem("B")
    items = [a, b]
    # tell the type checker these satisfy the protocol
    proto_items = cast(list[HasEmitQifWithHeader], items)

    # Act
    out = f.emit_section(proto_items)

    # Assert
    assert out == "!Stub\nA\nB"
    assert a.calls == [True], "First item must be called with with_header=True"
    assert b.calls == [False], "Subsequent items must be called with with_header=False"


def test_emit_qif_raises_when_no_section_selected():
    # Arrange
    f = QuickenFile()
    f.sections = QuickenSections.NONE

    # Act / Assert
    with pytest.raises(ValueError):
        f.emit_qif()


def test_emit_qif_concatenates_selected_sections_in_order_and_ends_with_newline():
    # Arrange
    f = QuickenFile()
    # Enable TAGS then CATEGORIES (order matters in output)
    f.sections = QuickenSections.TAGS | QuickenSections.CATEGORIES

    t1, t2 = _StubTag("tag1"), _StubTag("tag2")
    items = [t1, t2]
    proto_items = cast(list[ITag], items)

    c1 =  _StubCategory("cat1")
    c1_proto = cast(ICategory, c1)

    f.tags = proto_items
    f.categories = [c1_proto]

    # Act
    out = f.emit_qif()

    # Assert
    # The first item of each section is emitted with header, others without.
    # Sections are appended in the order TAGS, CATEGORIES.
    expected = "!Type:Tag\nNtag1\nDDefaultTagDescription\n^\nNtag2\nDDefaultTagDescription\n^\n!Type:Category\nNcat1\nDDefaultCatDescription\n^"
    assert out == expected

    assert t1.calls == [True]
    assert t2.calls == [False]
    assert c1.calls == [True]


def test_emit_qif_can_emit_any_subset_of_sections_independently():
    # Arrange
    f = QuickenFile()
    # Only CATEGORIES selected
    f.sections = QuickenSections.CATEGORIES
    c1, c2 = _StubCategory("c1"), _StubCategory("c2")
    f.categories = cast(list[ICategory], [c1, c2])

    # Act
    out = f.emit_qif()

    # Assert
    expected = "!Type:Category\nNc1\nDDefaultCatDescription\n^\nNc2\nDDefaultCatDescription\n^"
    assert out == expected
    assert c1.calls == [True]
    assert c2.calls == [False]


def test_emit_transactions_returns_empty_when_no_transactions():
    # Arrange
    f = QuickenFile()
    f.transactions = []

    # Act
    out = f.emit_transactions()

    # Assert
    assert out == ""
