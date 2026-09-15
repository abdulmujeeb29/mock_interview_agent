"""LiveKit wiring: gpt-realtime-2 (Azure) as the voice-and-brain, the pure core as
the decision maker, Astra (off-path) as the assessor.

This is the thin, hard-to-unit-test glue. All decision logic lives in
``StageController`` + the pure core; this file only connects LiveKit events to it.

Turn control is deliberate: the server detects end-of-turn (VAD) but does NOT auto-
create responses (``create_response=False``). The agent creates every reply itself,
so the stage switch is fully controlled — no race where the model starts a follow-up
just as the policy decides to advance.

Run a worker:   python -m interview.voice.agent dev
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from openai.types.realtime.audio_transcription import AudioTranscription
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.agents import room_io
from livekit.plugins import openai as lk_openai
from openai.types.realtime.realtime_audio_input_turn_detection import ServerVad

from ..avatar.tavus_avatar import start_avatar_if_enabled
from ..assess.astra import AstraAssessor
from ..assess.background import BackgroundAssessor
from ..core.policy import coverage_score
from ..core.state import default_stage_configs
from ..core.types import Action, Reason, Stage, TurnAssessment
from .controller import StageController


class FreshUntilCovered:
    """Voice-layer input cleaning wrapped around the assessor.

    Real-world STT hallucinates stock phrases on silence ("Thanks for watching",
    "Bye"), and Astra scores a beat late — so early turns often show coverage ~0 with
    gain ~0. The pure policy reads gain < epsilon as "dead topic, advance", which is
    wrong when NOTHING is covered yet. While coverage is below a small floor we report
    gain=1.0 (not redundant), so the policy keeps asking instead of advancing on noise.
    Once real coverage exists, the genuine redundancy signal passes through untouched.
    """

    def __init__(self, inner, floor: float = 0.2) -> None:
        self._inner = inner
        self._floor = floor

    def _clean(self, stage_config, a: TurnAssessment) -> TurnAssessment:
        if coverage_score(stage_config, a) < self._floor:
            return TurnAssessment(
                field_scores=dict(a.field_scores),
                last_followup_gain=1.0,
                model_suggests_advance=a.model_suggests_advance,
            )
        return a

    def assess(self, stage_config, transcript) -> TurnAssessment:
        return self._clean(stage_config, self._inner.assess(stage_config, transcript))

    def snapshot(self, stage_config) -> TurnAssessment:
        """Latest cleaned assessment WITHOUT triggering a network call."""
        return self._clean(stage_config, self._inner.latest())

    def refresh(self, stage_config, transcript) -> None:
        self._inner.refresh(stage_config, transcript)

    def version(self) -> int:
        return self._inner.version()

    def reset(self) -> None:
        r = getattr(self._inner, "reset", None)
        if callable(r):
            r()

    def latest(self):
        return self._inner.latest()

# Robust .env load: absolute path from this file so the spawned job SUBPROCESS
# (which re-imports this module, sometimes with a different cwd) always finds it.
# override=True so .env WINS over any stale key exported in the launching shell
# (a stale shell AZURE_OPENAI_API_KEY was the cause of the realtime 401s).
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH, override=True)

logger = logging.getLogger("interview.voice")

STAGE_GUIDE = {
    Stage.INTRO: (
        "Always speak in English. "
        "You are a warm, concise mock-interview interviewer in the INTRODUCTION stage. "
        "Get the candidate to introduce themselves. You want to learn: their name, their "
        "current role, their background, and their years of experience. Ask ONE short "
        "question at a time and listen. When you believe those are covered, call the "
        "advance_stage tool. Never announce stage changes yourself; the system handles that."
    ),
    Stage.PAST_EXPERIENCE: (
        "Always speak in English. "
        "You are now in the PAST EXPERIENCE stage. Ask about one specific past project: "
        "what it was, the candidate's own role on it, its impact, and probe one level deeper "
        "on a key decision or trade-off. ONE short question at a time. Call advance_stage when "
        "you believe these are covered. Never announce stage changes yourself."
    ),
}

GREETING = (
    "Speak only in English. Greet the candidate warmly in one sentence and ask them to "
    "introduce themselves."
)


def _realtime_azure_endpoint() -> str:
    """Return the base ``wss://<host>/`` the plugin expects, from AZURE_REALTIME_ENDPOINT."""
    raw = os.environ.get("AZURE_REALTIME_ENDPOINT", "")
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        scheme = "wss" if parsed.scheme in ("ws", "wss") else "https"
        return f"{scheme}://{parsed.netloc}/"
    return os.environ.get("AZURE_OPENAI_ENDPOINT", "")


def build_realtime_model():
    """Construct the Azure gpt-realtime model. We use the plugin's DEFAULT turn
    detection: the model converses naturally (server-VAD, auto-response) and LiveKit's
    own adaptive detector handles barge-in. The controller then only interrupts to
    switch stages. Low temperature keeps the voice snappy; the heavy judging is Astra's
    job, off the critical path."""
    _key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    _fp = f"{_key[:6]}...{_key[-4:]}" if _key else "MISSING"
    logger.info(
        "realtime cfg: endpoint=%s deployment=%s key=%s (len=%d)",
        _realtime_azure_endpoint(),
        os.environ.get("AZURE_REALTIME_DEPLOYMENT", "MISSING"),
        _fp,
        len(_key),
    )
    return lk_openai.realtime.RealtimeModel.with_azure(
        azure_deployment=os.environ["AZURE_REALTIME_DEPLOYMENT"],
        azure_endpoint=_realtime_azure_endpoint(),
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        voice="marin",
        temperature=0.6,
        # Pin transcription to English so the STT side-channel that feeds Astra does
        # not hallucinate other languages on noise/silence.
        input_audio_transcription=AudioTranscription(model="whisper-1", language="en"),
        # A 1.6s silence window so a candidate can pause to think mid-answer without the
        # turn ending (each committed turn is a follow-up against the budget).
        # create_response=True keeps the natural auto-reply; interrupt_response enables
        # barge-in.
        turn_detection=ServerVad(
            type="server_vad",
            threshold=0.5,
            prefix_padding_ms=300,
            silence_duration_ms=1600,
            create_response=True,
            interrupt_response=True,
        ),
    )


def _configs_with_env_overrides() -> dict:
    """Stage configs with optional time-limit overrides from the environment.

    The pure core stays pure (it never reads env); overrides are applied HERE, in the
    voice layer. Set INTRO_TIME_LIMIT / PAST_TIME_LIMIT (seconds) to, say, 20 to make
    the TIMER door easy to show on camera; leave unset for the real 90/150 defaults.
    """
    configs = default_stage_configs()

    def override(stage: Stage, env_key: str):
        raw = os.environ.get(env_key)
        if raw:
            try:
                return replace(configs[stage], time_limit_seconds=float(raw))
            except ValueError:
                logger.warning("ignoring bad %s=%r", env_key, raw)
        return configs[stage]

    configs[Stage.INTRO] = override(Stage.INTRO, "INTRO_TIME_LIMIT")
    configs[Stage.PAST_EXPERIENCE] = override(Stage.PAST_EXPERIENCE, "PAST_TIME_LIMIT")
    return configs


def _text_of(item) -> str:
    text = getattr(item, "text_content", None)
    if isinstance(text, str) and text:
        return text
    content = getattr(item, "content", None)
    if isinstance(content, list):
        return " ".join(c for c in content if isinstance(c, str)).strip()
    if isinstance(content, str):
        return content
    return ""


class InterviewAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=STAGE_GUIDE[Stage.INTRO])
        self.controller: StageController | None = None

    @function_tool
    async def advance_stage(self, context: RunContext) -> str:
        """Signal that you believe the CURRENT interview stage is now sufficiently
        covered and it may be time to move on. This is only a suggestion — the interview
        controller weighs it against coverage and the timer and decides."""
        if self.controller is not None:
            self.controller.note_model_advance_signal()
        return "acknowledged"


async def entrypoint(ctx: JobContext) -> None:
    load_dotenv(_ENV_PATH, override=True)  # belt-and-braces inside the job subprocess

    session = AgentSession(llm=build_realtime_model())
    agent = InterviewAgent()

    assessor = FreshUntilCovered(BackgroundAssessor(AstraAssessor()))
    transcript: list = []
    pending_bridge: dict = {"text": None}
    pending_user_ts: dict = {"t": None}  # end-of-user-speech -> first-audio latency
    # A stage switch is DEFERRED (never interrupts a streaming realtime response). It is
    # spoken only AFTER the candidate has answered the question already on the table, so
    # the agent never cuts them off mid-thought. "answered" flips true once the candidate
    # speaks after the switch was queued; "immediate" (a TIMER/silence advance) bridges
    # right away since there is no answer to wait for.
    pending_switch: dict = {
        "active": False, "answered": False, "immediate": False,
        "stage": None, "finish": False, "bridge": "", "reason": "",
    }

    async def _publish_stage(
        stage_value: str, reason_value: str = "", limit_seconds: float = 0.0
    ) -> None:
        """Publish the current stage + why we moved as room attributes, so the frontend
        can show a big, obvious stage indicator without anyone reading the logs.
        `iv_limit` is this stage's hard time-limit and `iv_started` is the wall-clock
        moment it began (epoch ms) so the UI can run a live countdown toward the TIMER
        fallback."""
        try:
            await ctx.room.local_participant.set_attributes(
                {
                    "iv_stage": stage_value,
                    "iv_reason": reason_value,
                    "iv_limit": str(int(limit_seconds)),
                    "iv_started": str(int(time.time() * 1000)),
                }
            )
        except Exception:  # noqa: BLE001 - UI signal must never affect the interview
            pass

    def _limit_for(stage) -> float:
        cfg = controller.configs.get(stage) if hasattr(controller, "configs") else None
        return float(getattr(cfg, "time_limit_seconds", 0.0)) if cfg else 0.0

    # Steering: the instant we decide to wrap, tell the model to stop asking new questions
    # so its reply to the candidate's in-progress answer isn't another dangling question.
    WRAPUP_INSTRUCTION = (
        "You are about to move on from this part of the interview. Do NOT ask any new "
        "questions now. If the candidate is still answering, let them finish and "
        "acknowledge in at most one short sentence."
    )

    async def _steer_wrapup() -> None:
        try:
            await agent.update_instructions(WRAPUP_INSTRUCTION)
        except Exception:  # noqa: BLE001
            pass

    async def _run_switch(stage, finish: bool, bridge: str, reason: str = "") -> None:
        # Now actually transition: fresh transcript + assessor for the new stage, then
        # speak the bridge / closing. Publish the new stage NOW so the on-screen
        # indicator flips in sync with the spoken bridge line.
        transcript.clear()
        assessor.reset()
        await _publish_stage(
            "done" if finish else stage.value,
            reason,
            0.0 if finish else _limit_for(stage),
        )
        if finish:
            try:
                await agent.update_instructions(
                    "The interview is over. If the candidate speaks again, politely say "
                    "in one short sentence that the interview has concluded."
                )
            except Exception:  # noqa: BLE001
                pass
            handle = session.generate_reply(
                instructions=f'Say this closing line to the candidate, verbatim, and nothing else: "{bridge}".'
            )
            try:
                await handle.wait_for_playout()
            except Exception:  # noqa: BLE001
                pass
            try:
                await session.aclose()
            except Exception:  # noqa: BLE001
                pass
        else:
            try:
                await agent.update_instructions(STAGE_GUIDE[stage])
            except Exception:  # noqa: BLE001
                pass
            session.generate_reply(
                instructions=(
                    f'First say this transition line to the candidate, verbatim: "{bridge}". '
                    f"Then immediately ask your first question for this stage in one short sentence."
                )
            )

    def _fire_switch_if_pending(force: bool = False) -> None:
        if not pending_switch["active"]:
            return
        # Wait for the candidate to answer the question on the table, unless this is an
        # immediate (silence/timer) switch or a forced fallback.
        if not force and not pending_switch["immediate"] and not pending_switch["answered"]:
            return
        pending_switch["active"] = False
        asyncio.create_task(
            _run_switch(
                pending_switch["stage"],
                pending_switch["finish"],
                pending_switch["bridge"],
                pending_switch["reason"],
            )
        )

    async def _switch_fallback() -> None:
        # Safety net: if the candidate never answers (abandons the turn), wrap anyway so
        # the interview cannot stall waiting to bridge.
        await asyncio.sleep(15.0)
        _fire_switch_if_pending(force=True)

    def _queue_switch(stage, finish: bool) -> None:
        last = controller.state.last_decision
        immediate = bool(last is not None and last.reason == Reason.TIMER)
        reason = last.reason.value if last is not None else ""
        pending_switch.update(
            active=True, answered=False, immediate=immediate,
            stage=stage, finish=finish, bridge=(pending_bridge["text"] or ""), reason=reason,
        )
        pending_bridge["text"] = None
        # Stop the model asking new questions while we wait for the candidate to finish.
        asyncio.create_task(_steer_wrapup())
        if immediate:
            _fire_switch_if_pending(force=True)  # silence/timer: nothing to wait for
        else:
            asyncio.create_task(_switch_fallback())

    def speak(text: str) -> None:
        pending_bridge["text"] = text  # captured by the queued switch below

    def set_stage_context(stage: Stage) -> None:
        _queue_switch(stage, finish=False)

    def on_done() -> None:
        _queue_switch(None, finish=True)

    controller = StageController(
        assessor=assessor,
        speak=speak,
        clock=time.monotonic,
        configs=_configs_with_env_overrides(),
        set_stage_context=set_stage_context,
        on_done=on_done,
    )
    agent.controller = controller

    def _log_decision(d) -> None:
        logger.info(
            "DECISION action=%s reason=%s coverage=%.2f u_advance=%.3f u_followup=%.3f "
            "stage=%s followups_used=%d",
            d.action.name, d.reason.name, d.coverage_score, d.u_advance, d.u_followup,
            controller.state.stage.name, controller.state.followups_used,
        )

    decide_state = {"busy": False, "pending": False}

    async def _run_decision() -> None:
        # Single-flight: one decision at a time. If new answers arrive mid-decision,
        # we loop and re-decide on the LATEST transcript instead of stacking a decision
        # (and a follow-up count) per fragment.
        decide_state["busy"] = True
        try:
            while True:
                stage = controller.state.stage
                if stage == Stage.DONE:
                    break
                cfg = controller.configs[stage]
                snapshot = list(transcript)
                start_version = assessor.version()
                assessor.refresh(cfg, snapshot)
                # Wait until Astra has actually scored THIS answer (it is slow, ~5s), so
                # the decision uses fresh coverage instead of a stale, lagging score.
                deadline = time.monotonic() + 6.0
                while time.monotonic() < deadline and assessor.version() == start_version:
                    await asyncio.sleep(0.1)
                d = controller.decide_with(assessor.snapshot(cfg), time.monotonic(), count_followup=True)
                if d is not None:
                    _log_decision(d)
                if decide_state["pending"]:
                    decide_state["pending"] = False
                    continue  # a newer answer came in while we were deciding
                break
        finally:
            decide_state["busy"] = False

    async def _timer_loop() -> None:
        # Safety net for the HARD time limit only. It must never end a stage on a
        # utility/coverage/budget call between turns — that would cut the candidate off
        # mid-thought. Those advances happen on real answers (see _run_decision).
        while True:
            await asyncio.sleep(1.0)
            stage = controller.state.stage
            if stage == Stage.DONE:
                return
            if pending_switch["active"]:
                continue
            d = controller.decide_with(
                assessor.snapshot(controller.configs[stage]),
                time.monotonic(),
                count_followup=False,
                advance_reasons={Reason.TIMER},
            )
            if d is not None and d.action == Action.ADVANCE and d.reason == Reason.TIMER:
                _log_decision(d)

    @session.on("user_input_transcribed")
    def _on_user(ev) -> None:
        if not getattr(ev, "is_final", False):
            return
        text = (getattr(ev, "transcript", "") or "").strip()
        # Ignore empty / word-less finals: STT hallucinates stock phrases and rows of
        # punctuation ("____", ".") on silence; those must not consume a follow-up.
        if len(re.sub(r"[^A-Za-z0-9]", "", text)) < 2:
            return
        transcript.append(("candidate", text))
        pending_user_ts["t"] = time.monotonic()
        # If a stage switch is queued, this answer IS the response to the question on the
        # table. Record it (so the switch can now fire) and don't start a new decision.
        if pending_switch["active"]:
            pending_switch["answered"] = True
            return
        if controller.state.stage != Stage.DONE:
            if decide_state["busy"]:
                decide_state["pending"] = True  # fold into the in-flight decision
            else:
                asyncio.create_task(_run_decision())
        # ASK_FOLLOWUP: LiveKit drives the natural follow-up reply.
        # ADVANCE: the queued switch is spoken once the candidate answers the pending
        # question and the agent stops talking (see agent_state_changed).

    @session.on("agent_state_changed")
    def _on_agent_state(ev) -> None:
        new_state = str(getattr(ev, "new_state", ""))
        # First moment the agent actually starts speaking = the latency we care about.
        if new_state.endswith("speaking") and pending_user_ts["t"] is not None:
            dt = time.monotonic() - pending_user_ts["t"]
            pending_user_ts["t"] = None
            # Only record plausible turn latencies; long multi-part answers make the
            # "end of user speech" mark stale and produce meaningless large values.
            if 0.0 < dt < 8.0:
                logger.info("LATENCY end_of_user_speech->agent_speaking=%.3fs", dt)
        # The agent has stopped talking -> safe to speak a queued stage switch now
        # (no streaming response to corrupt).
        if new_state.endswith("listening") or new_state.endswith("idle"):
            _fire_switch_if_pending()

    @session.on("conversation_item_added")
    def _on_item(ev) -> None:
        item = ev.item
        if getattr(item, "role", None) == "assistant":
            text = _text_of(item)
            if text:
                transcript.append(("interviewer", text))

    await ctx.connect()
    # Phase 3: put a face on it if enabled. If Tavus fails, this returns False and we
    # run exactly as Phase 2 (audio-only) — the avatar can never break the interview.
    avatar_on = await start_avatar_if_enabled(session, ctx.room)
    # When the avatar is on, it publishes the synced audio+video; otherwise the session
    # publishes audio directly (Phase 2 behaviour).
    await session.start(
        agent,
        room=ctx.room,
        room_output_options=room_io.RoomOutputOptions(audio_enabled=not avatar_on),
    )
    session.generate_reply(instructions=GREETING)
    await _publish_stage("intro", "", _limit_for(Stage.INTRO))  # initial stage for the indicator
    asyncio.create_task(_timer_loop())


if __name__ == "__main__":
    # Keep one process warm (dev default is 0) so a new interview doesn't pay the
    # ~1-2s "no warmed process available" spawn cost on connect.
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, num_idle_processes=1))
