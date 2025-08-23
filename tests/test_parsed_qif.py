# tests/test_parsed_qif.py
from __future__ import annotations

import copy
from dataclasses import asdict
from typing import Dict, Any, List

import pytest

from qif_converter.qif_parsed import ParsedQIF


def test_parsedqif_defaults_are_empty_and_isolated():
    # Arrange & Act
    p1 = ParsedQIF()
    p2 = ParsedQIF()

    # Assert: all defaults are empty collections
    assert p1.transactions == []
    assert p1.accounts == []
    assert p1.categories == []
    assert p1.memorized_payees == []
    assert p1.securities == []
    assert p1.business_list == []
    assert p1.payees == []
    assert p1.other_sections == {}

    # Assert: instances do not share default lists/dicts
    p1.transactions.append({"date": "2025-01-01", "amount": "-10.00"})
    p1.accounts.append({"name": "Checking"})
    p1.other_sections.setdefault("Custom", []).append({"k": "v"})

    assert p2.transactions == []
    assert p2.accounts == []
    assert "Custom" not in p2.other_sections


def test_parsedqif_accepts_initial_values():
    # Arrange
    txns = [{"date": "2025-01-02", "amount": "-20.00"}]
    accts = [{"name": "Savings"}]
    cats = [{"name": "Food"}]
    mem = [{"payee": "Store", "category": "Food"}]
    secs = [{"symbol": "ABC"}]
    biz = [{"vendor": "Some LLC"}]
    payees = [{"name": "Bob"}]
    other = {"Foo": [{"x": 1}], "Bar": []}

    # Act
    p = ParsedQIF(
        transactions=txns,
        accounts=accts,
        categories=cats,
        memorized_payees=mem,
        securities=secs,
        business_list=biz,
        payees=payees,
        other_sections=other,
    )

    # Assert: values are preserved
    assert p.transactions == txns
    assert p.accounts == accts
    assert p.categories == cats
    assert p.memorized_payees == mem
    assert p.securities == secs
    assert p.business_list == biz
    assert p.payees == payees
    assert p.other_sections == other


def test_parsedqif_equality_by_value():
    # Arrange
    data = dict(
        transactions=[{"date": "2025-02-01", "amount": "-5.00"}],
        accounts=[{"name": "Checking"}],
        categories=[{"name": "Groceries"}],
        memorized_payees=[{"payee": "Market", "category": "Groceries"}],
        securities=[{"symbol": "XYZ"}],
        business_list=[{"vendor": "Acme Inc."}],
        payees=[{"name": "Alice"}],
        other_sections={"Z": [{"k": "v"}]},
    )
    p1 = ParsedQIF(**copy.deepcopy(data))
    p2 = ParsedQIF(**copy.deepcopy(data))

    # Act & Assert
    assert p1 == p2

    # Changing one field should break equality
    p2.transactions.append({"date": "2025-02-02", "amount": "-1.00"})
    assert p1 != p2


def test_parsedqif_asdict_roundtrip():
    # Arrange
    original = ParsedQIF(
        transactions=[{"date": "2025-03-01", "amount": "-12.00", "memo": "Coffee"}],
        other_sections={"Extra": [{"foo": "bar"}]},
    )

    # Act
    d: Dict[str, Any] = asdict(original)
    roundtrip = ParsedQIF(**d)

    # Assert
    assert roundtrip == original
    # Ensure dict structure looks sane for API consumers
    assert set(d.keys()) == {
        "transactions",
        "accounts",
        "categories",
        "memorized_payees",
        "securities",
        "business_list",
        "payees",
        "other_sections",
    }


def test_parsedqif_other_sections_allows_arbitrary_keys():
    # Arrange
    custom = {
        "SomeUnknownList": [{"a": 1}, {"a": 2}],
        "AnotherList": [],
    }
    p = ParsedQIF(other_sections=custom)

    # Act & Assert
    assert "SomeUnknownList" in p.other_sections
    assert p.other_sections["SomeUnknownList"] == [{"a": 1}, {"a": 2}]
    assert "AnotherList" in p.other_sections
    assert p.other_sections["AnotherList"] == []


def test_parsedqif_collections_are_mutable_per_instance():
    # Arrange
    p = ParsedQIF()

    # Act
    p.transactions.append({"date": "2025-04-01", "amount": "-3.00"})
    p.accounts.extend([{"name": "Brokerage"}])
    p.other_sections.setdefault("X", []).append({"k": "v"})

    # Assert
    assert p.transactions == [{"date": "2025-04-01", "amount": "-3.00"}]
    assert p.accounts == [{"name": "Brokerage"}]
    assert p.other_sections["X"] == [{"k": "v"}]
