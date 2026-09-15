"""Keep the assessor OFF the critical path.

``BackgroundAssessor`` wraps any ``Assessor`` (Astra in production). Its ``assess``
returns the latest cached ``TurnAssessment`` IMMEDIATELY and kicks off a background
refresh in a thread. The conversation never waits on a score: if the freshest score
is not back yet, the policy reads the most recent available one and the timer/budget
still guard the flow. This is the latency-safety guarantee the brief demands.

A thread (not an asyncio task) is used deliberately so the wrapper is framework-
agnostic and unit-testable without a running event loop.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from ..core.types import StageConfig, TurnAssessment

logger = logging.getLogger("interview.assess")


class BackgroundAssessor:
    def __init__(self, inner: Any, initial: Optional[TurnAssessment] = None) -> None:
        self._inner = inner
        # Initial gain is 1.0, NOT 0.0: before Astra has scored anything we must not
        # look "redundant" (gain < epsilon), or the policy would treat the very first
        # turn as a dead topic and advance immediately. 1.0 => not redundant => the
        # policy asks a follow-up until real scores arrive.
        self._latest = initial or TurnAssessment(field_scores={}, last_followup_gain=1.0)
        self._lock = threading.Lock()
        self._inflight = False
        self._version = 0  # bumped every time a fresh score lands

    def _run(self, stage_config: StageConfig, transcript: list) -> None:
        try:
            result = self._inner.assess(stage_config, transcript)
            with self._lock:
                self._latest = result
                self._version += 1
            logger.info(
                "assessor updated: scores=%s gain=%.2f",
                {k: round(v, 2) for k, v in result.field_scores.items()},
                result.last_followup_gain,
            )
        except Exception as e:  # noqa: BLE001 - never let a background error surface on the call path
            logger.warning("assessor call failed (kept previous scores): %s", e)
        finally:
            with self._lock:
                self._inflight = False

    def refresh(self, stage_config: StageConfig, transcript: list) -> None:
        """Start a background refresh unless one is already running (single-flight)."""
        with self._lock:
            if self._inflight:
                return
            self._inflight = True
        threading.Thread(
            target=self._run,
            args=(stage_config, list(transcript)),
            daemon=True,
        ).start()

    def latest(self) -> TurnAssessment:
        with self._lock:
            return self._latest

    def version(self) -> int:
        """Monotonic counter; increments each time a fresh score lands. Lets the voice
        layer wait for THIS answer to be scored before deciding."""
        with self._lock:
            return self._version

    def reset(self) -> None:
        """Start a fresh stage: forget cached scores and look 'not yet scored' again
        (gain 1.0 => not redundant), so a new stage cannot inherit the previous stage's
        low gain and advance immediately."""
        with self._lock:
            self._latest = TurnAssessment(field_scores={}, last_followup_gain=1.0)
            self._version += 1
        inner_reset = getattr(self._inner, "reset", None)
        if callable(inner_reset):
            inner_reset()

    def assess(self, stage_config: StageConfig, transcript: list) -> TurnAssessment:
        """Off-path: trigger a refresh and return the most recent score right away."""
        self.refresh(stage_config, transcript)
        return self.latest()

    def wait_idle(self, timeout: Optional[float] = None) -> bool:
        """Block until no refresh is in flight. For tests/shutdown only."""
        start = time.monotonic()
        while True:
            with self._lock:
                if not self._inflight:
                    return True
            if timeout is not None and time.monotonic() - start > timeout:
                return False
            time.sleep(0.005)
