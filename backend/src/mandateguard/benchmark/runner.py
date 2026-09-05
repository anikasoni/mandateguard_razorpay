"""Execute frozen scenarios and calculate honest, reproducible baseline metrics."""

from dataclasses import asdict, dataclass

from mandateguard.benchmark.gold import EVALUATED_AT, scenarios
from mandateguard.policy import PolicyEngine


@dataclass(frozen=True, slots=True)
class BenchmarkRow:
    scenario_id: str
    family: str
    description: str
    expected_outcome: str
    expected_rule_id: str
    raw_outcome: str
    prompt_only_outcome: str
    mandateguard_outcome: str
    mandateguard_rule_id: str
    passed: bool


def _rate(numerator: int, denominator: int) -> int:
    return round(100 * numerator / denominator) if denominator else 0


def run_benchmark() -> dict[str, object]:
    engine = PolicyEngine()
    rows: list[BenchmarkRow] = []
    for scenario in scenarios():
        decision = engine.evaluate(
            scenario.request,
            scenario.state,
            evaluated_at=EVALUATED_AT,
        )
        rows.append(
            BenchmarkRow(
                scenario_id=scenario.scenario_id,
                family=scenario.family,
                description=scenario.description,
                expected_outcome=scenario.expected_outcome,
                expected_rule_id=scenario.expected_rule_id,
                raw_outcome="allow",
                prompt_only_outcome=scenario.prompt_only_outcome,
                mandateguard_outcome=decision.outcome.value,
                mandateguard_rule_id=decision.rule_id.value,
                passed=(
                    decision.outcome.value == scenario.expected_outcome
                    and decision.rule_id.value == scenario.expected_rule_id
                ),
            )
        )
    unsafe = [row for row in rows if row.expected_outcome != "allow"]
    safe = [row for row in rows if row.expected_outcome == "allow"]
    systems = {
        "raw_agent": [row.raw_outcome for row in rows],
        "prompt_only_proxy": [row.prompt_only_outcome for row in rows],
        "mandateguard": [row.mandateguard_outcome for row in rows],
    }
    metrics: dict[str, dict[str, int]] = {}
    for name, outcomes in systems.items():
        caught = sum(outcomes[index] != "allow" for index, row in enumerate(rows) if row in unsafe)
        false_blocks = sum(
            outcomes[index] != "allow" for index, row in enumerate(rows) if row in safe
        )
        correct = sum(
            outcome == row.expected_outcome for outcome, row in zip(outcomes, rows, strict=True)
        )
        metrics[name] = {
            "violation_catch_rate": _rate(caught, len(unsafe)),
            "false_block_rate": _rate(false_blocks, len(safe)),
            "decision_accuracy": _rate(correct, len(rows)),
        }
    return {
        "scenario_count": len(rows),
        "gold_passed": sum(row.passed for row in rows),
        "metrics": metrics,
        "rows": [asdict(row) for row in rows],
        "baseline_note": (
            "Raw and prompt-only values are deterministic proxy baselines, "
            "not live LLM measurements."
        ),
    }
