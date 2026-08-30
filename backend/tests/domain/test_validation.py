from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from mandateguard.domain import MAX_DB_INTEGER, Product
from mandateguard.domain.validation import (
    IntegerOverflowError,
    checked_add,
    checked_multiply,
)


def product_with_price(value: object) -> Product:
    return Product(
        product_id="product-1",
        merchant_id="acme",
        category_id="office",
        currency="INR",
        unit_price_paise=value,
        inventory_count=1,
        price_version=1,
        inventory_version=1,
        active=True,
    )


@pytest.mark.parametrize("value", [True, 1.0, -1, MAX_DB_INTEGER + 1])
def test_money_rejects_non_integer_or_out_of_range_values(value: object) -> None:
    with pytest.raises(ValidationError):
        product_with_price(value)


def test_money_accepts_sqlite_integer_boundaries() -> None:
    assert product_with_price(0).unit_price_paise == 0
    assert product_with_price(MAX_DB_INTEGER).unit_price_paise == MAX_DB_INTEGER


def test_checked_operations_reject_overflow() -> None:
    with pytest.raises(IntegerOverflowError):
        checked_add(MAX_DB_INTEGER, 1)
    with pytest.raises(IntegerOverflowError):
        checked_multiply(MAX_DB_INTEGER, 2)


@given(value=st.integers(min_value=MAX_DB_INTEGER // 2 + 1, max_value=MAX_DB_INTEGER))
def test_checked_multiply_always_rejects_generated_overflow(value: int) -> None:
    with pytest.raises(IntegerOverflowError):
        checked_multiply(value, 2)


@given(value=st.integers(min_value=1, max_value=MAX_DB_INTEGER))
def test_checked_add_always_rejects_generated_overflow(value: int) -> None:
    with pytest.raises(IntegerOverflowError):
        checked_add(MAX_DB_INTEGER, value)


@given(
    left=st.integers(min_value=0, max_value=1_000_000),
    right=st.integers(min_value=0, max_value=1_000_000),
)
def test_checked_multiply_matches_integer_arithmetic_when_in_range(left: int, right: int) -> None:
    assert checked_multiply(left, right) == left * right


def test_timestamps_normalize_to_utc_and_reject_naive_values() -> None:
    product = product_with_price(1).model_copy(
        update={"offer_expires_at": datetime(2026, 8, 30, 12, tzinfo=UTC)}
    )
    assert product.offer_expires_at is not None
    with pytest.raises(ValidationError):
        Product(
            **{
                **product.model_dump(exclude={"offer_expires_at"}),
                "offer_expires_at": datetime(2026, 8, 30, 12),
            }
        )
