from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, Field

MAX_DB_INTEGER = 2**63 - 1


class IntegerOverflowError(ValueError):
    pass


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def checked_add(left: int, right: int) -> int:
    result = left + right
    if result > MAX_DB_INTEGER:
        raise IntegerOverflowError("integer addition exceeds SQLite INTEGER range")
    return result


def checked_multiply(left: int, right: int) -> int:
    if left and right > MAX_DB_INTEGER // left:
        raise IntegerOverflowError("integer multiplication exceeds SQLite INTEGER range")
    return left * right


def checked_sum(values: Iterable[int]) -> int:
    total = 0
    for value in values:
        total = checked_add(total, value)
    return total


type Paise = Annotated[int, Field(strict=True, ge=0, le=MAX_DB_INTEGER)]
type PositiveQuantity = Annotated[int, Field(strict=True, ge=1, le=MAX_DB_INTEGER)]
type NonNegativeInteger = Annotated[int, Field(strict=True, ge=0, le=MAX_DB_INTEGER)]
type Identifier = Annotated[
    str, Field(strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
]
type CanonicalId = Annotated[
    str, Field(strict=True, min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
]
type CurrencyCode = Annotated[str, Field(strict=True, pattern=r"^[A-Z]{3}$")]
type UtcDateTime = Annotated[datetime, AfterValidator(normalize_utc)]
