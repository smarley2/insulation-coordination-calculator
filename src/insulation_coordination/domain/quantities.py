from decimal import Decimal
from typing import Annotated

from pydantic import BeforeValidator


def _decimal(value: object) -> Decimal:
    if isinstance(value, (bool, float)):
        raise TypeError("Engineering values must be Decimal, integer, or decimal text")
    return Decimal(value)  # type: ignore[arg-type]


def _positive_decimal(value: object) -> Decimal:
    decimal = _decimal(value)
    if not decimal.is_finite() or decimal <= 0:
        raise ValueError("Value must be greater than zero")
    return decimal


DecimalValue = Annotated[Decimal, BeforeValidator(_decimal)]
PositiveDecimal = Annotated[Decimal, BeforeValidator(_positive_decimal)]
