"""Phase 1 property test: session invariants over random assessments and clocks."""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from interview.core.state import SessionState, default_stage_configs, step
from interview.core.types import Stage, TurnAssessment

_ORDER = {Stage.INTRO: 0, Stage.PAST_EXPERIENCE: 1, Stage.DONE: 2}


@settings(max_examples=500, deadline=None)
@given(data=st.data())
def test_session_invariants(data):
    configs = default_stage_configs()
    state = SessionState(stage=Stage.INTRO, stage_start_time=0.0)
    now = 0.0
    transitions = 0

    for _ in range(5000):  # generous cap; the timer guarantees we finish well before it
        if state.stage == Stage.DONE:
            break

        cfg = configs[state.stage]
        scores = {
            f: data.draw(st.floats(min_value=0.0, max_value=1.0))
            for f in cfg.required_fields
        }
        gain = data.draw(st.floats(min_value=0.0, max_value=1.0))
        suggest = data.draw(st.booleans())
        # strictly increasing clock (min step 1.0s) so the timer must eventually fire
        now += data.draw(st.floats(min_value=1.0, max_value=60.0))

        stage_before = state.stage
        step(state, cfg, TurnAssessment(scores, gain, suggest), now)

        # never moves backward
        assert _ORDER[state.stage] >= _ORDER[stage_before]
        # never exceeds the follow-up budget for the stage
        assert state.followups_used <= cfg.followup_budget

        if state.stage != stage_before:
            transitions += 1

    # the session always terminates (the timer guarantees it)
    assert state.stage == Stage.DONE
    # exactly one bridge line per transition
    assert len(state.bridge_lines) == transitions
    # two stages means exactly two transitions to reach DONE
    assert transitions == 2
