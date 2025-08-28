# tests/test_qif_header.py
from quicken_helper.data_model.q_wrapper.qif_header import QifHeader


def test_qifentry_formats_record_exactly():
    # Arrange
    h = QifHeader(
        code="!Type:Bank", description="Bank section", type="Type"
    )  # :contentReference[oaicite:0]{index=0}
    # Act
    out = h.qif_entry()
    # Assert
    assert (
        out == "!Type:Bank\n^"
    ), "QifEntry should be 'code' + newline + '^' exactly."  # :contentReference[oaicite:1]{index=1}


def test_equality_compares_only_code_and_ignores_other_fields():
    # Arrange
    a = QifHeader(
        code="!Type:Bank", description="desc A", type="X"
    )  # :contentReference[oaicite:2]{index=2}
    b = QifHeader(code="!Type:Bank", description="desc B", type="Y")
    c = QifHeader(code="!Type:Invst", description="desc A", type="X")
    # Act / Assert
    assert (
        a == b
    ), "Same code ⇒ headers equal even if description/type differ."  # :contentReference[oaicite:3]{index=3}
    assert (
        a != c
    ), "Different code ⇒ headers not equal."  # :contentReference[oaicite:4]{index=4}


def test_equality_with_non_header_returns_false():
    # Arrange
    h = QifHeader(code="!Type:Bank", description="d", type="t")
    # Act / Assert
    assert (
        h == "!Type:Bank"
    ) is False, "__eq__ must return False for non-QifHeader objects."  # :contentReference[oaicite:5]{index=5}


def test_hash_is_based_on_code_and_consistent_with_equality():
    # Arrange
    a = QifHeader(code="!Type:Bank", description="a", type="x")
    b = QifHeader(code="!Type:Bank", description="b", type="y")
    c = QifHeader(code="!Type:Invst", description="a", type="x")
    # Act
    ha, hb, hc = hash(a), hash(b), hash(c)
    # Assert
    assert (
        ha == hb
    ), "Equal objects must have equal hashes (same code)."  # :contentReference[oaicite:6]{index=6}
    assert (
        ha != hc
    ), "Different code should generally produce a different hash."  # :contentReference[oaicite:7]{index=7}


def test_can_be_used_in_sets_and_dict_keys_uniquely_by_code():
    # Arrange
    a1 = QifHeader(code="!Type:Bank", description="a1", type="x")
    a2 = QifHeader(code="!Type:Bank", description="a2", type="y")
    b = QifHeader(code="!Type:Cash", description="b", type="x")
    # Act
    s = {a1, a2, b}  # set should de-duplicate by equality/hash
    d = {a1: "first", a2: "second", b: "cash"}  # a2 overwrites a1 since key equal
    # Assert
    assert len(s) == 2, "Set should contain one '!Type:Bank' and one '!Type:Cash' only."
    assert (
        d[a1] == "second" and d[a2] == "second"
    ), "Dict keying uses code equality; last value wins."  # :contentReference[oaicite:8]{index=8}


def test_changing_non_code_fields_does_not_affect_equality():
    # Arrange
    h1 = QifHeader(code="!Type:Bank", description="A", type="X")
    h2 = QifHeader(code="!Type:Bank", description="B", type="Y")
    # Act
    h1.description = "Changed"
    h1.type = "Changed"
    # Assert
    assert (
        h1 == h2
    ), "Equality is based on 'code' only; changing other fields must not matter."  # :contentReference[oaicite:9]{index=9}
