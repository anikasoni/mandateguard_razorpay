"""Backend-only checkout execution and payment-signature verification."""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from mandateguard.core.config import Settings
from mandateguard.db.models import PaymentOrderRecord
from mandateguard.db.repositories import CheckoutAttemptRepository, PaymentOrderRepository
from mandateguard.db.session import SessionFactory, immediate_policy_session
from mandateguard.domain.enums import CheckoutStatus
from mandateguard.domain.validation import normalize_utc
from mandateguard.integrations.razorpay import RazorpayOrdersClient


class CheckoutExecutionError(RuntimeError):
    pass


class CheckoutAttemptNotFoundError(LookupError):
    pass


class PaymentOrderNotFoundError(LookupError):
    pass


class PaymentVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PaymentOrderResult:
    provider_order_id: str
    attempt_id: str
    amount_paise: int
    currency: str
    status: Literal["created", "paid"]
    provider_mode: Literal["razorpay_test", "simulated"]
    checkout_key_id: str | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class PaymentVerificationResult:
    provider_order_id: str
    provider_payment_id: str
    attempt_id: str
    status: str
    replayed: bool


class PaymentService:
    """Execute only a live guarded reservation and verify payment on the backend."""

    def __init__(self, session_factory: SessionFactory, settings: Settings) -> None:
        self._session_factory = session_factory
        self._key_id = settings.razorpay_key_id
        self._key_secret = (
            settings.razorpay_key_secret.get_secret_value()
            if settings.razorpay_key_secret is not None
            else None
        )

    def create_order(self, attempt_id: str, *, evaluated_at: datetime) -> PaymentOrderResult:
        timestamp = normalize_utc(evaluated_at)
        result: PaymentOrderResult | None = None
        with immediate_policy_session(self._session_factory) as session:
            attempts = CheckoutAttemptRepository(session)
            orders = PaymentOrderRepository(session)
            existing = orders.get_by_attempt(attempt_id)
            if existing is not None:
                result = self._result(existing, replayed=True)
            else:
                attempt = attempts.get(attempt_id)
                if attempt is None:
                    raise CheckoutAttemptNotFoundError("checkout attempt not found")
                if (
                    attempt.status is not CheckoutStatus.RESERVED
                    or attempt.reservation_expires_at is None
                    or attempt.reservation_expires_at <= timestamp
                ):
                    raise CheckoutExecutionError("checkout reservation is not executable")
                receipt = f"mg-{hashlib.sha256(attempt_id.encode()).hexdigest()[:32]}"
                if self._key_id is not None and self._key_secret is not None:
                    provider = RazorpayOrdersClient(self._key_id, self._key_secret).create_order(
                        amount_paise=attempt.amount_paise,
                        currency=attempt.currency,
                        receipt=receipt,
                        attempt_id=attempt.attempt_id,
                    )
                    provider_order_id = provider.order_id
                    mode: Literal["razorpay_test", "simulated"] = "razorpay_test"
                else:
                    provider_order_id = (
                        f"order_demo_{hashlib.sha256(attempt_id.encode()).hexdigest()[:20]}"
                    )
                    mode = "simulated"
                record = PaymentOrderRecord(
                    provider_order_id=provider_order_id,
                    attempt_id=attempt.attempt_id,
                    receipt=receipt,
                    amount_paise=attempt.amount_paise,
                    currency=attempt.currency,
                    provider_mode=mode,
                    status="created",
                    provider_payment_id=None,
                    created_at=timestamp,
                    paid_at=None,
                )
                orders.add(record)
                attempts.mark_created(attempt_id)
                session.flush()
                result = self._result(record, replayed=False)
        if result is None:
            raise RuntimeError("payment transaction committed without a result")
        return result

    def verify_payment(
        self,
        *,
        provider_order_id: str,
        provider_payment_id: str,
        signature: str,
        evaluated_at: datetime,
    ) -> PaymentVerificationResult:
        timestamp = normalize_utc(evaluated_at)
        if self._key_secret is None:
            raise PaymentVerificationError("Razorpay verification is not configured")
        expected = hmac.new(
            self._key_secret.encode(),
            f"{provider_order_id}|{provider_payment_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise PaymentVerificationError("payment signature is invalid")

        result: PaymentVerificationResult | None = None
        with immediate_policy_session(self._session_factory) as session:
            orders = PaymentOrderRepository(session)
            order = orders.get(provider_order_id)
            if order is None:
                raise PaymentOrderNotFoundError("payment order not found")
            if order.provider_mode != "razorpay_test":
                raise PaymentVerificationError("simulated orders cannot be verified")
            replayed = order.status == "paid"
            if replayed:
                if order.provider_payment_id != provider_payment_id:
                    raise PaymentVerificationError("payment identity conflicts with stored order")
            else:
                order = orders.mark_paid(
                    provider_order_id,
                    provider_payment_id=provider_payment_id,
                    paid_at=timestamp,
                )
                CheckoutAttemptRepository(session).mark_completed(order.attempt_id)
                session.flush()
            result = PaymentVerificationResult(
                provider_order_id=order.provider_order_id,
                provider_payment_id=provider_payment_id,
                attempt_id=order.attempt_id,
                status="paid",
                replayed=replayed,
            )
        if result is None:
            raise RuntimeError("payment verification committed without a result")
        return result

    def _result(self, record: PaymentOrderRecord, *, replayed: bool) -> PaymentOrderResult:
        return PaymentOrderResult(
            provider_order_id=record.provider_order_id,
            attempt_id=record.attempt_id,
            amount_paise=record.amount_paise,
            currency=record.currency,
            status=cast(Literal["created", "paid"], record.status),
            provider_mode=cast(Literal["razorpay_test", "simulated"], record.provider_mode),
            checkout_key_id=self._key_id if record.provider_mode == "razorpay_test" else None,
            replayed=replayed,
        )
