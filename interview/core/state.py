"""Session state, the forward-only transition table, and the locked switch.

PURE: ``now`` is always passed in, never read from a clock. The lock is what
prevents the double-prompt the brief warns about: while a switch is in progress
no new prompt or follow-up may be produced, and a re-entrant advance is ignored.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .policy import decide
from .types import (
    Action,
    Decision,
    Stage,
    StageConfig,
    TurnAssessment,
    UtilityWeights,
)

# Forward-only transition table. Anything not here is illegal.
_FORWARD: dict[Stage, Stage] = {
    Stage.INTRO: Stage.PAST_EXPERIENCE,
    Stage.PAST_EXPERIENCE: Stage.DONE,
}

# One short handoff sentence per departing stage. Stored, never regenerated twice.
BRIDGE_LINES: dict[Stage, str] = {
    Stage.INTRO: "Thanks. Now let's talk about your past experience.",
    Stage.PAST_EXPERIENCE: "Great, that covers what I wanted to ask. Thanks for your time.",
}


def default_stage_configs() -> dict[Stage, StageConfig]:
    """The starting values from the Phase 1 spec (tune later)."""
    intro_fields = ["name", "current_role", "background", "years_experience"]
    past_fields = ["project", "your_role", "impact", "depth_probed"]
    return {
        # Follow-up budgets tuned up from the brief's starting 2/3 after live testing:
        # each stage has 4 required fields, so a natural interview needs ~one exchange
        # per field to reach a COVERAGE finish before the BUDGET cap.
        Stage.INTRO: StageConfig(
            required_fields=intro_fields,
            field_weights={f: 1.0 for f in intro_fields},
            coverage_threshold=0.6,
            high_coverage_threshold=0.85,
            followup_budget=4,
            time_limit_seconds=90.0,
            weights=UtilityWeights(),
        ),
        Stage.PAST_EXPERIENCE: StageConfig(
            required_fields=past_fields,
            field_weights={f: 1.0 for f in past_fields},
            coverage_threshold=0.6,
            high_coverage_threshold=0.80,
            followup_budget=5,
            time_limit_seconds=150.0,
            weights=UtilityWeights(),
        ),
    }


@dataclass
class SessionState:
    """Mutable per-session state. All time enters via ``now`` arguments."""

    stage: Stage = Stage.INTRO
    followups_used: int = 0
    stage_start_time: float = 0.0
    locked: bool = False
    bridge_lines: list[str] = field(default_factory=list)
    last_decision: Optional[Decision] = None

    # --- transitions -----------------------------------------------------

    def _forward_target(self) -> Optional[Stage]:
        return _FORWARD.get(self.stage)

    def _do_advance(self, now: float, bridge_line: str) -> Stage:
        target = self._forward_target()
        if target is None:
            raise ValueError(f"no forward transition from {self.stage}")
        # The locked switch: exactly one bridge line, reset counters/clock.
        self.locked = True
        self.bridge_lines.append(bridge_line)
        self.stage = target
        self.followups_used = 0
        self.stage_start_time = now
        return target

    def transition_to(self, target: Stage, now: float, bridge_line: str) -> Stage:
        """Explicit checked transition. Raises ``ValueError`` on any non-forward move."""
        if self._forward_target() != target:
            raise ValueError(f"illegal transition {self.stage} -> {target}")
        return self._do_advance(now, bridge_line)

    def begin_advance(self, now: float, bridge_line: Optional[str] = None) -> Optional[Stage]:
        """Advance one stage forward. Re-entrant calls while locked are ignored.

        Returns the new stage, or ``None`` if the call was a no-op because a switch
        is already in progress (this is what makes double-advance emit one bridge
        line and one transition).
        """
        if self.locked:
            return None
        if bridge_line is None:
            bridge_line = BRIDGE_LINES.get(self.stage, "")
        return self._do_advance(now, bridge_line)

    def end_turn(self) -> None:
        """Release the lock so the next real turn may produce a prompt."""
        self.locked = False


def step(
    state: SessionState,
    cfg: StageConfig,
    assessment: TurnAssessment,
    now: float,
) -> Decision:
    """Run one turn: decide, then apply the decision to ``state``.

    Pure w.r.t. time (``now`` is passed in). Reused by the CLI and the property
    test so the exact same orchestration is exercised everywhere.
    """
    elapsed = now - state.stage_start_time
    decision = decide(state.stage, cfg, assessment, state.followups_used, elapsed)
    state.last_decision = decision

    if decision.action == Action.ADVANCE:
        state.begin_advance(now)
        state.end_turn()
    else:
        state.followups_used += 1

    return decision
