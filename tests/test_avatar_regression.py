"""Phase 3 tests: the Tavus avatar is additive and can never break the interview.

The real "video track appears in the room" check needs live Tavus + LiveKit and is
verified on the Playground; here we prove the wiring's behaviour deterministically with
a fake avatar, and that the decision core is completely unaffected by the avatar.
"""
from __future__ import annotations

import asyncio

from interview.avatar.tavus_avatar import start_avatar_if_enabled
from interview.core.state import default_stage_configs
from interview.core.types import Action, Stage, TurnAssessment
from interview.voice.controller import StageController


class _FakeAvatar:
    def __init__(self, fail_on: str | None = None) -> None:
        self.fail_on = fail_on
        self.started = False
        self.joined = False

    async def start(self, session, room=None):
        if self.fail_on == "start":
            raise RuntimeError("tavus start failed")
        self.started = True

    async def wait_for_join(self):
        if self.fail_on == "join":
            raise RuntimeError("tavus join failed")
        self.joined = True


def test_avatar_starts_when_enabled():
    # Proxy for "video track appears": the avatar starts and joins the room. (The real
    # track is verified live on the Playground.)
    fake = _FakeAvatar()
    ok = asyncio.run(start_avatar_if_enabled(object(), object(), enabled=True, factory=lambda: fake))
    assert ok is True
    assert fake.started and fake.joined


def test_avatar_failure_isolation():
    # THE most important Phase 3 test: any Tavus failure must fall back to audio-only
    # (return False) without raising, so the interview still runs.

    # 1) factory/init raises
    def bad_factory():
        raise RuntimeError("tavus init failed")

    assert asyncio.run(start_avatar_if_enabled(object(), object(), enabled=True, factory=bad_factory)) is False

    # 2) avatar.start raises
    assert asyncio.run(
        start_avatar_if_enabled(object(), object(), enabled=True, factory=lambda: _FakeAvatar(fail_on="start"))
    ) is False

    # 3) wait_for_join raises
    assert asyncio.run(
        start_avatar_if_enabled(object(), object(), enabled=True, factory=lambda: _FakeAvatar(fail_on="join"))
    ) is False

    # 4) disabled: never even builds the avatar
    called = {"v": False}

    def tracking_factory():
        called["v"] = True
        return _FakeAvatar()

    assert asyncio.run(
        start_avatar_if_enabled(object(), object(), enabled=False, factory=tracking_factory)
    ) is False
    assert called["v"] is False


class _ScriptedAssessor:
    def __init__(self, script):
        self._script = list(script)
        self._i = 0

    def assess(self, stage_config, transcript):
        item = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        return TurnAssessment(
            field_scores={f: item["cov"] for f in stage_config.required_fields},
            last_followup_gain=item.get("gain", 0.5),
        )


def test_core_unaffected_by_avatar():
    # The avatar is cosmetic: the decision flow is identical to Phase 2. A scripted
    # two-stage run still reaches DONE with exactly one bridge line per transition.
    cfg_map = default_stage_configs()
    spoken = []
    clock = {"t": 0.0}
    controller = StageController(
        assessor=_ScriptedAssessor([{"cov": 0.95, "gain": 0.5}]),  # high coverage -> COVERAGE
        speak=lambda t: spoken.append(t),
        clock=lambda: clock["t"],
        configs=cfg_map,
    )
    for _ in range(6):
        if controller.state.stage == Stage.DONE:
            break
        clock["t"] += 5.0
        controller.on_user_turn([("candidate", "a thorough answer")])

    assert controller.state.stage == Stage.DONE
    assert len(controller.state.bridge_lines) == 2  # one per transition, unchanged
    assert spoken == controller.state.bridge_lines
