# tests/test_qif_codes.py
from __future__ import annotations

import inspect
import types
import pytest

from qif_converter.data_model.qif_code import QifCode
import qif_converter.data_model.qif_codes as codes


def _assert_qifcode(obj: QifCode, expect_code: str):
    assert isinstance(obj, QifCode), "Factory must return QifCode"
    assert obj.code == expect_code, f"Expected code '{expect_code}', got '{obj.code}'"
    assert isinstance(obj.description, str) and obj.description, "Description should be non-empty"
    assert isinstance(obj.used_in, str) and obj.used_in, "used_in should be non-empty"
    assert isinstance(obj.example, str) and obj.example.startswith(expect_code), \
        "Example should start with its code letter(s)"


# ------------------------------
# Banking / Splits basics
# ------------------------------

def test_bank_and_split_codes_minimal_fields():
    # Arrange
    # (No external deps; direct calls)

    # Act
    adr = codes.address()               # "A"
    cat = codes.category()              # "L"
    split_cat = codes.category_split()   # "S"
    split_memo = codes.memo_split()      # "E"
    split_amt = codes.amount_split()     # "$"
    #split_pct = codes.PercentSplit()    # "%"

    # Assert
    _assert_qifcode(adr, "A")
    assert "Address" in adr.description
    assert "Banking" in adr.used_in or "Splits" in adr.used_in

    _assert_qifcode(cat, "L")
    assert "Category" in cat.description

    _assert_qifcode(split_cat, "S")
    _assert_qifcode(split_memo, "E")
    _assert_qifcode(split_amt, "$")
    #_assert_qifcode(split_pct, "%")


# ------------------------------
# Investment codes
# ------------------------------

@pytest.mark.parametrize(
    "factory, expect_code, must_contain",
    [
        (codes.investment_action, "N", "Investment"),
        (codes.name_security, "Y", "Security"),
        (codes.price_investment, "I", "Price"),
        (codes.quantity_shares, "Q", "Quantity"),
        (codes.commission_cost, "O", "Commission"),
        (codes.amount_transfered, "$", "Amount"),
    ]
)
def test_investment_codes(factory, expect_code, must_contain):
    # Arrange / Act
    c = factory()

    # Assert
    _assert_qifcode(c, expect_code)
    assert must_contain in c.description
    assert "Investment" in c.used_in or c.used_in == "Investment"


# ------------------------------
# Category / Budget code
# ------------------------------

def test_budget_code_is_categories_scoped():
    # Arrange / Act
    b = codes.budgeted_amount()

    # Assert
    _assert_qifcode(b, "B")
    assert "Budgeted" in b.description
    assert "Categories" in b.used_in


# ------------------------------
# Invoice “X*” codes
# ------------------------------

@pytest.mark.parametrize(
    "factory, expect_code",
    [
        (codes.x, "X"),
        (codes.x_ivoice_ship_to_address, "XA"),
        (codes.x_invoice_type, "XI"),
        (codes.x_invoice_due_date, "XE"),
        (codes.x_invoice_tax_account, "XC"),
        (codes.x_invoice_tax_rate, "XR"),
        (codes.x_invoice_tax_amount, "XT"),
        (codes.x_invoice_item_description, "XS"),
        (codes.x_invoice_category, "XN"),
        (codes.x_invoice_units, "X#"),
        (codes.x_invoice_price_per_unit, "X$"),
        (codes.x_invoice_taxable_flag, "XF"),
    ]
)
def test_invoice_subcodes(factory, expect_code):
    # Arrange / Act
    c = factory()

    # Assert
    _assert_qifcode(c, expect_code)
    assert "Invoice" in c.used_in or "Invoices" in c.used_in


# ------------------------------
# QifCode equality / hashing semantics
# ------------------------------

def test_qifcode_equality_hash_on_code_only():
    # Arrange
    a = QifCode("Z", "desc1", "where1", "Zex")
    b = QifCode("Z", "desc2", "where2", "Zexample-different")

    c = QifCode("Y", "desc", "where", "Yex")

    # Act / Assert
    # Equal if and only if .code matches (by implementation)
    assert a == b, "QifCode with same code must compare equal"
    assert hash(a) == hash(b), "Equal codes must have equal hashes"

    assert a != c
    assert hash(a) != hash(c)


# ------------------------------
# Sanity: every exported factory returns QifCode
# (keeps future additions honest, but avoids brittle exact list checks)
# ------------------------------

def test_all_callable_factories_return_qifcode():
    # Arrange
    public_funcs = [
        (name, obj) for name, obj in vars(codes).items()
        if not name.startswith("_") and isinstance(obj, types.FunctionType)
    ]

    # Act
    results = [(name, obj()) for name, obj in public_funcs]

    # Assert
    for name, val in results:
        assert isinstance(val, QifCode), f"{name} should return QifCode, got {type(val)!r}"
        # minimal structural sanity — example begins with the code
        assert val.example.startswith(val.code), f"{name} example must start with code '{val.code}'"

