from __future__ import annotations

import pytest

from modules.farm_system.security import (
    hash_password,
    normalize_username,
    verify_password,
)
from modules.farm_system.tags import coc_tag_key


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("correct-horse-1")
    second = hash_password("correct-horse-1")

    assert first != second
    assert verify_password("correct-horse-1", first)
    assert not verify_password("wrong-password", first)
    assert not verify_password("correct-horse-1", "broken")


def test_username_normalization_requires_and_normalizes_email():
    assert normalize_username("  Farm.Admin@Example.COM  ") == "farm.admin@example.com"
    with pytest.raises(ValueError):
        normalize_username("farm.admin")
    with pytest.raises(ValueError):
        normalize_username("bad name@example.com")
    with pytest.raises(ValueError):
        normalize_username("bad@example")


def test_coc_tag_key_treats_letter_o_as_zero():
    assert coc_tag_key(" #ycoc ") == "#YC0C"
    assert coc_tag_key("#YC0C") == "#YC0C"
