"""Phase 2: a full two-stage interview through the controller (LiveKit/Astra mocked),
and the decision-loop latency measurement.

- test_transitions_fire_live: drive INTRO -> PAST_EXPERIENCE -> DONE with a scripted
  assessor and assert exactly one bridge line per transition.
- test_latency: measure the orchestration overhead we add per turn and print it. The
  full end-of-speech -> agent-reply number is model-dependent and is captured live by
  the agent's LATENCY log line during the browser demo; this test proves our layer
  contributes negligible latency.
"""
from __future__ import annotations

import time

from interview.core.state import default_stage_configs
from interview.core.types import Action, Reason, Stage, TurnAssessment
from interview.voice.controller import StageController


class _ScriptedAssessor:
    """Returns assessments from a queue, one per turn (last value repeats)."""

    def __init__(self, script) -> None:
        self._script = list(script)
        self._i = 0

    def assess(self, stage_config, transcript) -> TurnAssessment:
        item = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        scores = {f: item["cov"] for f in stage_config.required_fields}
        return TurnAssessment(field_scores=scores, last_followup_gain=item.get("gain", 0.5))


def test_transitions_fire_live():
    cfg_map = default_stage_configs()
    spoken = []
    stage_context_calls = []
    clock = {"t": 0.0}

    # turn 1: INTRO low -> ask; turn 2: INTRO high -> ADVANCE(coverage);
    # turn 3: PAST high -> ADVANCE(coverage) -> DONE
    assessor = _ScriptedAssessor([
        {"cov": 0.3, "gain": 0.5},
        {"cov": 0.95, "gain": 0.5},
        {"cov": 0.95, "gain": 0.5},
    ])

    controller = StageController(
        assessor=assessor,
        speak=lambda t: spoken.append(t),
        clock=lambda: clock["t"],
        configs=cfg_map,
        set_stage_context=lambda stage: stage_context_calls.append(stage),
    )

    seen = []
    for _ in range(6):
        if controller.state.stage == Stage.DONE:
            break
        clock["t"] += 5.0
        d = controller.on_user_turn([("candidate", "answer")])
        seen.append((controller.state.stage, d.action, d.reason))

    assert controller.state.stage == Stage.DONE
    # exactly one bridge line per transition, two transitions total
    assert len(controller.state.bridge_lines) == 2
    assert len(spoken) == 2
    assert spoken == controller.state.bridge_lines
    # moving INTO past_experience triggered exactly one stage-context switch
    assert stage_context_calls == [Stage.PAST_EXPERIENCE]


def test_first_turn_does_not_insta_advance():
    # Regression: before Astra returns, the assessor's cached score has coverage 0.
    # If its last_followup_gain were 0 it would look "redundant" and the policy would
    # advance on turn 1. The BackgroundAssessor seeds gain=1.0 so the first turn ASKS.
    from interview.assess.background import BackgroundAssessor
    from interview.core.types import Action

    class _NeverReturns:
        def assess(self, stage_config, transcript):
            import time as _t
            _t.sleep(60)  # never lands during the test

    cfg_map = default_stage_configs()
    clock = {"t": 0.0}
    controller = StageController(
        assessor=BackgroundAssessor(_NeverReturns()),
        speak=lambda t: None,
        clock=lambda: clock["t"],
        configs=cfg_map,
    )
    clock["t"] += 3.0
    decision = controller.on_user_turn([("candidate", "Hi there")])
    assert decision.action == Action.ASK_FOLLOWUP
    assert controller.state.stage == Stage.INTRO


def test_tick_does_not_spend_budget():
    # A timer/silence tick (count_followup=False) must never increment the follow-up
    # budget or advance on ASK — only real answers do. And it still fires the TIMER door.
    from interview.core.types import Action, Reason, TurnAssessment

    cfg_map = default_stage_configs()
    clock = {"t": 0.0}
    controller = StageController(
        assessor=_ScriptedAssessor([{"cov": 0.1, "gain": 0.5}]),
        speak=lambda t: None,
        clock=lambda: clock["t"],
        configs=cfg_map,
    )
    low = TurnAssessment(field_scores={f: 0.1 for f in cfg_map[Stage.INTRO].required_fields},
                         last_followup_gain=0.5)

    # ticks while there is time left: ASK, but budget untouched
    for _ in range(5):
        clock["t"] += 1.0
        d = controller.decide_with(low, clock["t"], count_followup=False)
        assert d.action == Action.ASK_FOLLOWUP
    assert controller.state.followups_used == 0  # ticks never spend budget

    # a tick past the time limit fires TIMER
    clock["t"] = cfg_map[Stage.INTRO].time_limit_seconds + 1
    d = controller.decide_with(low, clock["t"], count_followup=False)
    assert d.action == Action.ADVANCE
    assert d.reason == Reason.TIMER


def test_tick_only_commits_timer_advance():
    # A background tick must NOT end a stage on a utility/coverage/budget advance
    # (that would cut the candidate off between turns). Only the hard TIMER door.
    from interview.core.types import Action, Reason, TurnAssessment

    cfg_map = default_stage_configs()
    clock = {"t": 0.0}
    controller = StageController(
        assessor=None,
        speak=lambda t: None,
        clock=lambda: clock["t"],
        configs=cfg_map,
    )
    # moderate coverage + high time pressure => the policy WOULD choose ADVANCE/UTILITY
    mod = TurnAssessment(
        field_scores={f: 0.35 for f in cfg_map[Stage.INTRO].required_fields},
        last_followup_gain=0.5,
    )
    clock["t"] = 80.0  # well under the 90s limit, but enough time pressure for a util tie
    d = controller.decide_with(mod, 80.0, count_followup=False, advance_reasons={Reason.TIMER})
    assert d.action == Action.ADVANCE and d.reason == Reason.UTILITY  # policy wanted it
    assert controller.state.stage == Stage.INTRO  # but the tick did NOT commit it

    # once past the hard limit, the tick DOES commit the TIMER advance
    clock["t"] = cfg_map[Stage.INTRO].time_limit_seconds + 1
    d = controller.decide_with(mod, clock["t"], count_followup=False, advance_reasons={Reason.TIMER})
    assert d.action == Action.ADVANCE and d.reason == Reason.TIMER
    assert controller.state.stage == Stage.PAST_EXPERIENCE


def test_latency():
    cfg_map = default_stage_configs()
    clock = {"t": 0.0}
    assessor = _ScriptedAssessor([{"cov": 0.2, "gain": 0.5}])
    controller = StageController(
        assessor=assessor,
        speak=lambda t: None,
        clock=lambda: clock["t"],
        configs=cfg_map,
    )

    samples = []
    for _ in range(5):
        clock["t"] += 1.0
        t0 = time.perf_counter()
        controller.on_user_turn([("candidate", "some answer")])
        samples.append(time.perf_counter() - t0)

    worst = max(samples)
    avg = sum(samples) / len(samples)
    print(f"\n[latency] decision-loop overhead: avg={avg*1000:.3f}ms worst={worst*1000:.3f}ms")

    # Our added orchestration must be well under a millisecond-scale budget; the
    # threshold here is generous (50ms) and only guards against accidental blocking.
    assert worst < 0.05, f"decision loop too slow: {worst*1000:.1f}ms"
