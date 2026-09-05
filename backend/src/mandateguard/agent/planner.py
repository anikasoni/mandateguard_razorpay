"""Gemini-backed product proposal with an explicit offline demo fallback."""

import json
import re
from collections.abc import Callable
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mandateguard.domain.models import Product


class AgentPlanningError(RuntimeError):
    pass


class PurchasePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: str
    quantity: int = Field(strict=True, ge=1, le=20)
    claimed_inventory_count: int | None = Field(default=None, strict=True, ge=0)
    rationale: str = Field(min_length=1, max_length=240)
    provider: Literal["gemini", "offline_demo"]


type JsonTransport = Callable[[Request, float], object]


def _default_transport(request: Request, timeout: float) -> object:
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class PurchasingPlanner:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        transport: JsonTransport = _default_transport,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._transport = transport

    def plan(self, user_request: str, products: tuple[Product, ...]) -> PurchasePlan:
        if self._api_key is None:
            return self._offline_plan(user_request, products)
        catalog = [
            {
                "product_id": item.product_id,
                "price_paise": item.unit_price_paise,
                "inventory_count": item.inventory_count,
                "merchant_id": item.merchant_id,
                "category_id": item.category_id,
            }
            for item in products
        ]
        instruction = (
            "You are a bounded purchasing planner. Select one catalog product and quantity for "
            "the user's request. You may repeat an inventory claim from the user, but never invent "
            "payment approval. Return JSON only. Catalog: "
            + json.dumps(catalog, separators=(",", ":"))
            + "\nUser request: "
            + user_request
        )
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(self._model, safe='')}:generateContent"
        )
        body = json.dumps(
            {
                "contents": [{"role": "user", "parts": [{"text": instruction}]}],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                    "responseSchema": {
                        "type": "OBJECT",
                        "properties": {
                            "product_id": {"type": "STRING"},
                            "quantity": {"type": "INTEGER"},
                            "claimed_inventory_count": {
                                "type": "INTEGER",
                                "nullable": True,
                            },
                            "rationale": {"type": "STRING"},
                        },
                        "required": ["product_id", "quantity", "rationale"],
                    },
                },
            }
        ).encode()
        request = Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "x-goog-api-key": self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            raw = self._transport(request, 12.0)
            text = self._response_text(raw)
            proposed = json.loads(text)
            plan = PurchasePlan.model_validate({**proposed, "provider": "gemini"})
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValidationError) as exc:
            raise AgentPlanningError("Gemini could not produce a valid purchase plan") from exc
        if plan.product_id not in {item.product_id for item in products}:
            raise AgentPlanningError("Gemini selected a product outside the catalog")
        return plan

    @staticmethod
    def _response_text(raw: object) -> str:
        try:
            data: Any = raw
            value = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AgentPlanningError("Gemini returned an invalid response") from exc
        if not isinstance(value, str):
            raise AgentPlanningError("Gemini returned an invalid response")
        return value

    @staticmethod
    def _offline_plan(user_request: str, products: tuple[Product, ...]) -> PurchasePlan:
        lowered = user_request.lower()
        product = next(
            (
                item
                for item in products
                if item.product_id.replace("-", " ") in lowered
                or any(word in lowered for word in item.product_id.split("-"))
            ),
            products[0],
        )
        match = re.search(r"\b(\d{1,2})\b", lowered)
        quantity = int(match.group(1)) if match else 1
        claim_match = re.search(r"(?:only|just)\s+(\d{1,2})\s+(?:left|remaining)", lowered)
        return PurchasePlan(
            product_id=product.product_id,
            quantity=min(quantity, 20),
            claimed_inventory_count=int(claim_match.group(1)) if claim_match else None,
            rationale="Deterministic offline proposal; configure Gemini for live agent planning.",
            provider="offline_demo",
        )
