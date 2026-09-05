"""Backend-only Razorpay test-order execution and payment verification."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mandateguard.api.dependencies import get_evaluated_at, get_payment_service
from mandateguard.api.errors import ApiError
from mandateguard.api.schemas import (
    CreatePaymentOrderRequest,
    ErrorResponse,
    PaymentOrderResponse,
    PaymentVerificationResponse,
    VerifyPaymentRequest,
)
from mandateguard.db.repositories import RepositoryConflictError
from mandateguard.integrations.razorpay import RazorpayUnavailableError
from mandateguard.services.payments import (
    CheckoutAttemptNotFoundError,
    CheckoutExecutionError,
    PaymentOrderNotFoundError,
    PaymentService,
    PaymentVerificationError,
)

router = APIRouter(prefix="/payments", tags=["payments"])
ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (404, 409, 422, 502, 503)
}


@router.post("/orders", response_model=PaymentOrderResponse, responses=ERRORS)
def create_payment_order(
    body: CreatePaymentOrderRequest,
    evaluated_at: Annotated[datetime, Depends(get_evaluated_at)],
    service: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentOrderResponse:
    try:
        result = service.create_order(body.attempt_id, evaluated_at=evaluated_at)
    except CheckoutAttemptNotFoundError as exc:
        raise ApiError(
            404, "checkout_attempt_not_found", "Checkout attempt was not found."
        ) from exc
    except CheckoutExecutionError as exc:
        raise ApiError(
            409, "checkout_not_executable", "Checkout reservation is not executable."
        ) from exc
    except RazorpayUnavailableError as exc:
        raise ApiError(
            502, "razorpay_unavailable", "Razorpay test mode is unavailable.", retryable=True
        ) from exc
    except (RepositoryConflictError, IntegrityError) as exc:
        raise ApiError(
            409, "payment_state_conflict", "Payment state changed.", retryable=True
        ) from exc
    except SQLAlchemyError as exc:
        raise ApiError(
            503, "database_unavailable", "Database is unavailable.", retryable=True
        ) from exc
    return PaymentOrderResponse(
        provider_order_id=result.provider_order_id,
        attempt_id=result.attempt_id,
        amount_paise=result.amount_paise,
        currency="INR",
        status=result.status,
        provider_mode=result.provider_mode,
        checkout_key_id=result.checkout_key_id,
        replayed=result.replayed,
    )


@router.post("/verify", response_model=PaymentVerificationResponse, responses=ERRORS)
def verify_payment(
    body: VerifyPaymentRequest,
    evaluated_at: Annotated[datetime, Depends(get_evaluated_at)],
    service: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentVerificationResponse:
    try:
        result = service.verify_payment(
            provider_order_id=body.provider_order_id,
            provider_payment_id=body.provider_payment_id,
            signature=body.signature,
            evaluated_at=evaluated_at,
        )
    except PaymentOrderNotFoundError as exc:
        raise ApiError(404, "payment_order_not_found", "Payment order was not found.") from exc
    except PaymentVerificationError as exc:
        raise ApiError(409, "payment_verification_failed", "Payment verification failed.") from exc
    except (RepositoryConflictError, IntegrityError) as exc:
        raise ApiError(
            409, "payment_state_conflict", "Payment state changed.", retryable=True
        ) from exc
    except SQLAlchemyError as exc:
        raise ApiError(
            503, "database_unavailable", "Database is unavailable.", retryable=True
        ) from exc
    return PaymentVerificationResponse(
        provider_order_id=result.provider_order_id,
        provider_payment_id=result.provider_payment_id,
        attempt_id=result.attempt_id,
        status="paid",
        replayed=result.replayed,
    )
