"""Stage orchestration for the voice layer — the ONLY glue between the live
conversation and the pure core. It does NOT contain stage logic: it reuses
``interview.core.policy.decide`` and ``SessionState`` unchanged and only produces
the inputs they expect. This is the class the Phase 2 tests drive directly, with
LiveKit and Astra mocked out.

Its jobs (straight from the Phase 2 brief):
  1. On each user turn, get a TurnAssessment from the assessor (off-path in prod).
  2. Fold in the model's advance nudge and the clock.
  3. Call decide(...).
  4. Speak the follow-up (the model does that itself) OR speak the one bridge line
     and advance the stage.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from ..core.policy import decide
from ..core.state import SessionState, default_stage_configs
from ..core.types import Action, Decision, Reason, Stage, TurnAssessment


class StageController:
    def __init__(
        self,
        *,
        assessor: Any,
        speak: Callable[[str], Any],
        clock: Callable[[], float],
        configs: Optional[dict] = None,
        set_stage_context: Optional[Callable[[Stage], Any]] = None,
        on_done: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.assessor = assessor
        self.speak = speak
        self.clock = clock
        self.configs = configs or default_stage_configs()
        self.set_stage_context = set_stage_context or (lambda stage: None)
        self.on_done = on_done or (lambda: None)
        self.state = SessionState(stage=Stage.INTRO, stage_start_time=clock())
        self._nudge = False

    def note_model_advance_signal(self) -> None:
        """The gpt-realtime ``advance_stage`` tool call lands here. It only biases the
        next decision; it never advances on its own."""
        self._nudge = True

    def decide_with(
        self,
        assessment: TurnAssessment,
        now: float,
        count_followup: bool = True,
        advance_reasons=None,
    ):
        """Run the policy from an ALREADY-FETCHED assessment and apply the decision.

        ``count_followup=True`` (a real candidate answer) increments the follow-up
        counter on ASK and consumes the model's advance nudge. ``count_followup=False``
        (a silence/timer tick) never touches the budget or the nudge.

        ``advance_reasons`` restricts which ADVANCE decisions are actually committed. The
        timer tick passes ``{Reason.TIMER}`` so a background tick can ONLY ever fire the
        hard time-limit door — never a utility/coverage/budget advance between turns
        (those must happen on a real answer, or the agent could cut the candidate off
        mid-thought). ``None`` (the answer path) commits any advance.
        """
        if self.state.stage == Stage.DONE:
            return None

        cfg = self.configs[self.state.stage]
        turn = TurnAssessment(
            field_scores=dict(assessment.field_scores),
            last_followup_gain=assessment.last_followup_gain,
            model_suggests_advance=self._nudge,
        )
        elapsed = now - self.state.stage_start_time
        decision = decide(self.state.stage, cfg, turn, self.state.followups_used, elapsed)
        self.state.last_decision = decision
        if count_followup:
            self._nudge = False  # consumed on a real turn, never sticky

        commit_advance = decision.action == Action.ADVANCE and (
            advance_reasons is None or decision.reason in advance_reasons
        )
        if commit_advance:
            self.state.begin_advance(now)          # locked switch: exactly one bridge line
            self.state.end_turn()
            self.speak(self.state.bridge_lines[-1])
            if self.state.stage == Stage.DONE:
                self.on_done()
            else:
                self.set_stage_context(self.state.stage)
        elif count_followup and decision.action == Action.ASK_FOLLOWUP:
            # ASK_FOLLOWUP: the realtime model generates the actual follow-up itself.
            self.state.followups_used += 1

        return decision

    def on_user_turn(self, transcript: list):
        # Convenience path (used by tests): fetch the latest assessment, then decide.
        if self.state.stage == Stage.DONE:
            return None
        latest = self.assessor.assess(self.configs[self.state.stage], transcript)
        return self.decide_with(latest, self.clock(), count_followup=True)
