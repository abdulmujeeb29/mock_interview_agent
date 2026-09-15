"""Phase 2: prove the voice layer added NO new decision logic.

- test_voice_parity: the real Astra assessor (Azure call mocked to fixed scores)
  feeds decide(...) and the result matches a direct Phase 1 decide(...) exactly.
- test_advance_tool_is_nudge: the gpt-realtime advance_stage() signal biases but does
  not force an advance (parity with Phase 1 test 10).
"""
from __future__ import annotations

import json

from interview.assess.astra import AstraAssessor
from interview.core.policy import decide
from interview.core.state import default_stage_configs
from interview.core.types import Action, Stage, TurnAssessment
from interview.voice.controller import StageController


# --- a fake openai client whose responses.create returns canned JSON ---------
class _FakeResp:
    def __init__(self, text: str) -> None:
        self.output_text = text


class _FakeResponses:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def create(self, **kwargs):
        return _FakeResp(json.dumps(self._payload))


class _FakeClient:
    def __init__(self, payload: dict) -> None:
        self.responses = _FakeResponses(payload)


def test_voice_parity():
    cfg = default_stage_configs()[Stage.INTRO]
    fields = cfg.required_fields
    # canned scores Astra "returns"
    canned = {f: 0.5 for f in fields}
    payload = {"field_scores": canned, "last_followup_gain": 0.5}

    astra = AstraAssessor(client=_FakeClient(payload), model="gpt-6-astra")
    transcript = [("candidate", "I'm Sam, an engineer with a systems background, 6 years in.")]

    astra_assessment = astra.assess(cfg, transcript)

    # The voice/assessor path must reduce to the exact same numbers the pure core
    # would produce from the same field scores.
    reference = TurnAssessment(field_scores=dict(canned), last_followup_gain=0.5)

    d_voice = decide(Stage.INTRO, cfg, astra_assessment, followups_used=0, elapsed_seconds=10.0)
    d_core = decide(Stage.INTRO, cfg, reference, followups_used=0, elapsed_seconds=10.0)

    assert astra_assessment.field_scores == canned
    assert d_voice.action == d_core.action
    assert d_voice.reason == d_core.reason
    assert d_voice.coverage_score == d_core.coverage_score
    assert d_voice.u_advance == d_core.u_advance
    assert d_voice.u_followup == d_core.u_followup


class _FixedAssessor:
    """Returns the same TurnAssessment every call (Astra stand-in)."""

    def __init__(self, scores: dict, gain: float = 0.5) -> None:
        self._scores = scores
        self._gain = gain

    def assess(self, stage_config, transcript) -> TurnAssessment:
        return TurnAssessment(field_scores=dict(self._scores), last_followup_gain=self._gain)


def test_advance_tool_is_nudge():
    cfg_map = default_stage_configs()
    fields = cfg_map[Stage.INTRO].required_fields
    low_scores = {f: 0.1 for f in fields}  # very low coverage

    clock = {"t": 0.0}  # fresh time
    spoken = []

    controller = StageController(
        assessor=_FixedAssessor(low_scores, gain=0.5),
        speak=lambda text: spoken.append(text),
        clock=lambda: clock["t"],
        configs=cfg_map,
    )

    # gpt-realtime calls advance_stage() ...
    controller.note_model_advance_signal()
    decision = controller.on_user_turn([("candidate", "hi")])

    # ... but with low coverage and fresh time the session does NOT advance.
    assert decision.action == Action.ASK_FOLLOWUP
    assert controller.state.stage == Stage.INTRO
    assert spoken == []  # no bridge line spoken
