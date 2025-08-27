# tests/test_qif_account.py
from quicken_helper.data_model.q_wrapper.q_account import QAccount
from quicken_helper.data_model.q_wrapper.qif_header import QifHeader


def test_header_returns_expected_qifheader():
    # Arrange
    acct = QAccount(name="Checking", type="Bank", description="Primary Checking")

    # Act
    h = acct.header

    # Assert
    assert isinstance(h, QifHeader)
    assert h.code == "!Account"  # exact header code
    assert h.description == "Account list or which account follows"
    assert h.type == "Account"
    # Equality sanity check (QifHeader equality is code-based)
    assert h == QifHeader("!Account", "ignored desc", "ignored type")


def test_qifentry_without_header_emits_fields_and_caret():
    # Arrange
    acct = QAccount(name="Checking", type="Bank", description="My checking")

    # Act
    out = acct.qif_entry(with_header=False)

    # Assert
    assert out == "NChecking\nTBank\nDMy checking\n^"


def test_qifentry_with_header_includes_header_code_first():
    # Arrange
    acct = QAccount(name="Checking", type="Bank", description="My checking")

    # Act
    out = acct.qif_entry(with_header=True)

    # Assert
    expected = "!Account\nNChecking\nTBank\nDMy checking\n^"
    assert out == expected


def test_equality_and_hash_semantics():
    # Arrange
    a1 = QAccount(name="Checking", type="Bank", description="desc A")
    a2 = QAccount(name="Checking", type="Bank", description="desc B")  # desc differs, but __eq__ ignores it
    a3 = QAccount(name="Savings", type="Bank", description="desc A")
    not_acct = object()

    # Act / Assert
    # Equality is based on (name, type, header) — description is not part of equality
    assert a1 == a2
    assert hash(a1) == hash(a2)

    # Differences in name (or type) break equality and typically change hash
    assert a1 != a3
    assert hash(a1) != hash(a3)

    # Non-QifAcct comparisons return False
    assert (a1 == not_acct) is False


def test_defaults_emit_empty_fields_and_caret():
    # Arrange
    acct = QAccount()  # all defaults: empty strings

    # Act
    out_no_header = acct.qif_entry(with_header=False)
    out_with_header = acct.qif_entry(with_header=True)

    # Assert
    assert out_no_header == "N\nT\nD\n^"
    assert out_with_header == "!Account\nN\nT\nD\n^"
