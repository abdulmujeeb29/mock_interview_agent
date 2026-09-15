"""Tavus avatar wiring (Phase 3).

Cosmetic and ADDITIVE: it puts a face on the Phase 2 voice agent by routing the
agent's audio to a Tavus persona, which publishes a lip-synced video track into the
LiveKit room. It must NEVER be able to break the working voice interview:

- Behind the ``AVATAR_ENABLED`` flag.
- ``start_avatar_if_enabled`` swallows ANY failure and returns False, so the caller
  falls back to the exact Phase 2 audio-only behaviour.

Nothing here imports or touches ``interview/core``.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger("interview.avatar")


def avatar_enabled() -> bool:
    return os.environ.get("AVATAR_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def _default_factory() -> Any:
    """Build a Tavus ``AvatarSession`` from the environment. Imported lazily so the
    rest of the app (and the tests) never need the Tavus plugin unless the avatar runs."""
    from livekit.plugins import tavus

    kwargs: dict = {}
    pal = os.environ.get("TAVUS_PERSONA_ID") or os.environ.get("TAVUS_PAL_ID")
    face = os.environ.get("TAVUS_REPLICA_ID") or os.environ.get("TAVUS_FACE_ID")
    api_key = os.environ.get("TAVUS_API_KEY")
    if pal:
        kwargs["pal_id"] = pal
    if face:
        kwargs["face_id"] = face
    if api_key:
        kwargs["api_key"] = api_key
    return tavus.AvatarSession(**kwargs)


async def start_avatar_if_enabled(
    session: Any,
    room: Any,
    *,
    enabled: Optional[bool] = None,
    factory: Callable[[], Any] = _default_factory,
) -> bool:
    """Start the Tavus avatar if enabled. Returns True only if it actually started.

    Returns False — so the caller runs audio-only Phase 2 — when the flag is off OR on
    ANY Tavus error (init, connect, join). This function never raises: the avatar is
    cosmetic and must not be able to take down the interview.
    """
    if enabled is None:
        enabled = avatar_enabled()
    if not enabled:
        return False

    try:
        avatar = factory()
        await avatar.start(session, room=room)
        wait = getattr(avatar, "wait_for_join", None)
        if callable(wait):
            await wait()
        logger.info("Tavus avatar started")
        return True
    except Exception as e:  # noqa: BLE001 - avatar must never break the interview
        logger.warning("avatar disabled; falling back to audio-only (Tavus failed): %s", e)
        return False
