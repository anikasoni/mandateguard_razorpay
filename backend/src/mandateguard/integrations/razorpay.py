"""Minimal Razorpay test-mode Orders client using the standard library."""

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class RazorpayUnavailableError(RuntimeError):
    """Raised when Razorpay cannot return a valid test order."""


@dataclass(frozen=True, slots=True)
class RazorpayOrder:
    order_id: str
    amount_paise: int
    currency: str
    status: str


type JsonTransport = Callable[[Request, float], object]


def _default_transport(request: Request, timeout: float) -> object:
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class RazorpayOrdersClient:
    """Create one order against Razorpay's fixed HTTPS test/live API endpoint."""

    _URL = "https://api.razorpay.com/v1/orders"

    def __init__(
        self,
        key_id: str,
        key_secret: str,
        *,
        timeout_seconds: float = 10.0,
        transport: JsonTransport = _default_transport,
    ) -> None:
        self._authorization = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
        self._timeout = timeout_seconds
        self._transport = transport

    def create_order(
        self,
        *,
        amount_paise: int,
        currency: str,
        receipt: str,
        attempt_id: str,
    ) -> RazorpayOrder:
        payload = json.dumps(
            {
                "amount": amount_paise,
                "currency": currency,
                "receipt": receipt,
                "notes": {"mandateguard_attempt_id": attempt_id},
            },
            separators=(",", ":"),
        ).encode()
        request = Request(
            self._URL,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Basic {self._authorization}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            raw = self._transport(request, self._timeout)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RazorpayUnavailableError("Razorpay order creation failed") from exc
        if not isinstance(raw, dict):
            raise RazorpayUnavailableError("Razorpay returned an invalid order")
        data: dict[str, Any] = raw
        order_id = data.get("id")
        amount = data.get("amount")
        returned_currency = data.get("currency")
        status = data.get("status")
        if (
            not isinstance(order_id, str)
            or not order_id.startswith("order_")
            or type(amount) is not int
            or amount != amount_paise
            or returned_currency != currency
            or status != "created"
        ):
            raise RazorpayUnavailableError("Razorpay returned an invalid order")
        return RazorpayOrder(order_id, amount, returned_currency, status)
