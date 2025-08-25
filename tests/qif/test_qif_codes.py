# tests/test_qif_codes.py
from __future__ import annotations

import inspect
import types
import pytest

from qif_converter.qif.qif_code import QifCode
import qif_converter.qif.qif_codes as codes


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
    adr = codes.Address()               # "A"
    cat = codes.Category()              # "L"
    split_cat = codes.CategorySplit()   # "S"
    split_memo = codes.MemoSplit()      # "E"
    split_amt = codes.AmountSplit()     # "$"
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
        (codes.InvestmentAction, "N", "Investment"),
        (codes.NameSecurity, "Y", "Security"),
        (codes.PriceInvestment, "I", "Price"),
        (codes.QuantityShares, "Q", "Quantity"),
        (codes.CommissionCost, "O", "Commission"),
        (codes.AmountTransfered, "$", "Amount"),
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
    b = codes.BudgetedAmount()

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
        (codes.X, "X"),
        (codes.XIvoiceShipToAddress, "XA"),
        (codes.XInvoiceType, "XI"),
        (codes.XInvoiceDueDate, "XE"),
        (codes.XInvoiceTaxAccount, "XC"),
        (codes.XInvoiceTaxRate, "XR"),
        (codes.XInvoiceTaxAmount, "XT"),
        (codes.XInvoiceItemDescription, "XS"),
        (codes.XInvoiceCategory, "XN"),
        (codes.XInvoiceUnits, "X#"),
        (codes.XInvoicePricePerUnit, "X$"),
        (codes.XInvoiceTaxableFlag, "XF"),
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

