"""Core value types for the interview decision engine.

PURE module: no I/O, no clock, no network. Everything the policy needs is passed
in as data. These types are shared unchanged by Phase 1 (tests), Phase 2 (voice)
and Phase 3 (avatar).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Stage(Enum):
    """Forward-only interview stages."""

    INTRO = "intro"
    PAST_EXPERIENCE = "past_experience"
    DONE = "done"


class Action(Enum):
    """The two candidate actions the policy chooses between each turn."""

    ASK_FOLLOWUP = "ask_followup"
    ADVANCE = "advance"


class Reason(Enum):
    """Why a decision was made. Lets tests and logs prove the switch was controlled."""

    UTILITY = "utility"    # the utility comparison picked it
    COVERAGE = "coverage"  # early-out: coverage already strong
    BUDGET = "budget"      # hard override: follow-up budget spent
    TIMER = "timer"        # hard override: stage time limit hit


@dataclass(frozen=True)
class UtilityWeights:
    """Tunable weights for the utility policy.

    ``advance_bonus`` is the small nudge added to ``u_advance`` when the voice
    model calls ``advance_stage()``. It biases, it never forces.
    """

    w_cov: float = 1.0
    w_time: float = 0.4
    w_flow: float = 0.1
    w_redundant: float = 0.6
    epsilon: float = 0.05
    advance_bonus: float = 0.15


@dataclass(frozen=True)
class StageConfig:
    """Everything the policy needs to know about one stage."""

    required_fields: list[str]
    field_weights: dict[str, float]
    coverage_threshold: float       # a field counts as covered at/above this score
    high_coverage_threshold: float  # allow early advance when overall coverage >= this
    followup_budget: int            # max follow-ups in this stage
    time_limit_seconds: float       # hard fallback timer for this stage
    weights: UtilityWeights


@dataclass
class TurnAssessment:
    """The assessor's read of the conversation so far, per turn.

    In Phase 1 this is supplied directly by tests / the mock assessor. In Phase 2
    it comes from Astra. The core cannot tell the difference.
    """

    field_scores: dict[str, float]        # 0..1 per required field
    last_followup_gain: float = 0.0       # coverage improvement vs previous turn (0..1)
    model_suggests_advance: bool = False  # Phase 2 tool signal; False in Phase 1


@dataclass
class Decision:
    """The policy's output for one turn. Carries the math so tests can assert it."""

    action: Action
    reason: Reason
    coverage_score: float
    u_advance: float
    u_followup: float
