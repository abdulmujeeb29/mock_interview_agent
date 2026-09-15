"""Phase 1 tests: forward-only transition table and reset-on-advance."""
from __future__ import annotations

import pytest

from interview.core.state import SessionState
from interview.core.types import Stage


def test_forward_only():
    # INTRO -> PAST_EXPERIENCE -> DONE is allowed.
    s = SessionState()
    assert s.stage == Stage.INTRO
    s.transition_to(Stage.PAST_EXPERIENCE, now=1.0, bridge_line="b1")
    assert s.stage == Stage.PAST_EXPERIENCE
    s.transition_to(Stage.DONE, now=2.0, bridge_line="b2")
    assert s.stage == Stage.DONE

    # PAST_EXPERIENCE -> INTRO (backward) raises.
    back = SessionState(stage=Stage.PAST_EXPERIENCE)
    with pytest.raises(ValueError):
        back.transition_to(Stage.INTRO, now=1.0, bridge_line="x")

    # INTRO -> DONE (skip a stage) raises.
    skip = SessionState(stage=Stage.INTRO)
    with pytest.raises(ValueError):
        skip.transition_to(Stage.DONE, now=1.0, bridge_line="x")

    # Advancing off the end (DONE has no forward) raises.
    done = SessionState(stage=Stage.DONE)
    with pytest.raises(ValueError):
        done.begin_advance(now=1.0)


def test_reset_on_advance():
    s = SessionState(stage=Stage.INTRO, followups_used=2, stage_start_time=0.0)
    s.begin_advance(now=50.0, bridge_line="bridge")
    assert s.stage == Stage.PAST_EXPERIENCE
    assert s.followups_used == 0          # follow-up counter reset
    assert s.stage_start_time == 50.0     # stage clock reset to now
    assert s.bridge_lines == ["bridge"]   # exactly one bridge line stored
