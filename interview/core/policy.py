"""The utility-based decision policy.

ONE pure function: ``decide``. No clock reads, no I/O. ``elapsed_seconds`` and the
``TurnAssessment`` are passed in. This is the graded spine of the whole system and
is reused unchanged by the voice and avatar layers.
"""
from __future__ import annotations

from .types import Action, Decision, Reason, Stage, StageConfig, TurnAssessment


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def coverage_score(cfg: StageConfig, assessment: TurnAssessment) -> float:
    """Weighted mean of ``min(score, 1.0)`` over the stage's required fields (0..1)."""
    total_weight = 0.0
    acc = 0.0
    for name in cfg.required_fields:
        weight = cfg.field_weights.get(name, 1.0)
        score = min(assessment.field_scores.get(name, 0.0), 1.0)
        acc += weight * score
        total_weight += weight
    return acc / total_weight if total_weight else 0.0


def decide(
    stage: Stage,
    cfg: StageConfig,
    assessment: TurnAssessment,
    followups_used: int,
    elapsed_seconds: float,
) -> Decision:
    """Choose the next action by maximizing expected utility.

    Order is fixed and load-bearing:
      1. coverage_score
      2. hard overrides (timer, then budget) -> return immediately
      3. early-out on strong coverage
      4. utility comparison (the utility-based core)
    """
    w = cfg.weights
    coverage = coverage_score(cfg, assessment)

    # --- utility terms (computed always so the Decision carries the math even on override)
    time_pressure = _clamp(elapsed_seconds / cfg.time_limit_seconds, 0.0, 1.0)
    redundant = 1.0 if assessment.last_followup_gain < w.epsilon else 0.0
    expected_gain = (1.0 - coverage) * (0.0 if redundant else 1.0)

    u_advance = w.w_cov * coverage + w.w_time * time_pressure + w.w_flow
    if assessment.model_suggests_advance:
        u_advance += w.advance_bonus  # a nudge, never a command
    u_followup = (
        w.w_cov * (coverage + expected_gain)
        - w.w_time * time_pressure
        - w.w_redundant * redundant
    )

    def out(action: Action, reason: Reason) -> Decision:
        return Decision(
            action=action,
            reason=reason,
            coverage_score=coverage,
            u_advance=u_advance,
            u_followup=u_followup,
        )

    # --- 2. hard overrides, in this exact order
    if elapsed_seconds >= cfg.time_limit_seconds:
        return out(Action.ADVANCE, Reason.TIMER)
    if followups_used >= cfg.followup_budget:
        return out(Action.ADVANCE, Reason.BUDGET)

    # --- 3. early-out on strong coverage
    if coverage >= cfg.high_coverage_threshold:
        return out(Action.ADVANCE, Reason.COVERAGE)

    # --- 4. the utility-based core
    if u_followup > u_advance:
        return out(Action.ASK_FOLLOWUP, Reason.UTILITY)
    return out(Action.ADVANCE, Reason.UTILITY)
