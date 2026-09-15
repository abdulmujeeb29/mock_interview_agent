"""Phase 2 latency-safety test: the assessor runs OFF the critical path.

A deliberately slow Astra must not block the conversation loop. assess() returns
immediately with the latest cached score, and the timer can still fire while the
real score is pending.
"""
from __future__ import annotations

import time

from interview.assess.background import BackgroundAssessor
from interview.core.state import default_stage_configs
from interview.core.types import Action, Reason, Stage, TurnAssessment
from interview.voice.controller import StageController

SLOW = 2.0  # seconds the fake Astra call "takes"


class _SlowAssessor:
    def assess(self, stage_config, transcript) -> TurnAssessment:
        time.sleep(SLOW)
        return TurnAssessment(
            field_scores={f: 1.0 for f in stage_config.required_fields},
            last_followup_gain=0.9,
        )


def test_assessor_offpath():
    cfg_map = default_stage_configs()
    cfg = cfg_map[Stage.INTRO]
    bg = BackgroundAssessor(_SlowAssessor())

    # 1) A direct call returns immediately, not after SLOW seconds.
    t0 = time.monotonic()
    first = bg.assess(cfg, [("candidate", "hello")])
    elapsed = time.monotonic() - t0
    assert elapsed < 0.2, f"assess() blocked for {elapsed:.2f}s"
    assert first.field_scores == {}  # nothing back yet; cached default

    # 2) Drive a turn through the controller with the clock past the time limit.
    #    Even though Astra is still computing, the timer must fire promptly.
    clock = {"t": cfg.time_limit_seconds + 1.0}
    spoken = []
    controller = StageController(
        assessor=bg,
        speak=lambda text: spoken.append(text),
        clock=lambda: clock["t"],
        configs=cfg_map,
    )
    # controller starts its stage clock at clock() == time_limit+1, so make the stage
    # look like it started at 0 to represent real elapsed time.
    controller.state.stage_start_time = 0.0

    t1 = time.monotonic()
    decision = controller.on_user_turn([("candidate", "still talking")])
    loop_elapsed = time.monotonic() - t1

    assert loop_elapsed < 0.2, f"decision loop blocked for {loop_elapsed:.2f}s"
    assert decision.action == Action.ADVANCE
    assert decision.reason == Reason.TIMER  # timer guarded the flow while Astra pending

    # 3) Eventually the real score lands in the background cache.
    assert bg.wait_idle(timeout=SLOW + 2.0)
    assert bg.latest().field_scores  # now populated
