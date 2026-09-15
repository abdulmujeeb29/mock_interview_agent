"""Setup step 6 — transport smoke test.

A throwaway agent that joins a LiveKit room and speaks ONE fixed line via the Azure
gpt-realtime deployment. Proves keys + the Azure deployment + transport BEFORE any
interview logic. If you can join from a browser and hear the line, Setup is done.

Run:
    python -m interview.voice.smoke dev
Then open your LiveKit project's Agents console / playground and start a session.
"""
from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli

from .agent import build_realtime_model

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH, override=True)
logging.basicConfig(level=logging.INFO)

LINE = (
    "Hello. This is the mock interview agent transport smoke test. If you can hear this, "
    "the Azure real-time deployment and LiveKit are working."
)


async def entrypoint(ctx: JobContext) -> None:
    load_dotenv(_ENV_PATH, override=True)  # ensure the job subprocess uses .env, not a stale shell key
    session = AgentSession(llm=build_realtime_model())
    await ctx.connect()
    await session.start(Agent(instructions="Say only the exact line you are given."), room=ctx.room)
    # Realtime sessions don't support say(); drive the utterance with generate_reply.
    session.generate_reply(instructions=f'Say this exact line and nothing else: "{LINE}"')


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
