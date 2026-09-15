"""Phase 1 test: the locked switch prevents a double prompt / double transition."""
from __future__ import annotations

from interview.core.state import SessionState
from interview.core.types import Stage


def test_lock_no_double_prompt():
    s = SessionState(stage=Stage.INTRO, stage_start_time=0.0)

    # First advance transitions and stores exactly one bridge line, and leaves the
    # switch locked (no end_turn called yet).
    first = s.begin_advance(now=10.0, bridge_line="one bridge")
    assert first == Stage.PAST_EXPERIENCE
    assert s.locked is True

    # A second advance "back to back" while still locked is ignored: no second
    # bridge line, no second transition.
    second = s.begin_advance(now=11.0, bridge_line="SHOULD NOT APPEAR")
    assert second is None

    assert s.stage == Stage.PAST_EXPERIENCE          # exactly one transition
    assert s.bridge_lines == ["one bridge"]          # exactly one bridge line
