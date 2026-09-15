"""Phase 1 terminal driver.

Type answers; the mock assessor turns them into field scores; the pure policy
decides; the loop prints the action, reason and both utilities, then asks the next
question or speaks the one bridge line and advances. No audio, no model, no network.

Run with:  python -m interview.cli
"""
from __future__ import annotations

import time

from .assess.mock import MockAssessor
from .core.state import SessionState, default_stage_configs, step
from .core.types import Action, Stage

OPENING_QUESTION = {
    Stage.INTRO: "Tell me a bit about yourself — who you are and what you do.",
    Stage.PAST_EXPERIENCE: "Tell me about a project you're proud of and your role in it.",
}

FOLLOWUP_PROMPT = {
    Stage.INTRO: "Can you say a little more — your current role and how long you've been at it?",
    Stage.PAST_EXPERIENCE: "Go deeper: what was your specific role, and what impact did it have?",
}


def _fmt(decision) -> str:
    return (
        f"[decision] action={decision.action.name:12} reason={decision.reason.name:8} "
        f"coverage={decision.coverage_score:.2f} "
        f"u_advance={decision.u_advance:.3f} u_followup={decision.u_followup:.3f}"
    )


def run() -> None:
    configs = default_stage_configs()
    assessor = MockAssessor()
    state = SessionState()

    clock_start = time.monotonic()
    state.stage_start_time = 0.0
    transcript: list = []

    print("=" * 72)
    print("AI Mock Interview — Phase 1 (typed). Ctrl-C to quit.")
    print("=" * 72)
    print(f"\nInterviewer: {OPENING_QUESTION[state.stage]}")

    while state.stage != Stage.DONE:
        try:
            answer = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[ended]")
            return
        if not answer:
            print("(say something — or Ctrl-C to quit)")
            continue

        transcript.append(("candidate", answer))
        cfg = configs[state.stage]
        assessment = assessor.assess(cfg, transcript)

        now = time.monotonic() - clock_start
        prev_stage = state.stage
        decision = step(state, cfg, assessment, now)
        print(_fmt(decision))

        if decision.action == Action.ADVANCE:
            # exactly one bridge line was stored by the locked switch
            print(f"\nInterviewer: {state.bridge_lines[-1]}")
            assessor.reset()
            transcript = []
            if state.stage != Stage.DONE:
                print(f"Interviewer: {OPENING_QUESTION[state.stage]}")
        else:
            print(f"\nInterviewer: {FOLLOWUP_PROMPT[prev_stage]}")

    print("\n" + "=" * 72)
    print(f"Interview complete. Bridge lines used: {len(state.bridge_lines)}")
    print("=" * 72)


if __name__ == "__main__":
    run()
