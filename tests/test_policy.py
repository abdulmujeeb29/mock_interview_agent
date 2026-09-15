"""Phase 1 tests for the pure utility policy: the three doors, redundancy, the
hand-computed utility math, and the model-suggest nudge."""
from __future__ import annotations

import pytest

from interview.core.policy import decide
from interview.core.types import Action, Reason, Stage, UtilityWeights

from _helpers import assessment, make_cfg


def test_coverage_door():
    # Strong coverage -> ADVANCE with reason COVERAGE, even with budget and time left.
    cfg = make_cfg(high_coverage_threshold=0.85, followup_budget=3, time_limit_seconds=100)
    d = decide(
        Stage.INTRO, cfg,
        assessment({"a": 0.9, "b": 0.9}, gain=0.5),
        followups_used=0, elapsed_seconds=0.0,
    )
    assert d.action == Action.ADVANCE
    assert d.reason == Reason.COVERAGE


def test_budget_door():
    # Coverage kept low; budget=2. Feed follow-ups; ADVANCE/BUDGET fires at exactly
    # the budget, not one before.
    cfg = make_cfg(high_coverage_threshold=0.85, followup_budget=2, time_limit_seconds=100)
    a = assessment({"a": 0.4, "b": 0.4}, gain=0.5)  # not redundant, moderate coverage

    # one before the budget -> still asking, NOT a BUDGET advance
    before = decide(Stage.INTRO, cfg, a, followups_used=1, elapsed_seconds=0.0)
    assert before.reason != Reason.BUDGET
    assert before.action == Action.ASK_FOLLOWUP

    # exactly at the budget -> ADVANCE/BUDGET
    at = decide(Stage.INTRO, cfg, a, followups_used=2, elapsed_seconds=0.0)
    assert at.action == Action.ADVANCE
    assert at.reason == Reason.BUDGET

    # past the budget -> still BUDGET
    after = decide(Stage.INTRO, cfg, a, followups_used=3, elapsed_seconds=0.0)
    assert after.reason == Reason.BUDGET


def test_timer_door():
    # Coverage low, budget not spent, elapsed >= time_limit -> ADVANCE/TIMER.
    cfg = make_cfg(high_coverage_threshold=0.85, followup_budget=3, time_limit_seconds=90)
    d = decide(
        Stage.INTRO, cfg,
        assessment({"a": 0.1, "b": 0.1}, gain=0.5),
        followups_used=0, elapsed_seconds=90.0,
    )
    assert d.action == Action.ADVANCE
    assert d.reason == Reason.TIMER


def test_whichever_first():
    cfg = make_cfg(high_coverage_threshold=0.85, followup_budget=2, time_limit_seconds=90)

    # coverage is the earliest to fire: high coverage, budget/time untouched
    d_cov = decide(Stage.INTRO, cfg, assessment({"a": 0.9, "b": 0.9}),
                   followups_used=0, elapsed_seconds=0.0)
    assert d_cov.reason == Reason.COVERAGE

    # budget is the earliest to fire: low coverage, budget spent, time untouched
    d_bud = decide(Stage.INTRO, cfg, assessment({"a": 0.1, "b": 0.1}),
                   followups_used=2, elapsed_seconds=0.0)
    assert d_bud.reason == Reason.BUDGET

    # timer is the earliest to fire: low coverage, budget free, time expired
    d_tim = decide(Stage.INTRO, cfg, assessment({"a": 0.1, "b": 0.1}),
                   followups_used=0, elapsed_seconds=90.0)
    assert d_tim.reason == Reason.TIMER

    # priority when all three are satisfied at once: timer (hard safety) wins.
    d_all = decide(Stage.INTRO, cfg, assessment({"a": 0.9, "b": 0.9}),
                   followups_used=2, elapsed_seconds=90.0)
    assert d_all.reason == Reason.TIMER


def test_redundancy_no_repeat_followup():
    # last_followup_gain < epsilon marks the topic dead: prefer ADVANCE over another ASK.
    cfg = make_cfg(high_coverage_threshold=0.85, followup_budget=3, time_limit_seconds=100)
    scores = {"a": 0.4, "b": 0.4}

    redundant = decide(Stage.INTRO, cfg, assessment(scores, gain=0.0),  # < epsilon
                       followups_used=0, elapsed_seconds=0.0)
    assert redundant.action == Action.ADVANCE
    assert redundant.reason == Reason.UTILITY

    # Same coverage, but with real gain, the policy DOES want another follow-up.
    productive = decide(Stage.INTRO, cfg, assessment(scores, gain=0.5),
                        followups_used=0, elapsed_seconds=0.0)
    assert productive.action == Action.ASK_FOLLOWUP


def test_utility_argmax():
    # Hand-computed with default weights (w_cov=1, w_time=0.4, w_flow=0.1,
    # w_redundant=0.6, epsilon=0.05), time_limit=100.
    cfg = make_cfg(fields=("a", "b"), high_coverage_threshold=0.85,
                   followup_budget=3, time_limit_seconds=100, weights=UtilityWeights())
    # coverage = 0.5, elapsed=10 -> time_pressure=0.1, gain=0.5 (not redundant)
    a = assessment({"a": 0.5, "b": 0.5}, gain=0.5)
    d = decide(Stage.INTRO, cfg, a, followups_used=0, elapsed_seconds=10.0)

    # u_advance  = 1*0.5 + 0.4*0.1 + 0.1              = 0.64
    # u_followup = 1*(0.5 + 0.5) - 0.4*0.1 - 0.6*0     = 0.96
    assert d.coverage_score == pytest.approx(0.5)
    assert d.u_advance == pytest.approx(0.64)
    assert d.u_followup == pytest.approx(0.96)
    assert d.action == Action.ASK_FOLLOWUP
    assert d.reason == Reason.UTILITY


def test_model_suggest_is_nudge_not_command():
    # model_suggests_advance=True but very low coverage and fresh time: still ASK.
    cfg = make_cfg(high_coverage_threshold=0.85, followup_budget=3, time_limit_seconds=100)
    a = assessment({"a": 0.1, "b": 0.1}, gain=0.5, suggest=True)
    d = decide(Stage.INTRO, cfg, a, followups_used=0, elapsed_seconds=0.0)
    assert d.action == Action.ASK_FOLLOWUP  # the signal biases, it does not force
