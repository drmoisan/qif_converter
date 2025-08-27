# tests/test_qif_category.py


from quicken_helper.data_model import QCategory, QifHeader

# --------------------------
# Arrange–Act–Assert (AAA)
# --------------------------

def test_header_returns_expected_qifheader():
    # Arrange
    c = QCategory(name="Food", description="Groceries")
    # Act
    h = c.header
    # Assert
    assert isinstance(h, QifHeader)
    assert h.code == "!Type:Cat"
    # QifHeader equality is code-only; description/type don’t affect equality
    assert h == QifHeader("!Type:Cat", "ignored", "ignored")


def test_emit_qif_without_header_minimal_lines():
    # Arrange
    c = QCategory(name="Food", description="Groceries")
    # Act
    out = c.emit_qif(with_header=False)
    # Assert
    # Category emitter (unlike accounts) does not append '^' per implementation
    assert out == "NFood\nDGroceries"


def test_emit_qif_with_header_includes_header_first():
    # Arrange
    c = QCategory(name="Utilities", description="Power & water")
    # Act
    out = c.emit_qif(with_header=True)
    # Assert
    # Exact ordering: header line, then N, then D (no caret per implementation)
    assert out == "!Type:Cat\nNUtilities\nDPower & water"


def test_equality_ignores_description_and_relies_on_name_and_header():
    # Arrange
    a = QCategory(name="Food", description="Desc A")
    b = QCategory(name="Food", description="Desc B")  # different description
    # Act / Assert
    assert a == b, "Descriptions differ but equality is based on name + header only."
    # Hash must be consistent with equality
    assert hash(a) == hash(b)


def test_not_equal_when_name_differs_or_object_type_differs():
    # Arrange
    a = QCategory(name="Food", description="x")
    b = QCategory(name="Fuel", description="x")
    # Act / Assert
    assert a != b, "Different names should not be equal."
    assert a != object(), "Different types should not be equal."


def test_set_semantics_de_duplicate_by_name_and_header_only():
    # Arrange
    a1 = QCategory(name="Entertainment", description="A")
    a2 = QCategory(name="Entertainment", description="B")  # same name, diff desc
    b = QCategory(name="Bills", description="C")
    # Act
    s = {a1, a2, b}
    # Assert
    # a1 and a2 collapse to one because equality/hash ignore description
    assert len(s) == 2
    assert any(x.name == "Entertainment" for x in s)
    assert any(x.name == "Bills" for x in s)
