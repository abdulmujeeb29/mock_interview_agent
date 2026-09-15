"""Small factories for deterministic policy tests."""
from __future__ import annotations

from interview.core.types import StageConfig, TurnAssessment, UtilityWeights


def make_cfg(
    fields=("a", "b"),
    high_coverage_threshold: float = 0.85,
    followup_budget: int = 2,
    time_limit_seconds: float = 100.0,
    weights: UtilityWeights = None,
    coverage_threshold: float = 0.6,
) -> StageConfig:
    fields = list(fields)
    return StageConfig(
        required_fields=fields,
        field_weights={f: 1.0 for f in fields},
        coverage_threshold=coverage_threshold,
        high_coverage_threshold=high_coverage_threshold,
        followup_budget=followup_budget,
        time_limit_seconds=time_limit_seconds,
        weights=weights or UtilityWeights(),
    )


def assessment(scores: dict, gain: float = 0.5, suggest: bool = False) -> TurnAssessment:
    return TurnAssessment(
        field_scores=dict(scores),
        last_followup_gain=gain,
        model_suggests_advance=suggest,
    )
