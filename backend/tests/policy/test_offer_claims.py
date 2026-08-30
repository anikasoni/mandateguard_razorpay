from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest

from mandateguard.domain import EvaluationState, RuleId
from mandateguard.policy import PolicyEngine


@pytest.mark.parametrize(
    "claims",
    [
        {"claimed_inventory_count": 19},
        {"claimed_unit_price_paise": 4_999},
        {"claimed_offer_expires_at": "2026-08-30T14:00:00Z"},
    ],
)
def test_structured_claim_mismatch_is_mg007(
    claims: dict[str, Any],
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    now: datetime,
) -> None:
    decision = PolicyEngine().evaluate(
        request_factory("present_offer", claims=claims), state_factory(), evaluated_at=now
    )
    assert decision.rule_id is RuleId.OFFER_CLAIMS
    assert decision.reason == "structured_offer_claim_mismatch"


def test_exact_structured_claims_pass(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    now: datetime,
) -> None:
    decision = PolicyEngine().evaluate(
        request_factory(
            "present_offer",
            claims={
                "claimed_inventory_count": 20,
                "claimed_unit_price_paise": 5_000,
                "claimed_offer_expires_at": (now + timedelta(hours=1)).isoformat(),
            },
        ),
        state_factory(),
        evaluated_at=now,
    )
    assert decision.rule_id is RuleId.CUMULATIVE_BUDGET


def test_arbitrary_offer_claim_fields_are_contract_errors(
    request_factory: Callable[..., dict[str, Any]],
    state_factory: Callable[..., EvaluationState],
    now: datetime,
) -> None:
    decision = PolicyEngine().evaluate(
        request_factory("present_offer", claims={"marketing_copy": "best deal"}),
        state_factory(),
        evaluated_at=now,
    )
    assert decision.rule_id is RuleId.REQUEST_CONTRACT
