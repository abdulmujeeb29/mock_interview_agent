"""Deterministic keyword-based assessor for Phase 1 and tests.

No network, no model. It scans the candidate's answers for per-field keywords and
returns 0..1 field scores plus the coverage gain since the previous call. This is
what lets ``python -m interview.cli`` cover-out on rich answers and spend the budget
on vague ones, entirely offline.
"""
from __future__ import annotations

from ..core.policy import coverage_score
from ..core.types import StageConfig, TurnAssessment

# Per-field keyword cues. Presence of any cue in the candidate's answers scores the
# field. Kept intentionally simple and transparent for a deterministic demo.
FIELD_KEYWORDS: dict[str, list[str]] = {
    # INTRO
    "name": ["name", "i'm", "i am", "call me", "myself"],
    "current_role": ["engineer", "developer", "manager", "designer", "role", "work as", "i'm a", "scientist", "lead"],
    "background": ["background", "studied", "degree", "graduated", "experience in", "worked", "specializ"],
    "years_experience": ["year", "years", "yrs", "decade", "months"],
    # PAST_EXPERIENCE
    "project": ["project", "built", "shipped", "system", "app", "platform", "feature", "product"],
    "your_role": ["i led", "i built", "i was responsible", "my role", "i owned", "i designed", "i implemented"],
    "impact": ["impact", "increased", "reduced", "saved", "improved", "revenue", "users", "percent", "%", "growth"],
    "depth_probed": ["because", "trade-off", "tradeoff", "challenge", "decided", "architecture", "why", "approach"],
}


class MockAssessor:
    """Stateful so it can report ``last_followup_gain`` between turns."""

    def __init__(self) -> None:
        self._prev_coverage = 0.0

    def reset(self) -> None:
        self._prev_coverage = 0.0

    def _score_field(self, name: str, text: str) -> float:
        cues = FIELD_KEYWORDS.get(name, [])
        hits = sum(1 for cue in cues if cue in text)
        if hits == 0:
            return 0.0
        # First hit gets you most of the way; extra cues top it up. A longer answer
        # nudges it as well so thin answers stay below the coverage door.
        base = min(1.0, 0.6 + 0.2 * hits)
        return base

    def assess(self, stage_config: StageConfig, transcript: list) -> TurnAssessment:
        candidate_text = " ".join(
            text.lower()
            for speaker, text in transcript
            if speaker == "candidate"
        )

        field_scores = {
            name: self._score_field(name, candidate_text)
            for name in stage_config.required_fields
        }

        assessment = TurnAssessment(field_scores=field_scores)
        current = coverage_score(stage_config, assessment)
        assessment.last_followup_gain = max(0.0, current - self._prev_coverage)
        self._prev_coverage = current
        return assessment
