# tests/utilities/test_from_dict.py
"""
Unit tests for core_util.from_dict.

Policy adherence:
- Independence & Isolation: Uses local test dataclasses; only imports the function under test.
- Fast & Deterministic: Pure in-memory construction; no I/O, no randomness.
- Readability: AAA pattern with explicit, helpful assertions.
- Coverage: Positive, edge/missing fields, nested objects, containers (list/tuple/dict),
  extra keys ignored.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict

import pytest

from quicken_helper.utilities.core_util import from_dict


# ---------- Test-only dataclasses (isolated from production code) ----------

@dataclass
class Child:
    """Simple nested dataclass used for recursion checks."""
    x: int
    y: str = "default-y"


@dataclass
class Parent:
    """Parent dataclass that exercises multiple field shapes."""
    name: str
    child: Child
    tags: List[str]
    coords: Tuple[int, int]
    meta: Dict[str, int]
    maybe: Optional[int] = None


@dataclass
class WithListOfChildren:
    """Dataclass with a list of nested dataclasses."""
    title: str
    children: List[Child] = field(default_factory=list)


# --------------------------------- Tests -----------------------------------

def test_from_dict_simple_nested_and_containers():
    """Positive: builds a Parent with nested Child, list/tuple/dict fields mapped correctly."""
    # Arrange
    payload = {
        "name": "Alice",
        "child": {"x": 7, "y": "seven"},
        "tags": ["a", "b"],
        "coords": (10, 20),
        "meta": {"k1": 1, "k2": 2},
        "maybe": None,
    }

    # Act
    obj = from_dict(Parent, payload)

    # Assert
    assert isinstance(obj, Parent), "Should return a Parent instance"
    assert obj.name == "Alice"
    assert isinstance(obj.child, Child), "Nested dict should become a Child instance"
    assert (obj.child.x, obj.child.y) == (7, "seven")
    assert obj.tags == ["a", "b"], "List field should be preserved"
    assert obj.coords == (10, 20), "Tuple field should be preserved"
    assert obj.meta == {"k1": 1, "k2": 2}, "Dict field should be preserved"
    assert obj.maybe is None, "Optional field should allow None"


def test_from_dict_uses_child_default_when_field_omitted():
    """Positive/edge: omitted optional field in a nested dataclass uses dataclass default."""
    # Arrange
    payload = {
        "name": "Bob",
        "child": {"x": 5},  # omit 'y' -> should use Child.y default
        "tags": [],
        "coords": (0, 0),
        "meta": {},
    }

    # Act
    obj = from_dict(Parent, payload)

    # Assert
    assert obj.child.x == 5
    assert obj.child.y == "default-y", "Omitted field should default via dataclass default"


def test_from_dict_missing_optional_on_parent_is_set_none():
    """Edge: missing optional field on the parent should become None (explicit contract)."""
    # Arrange
    payload = {
        "name": "Carol",
        "child": {"x": 1, "y": "one"},
        "tags": ["z"],
        "coords": (1, 2),
        "meta": {},
        # 'maybe' omitted
    }

    # Act
    obj = from_dict(Parent, payload)

    # Assert
    assert obj.maybe is None, "Missing Optional[int] should be set to None"


def test_from_dict_list_of_nested_dataclasses():
    """Positive: builds a list of Child instances from a list of dicts."""
    # Arrange
    payload = {
        "title": "Group",
        "children": [{"x": 1}, {"x": 2, "y": "two"}],  # rely on child default for first
    }

    # Act
    obj = from_dict(WithListOfChildren, payload)

    # Assert
    assert isinstance(obj, WithListOfChildren)
    assert [type(c).__name__ for c in obj.children] == ["Child", "Child"]
    assert [(c.x, c.y) for c in obj.children] == [(1, "default-y"), (2, "two")]


def test_from_dict_ignores_extra_keys_in_payload():
    """Negative/robustness: extra keys in payload should not break construction."""
    # Arrange
    payload = {
        "name": "Extra",
        "child": {"x": 9, "y": "nine", "not_used": "ignored"},
        "tags": ["t"],
        "coords": (3, 4),
        "meta": {"a": 10},
        "maybe": 42,
        "unused_at_top": True,  # extra key at root
    }

    # Act
    obj = from_dict(Parent, payload)

    # Assert
    assert obj.name == "Extra"
    assert obj.child.x == 9 and obj.child.y == "nine"
    assert obj.maybe == 42
    # The presence of extra keys should not raise nor affect the mapped fields
    assert hasattr(obj, "name") and hasattr(obj, "child") and hasattr(obj, "meta")


def test_from_dict_type_passthrough_for_primitives():
    """Positive: calling from_dict on a primitive type should return the value unchanged."""
    # Arrange
    value = 123

    # Act
    out = from_dict(int, value)

    # Assert
    assert out == 123
    assert isinstance(out, int), "Primitive types should pass through unchanged"
