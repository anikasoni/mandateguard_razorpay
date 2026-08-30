from types import MappingProxyType

from mandateguard.domain.enums import RuleId, ToolName
from mandateguard.policy.rules import ORDERED_RULES

RULE_REGISTRY = ORDERED_RULES

_APPLICABLE = {
    ToolName.GET_PRODUCT: frozenset(
        {
            RuleId.REQUEST_CONTRACT,
            RuleId.MANDATE_STATUS,
            RuleId.CURRENCY,
            RuleId.CATALOG,
            RuleId.SCOPE,
        }
    ),
    ToolName.PRESENT_OFFER: frozenset(
        {
            RuleId.REQUEST_CONTRACT,
            RuleId.MANDATE_STATUS,
            RuleId.CURRENCY,
            RuleId.CATALOG,
            RuleId.SCOPE,
            RuleId.OFFER_CLAIMS,
            RuleId.PER_ITEM_CAP,
            RuleId.CUMULATIVE_BUDGET,
        }
    ),
    ToolName.REQUEST_APPROVAL: frozenset(
        {
            RuleId.REQUEST_CONTRACT,
            RuleId.INTENT_IDEMPOTENCY,
            RuleId.MANDATE_STATUS,
            RuleId.CURRENCY,
            RuleId.CATALOG,
            RuleId.SCOPE,
            RuleId.PER_ITEM_CAP,
            RuleId.CUMULATIVE_BUDGET,
            RuleId.APPROVAL,
            RuleId.AUTHORIZATION,
        }
    ),
    ToolName.CREATE_CHECKOUT: frozenset(
        {
            RuleId.REQUEST_CONTRACT,
            RuleId.INTENT_IDEMPOTENCY,
            RuleId.MANDATE_STATUS,
            RuleId.CURRENCY,
            RuleId.CATALOG,
            RuleId.SCOPE,
            RuleId.PER_ITEM_CAP,
            RuleId.CUMULATIVE_BUDGET,
            RuleId.APPROVAL,
            RuleId.AUTHORIZATION,
        }
    ),
}

APPLICABLE_RULES = MappingProxyType(_APPLICABLE)

if tuple(rule.rule_id for rule in RULE_REGISTRY) != tuple(RuleId):
    raise RuntimeError("rule registry must contain MG-001 through MG-011 in order")
