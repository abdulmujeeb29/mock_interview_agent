"""The Assessor seam.

One interface, two implementations: a deterministic mock (Phase 1 / tests) and an
Astra-backed assessor (Phase 2). The pure core reads a ``TurnAssessment`` and cannot
tell which one produced it, so swapping the assessor never touches the core.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.types import StageConfig, TurnAssessment

# A transcript is an ordered list of (speaker, text) turns for the current stage.
# speaker is "candidate" or "interviewer".
Transcript = list

@runtime_checkable
class Assessor(Protocol):
    def assess(
        self,
        stage_config: StageConfig,
        transcript: Transcript,
    ) -> TurnAssessment:
        """Score how well each required field is covered, given the transcript so far."""
        ...
