"""Astra-backed assessor (Azure Foundry, v1 Responses API).

Implements the same ``Assessor`` protocol as the Phase 1 mock, so the pure core
cannot tell them apart. It reads the running transcript for the current stage and
returns ``field_scores`` (0..1 per required field) plus ``last_followup_gain`` as
JSON. Parsing is defensive: anything malformed degrades to 0.0, never raises.

Wiring notes (verified against live docs, Sep 2026):
- The deployed resource exposes the OpenAI-compatible v1 API. We use the ``openai``
  SDK with ``base_url`` pointed at ``.../openai/v1`` and call ``responses.create``
  with the deployment NAME as ``model``. No ``api-version`` is needed on v1.
- This class does the network call directly; keeping it OFF the critical path is
  the job of ``BackgroundAssessor`` (see background.py), which wraps this.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from ..core.types import StageConfig, TurnAssessment

_SYSTEM = (
    "You are Astra, a strict mock-interview assessor. You read the transcript for the "
    "CURRENT interview stage and score, from 0.0 to 1.0, how well the candidate has "
    "covered each required field (0.0 = not addressed, 1.0 = thoroughly covered). You "
    "also estimate last_followup_gain: how much the MOST RECENT candidate turn improved "
    "overall coverage versus before it (0.0 = added nothing new, 1.0 = added a lot). "
    "Respond with ONLY a JSON object and no prose, of the exact form: "
    '{"field_scores": {"<field>": <0..1>, ...}, "last_followup_gain": <0..1>}'
)


def _build_user_input(cfg: StageConfig, transcript: list) -> str:
    lines = []
    for speaker, text in transcript:
        who = "Candidate" if speaker == "candidate" else "Interviewer"
        lines.append(f"{who}: {text}")
    convo = "\n".join(lines) if lines else "(no turns yet)"
    fields = ", ".join(cfg.required_fields)
    return (
        f"Required fields for this stage: {fields}.\n\n"
        f"Transcript so far:\n{convo}\n\n"
        f"Score exactly these fields as JSON: {fields}."
    )


def _extract_json(text: str) -> dict:
    if not text:
        return {}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _clamp01(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    return max(0.0, min(1.0, v))


def astra_base_url() -> str:
    """Derive the ``/openai/v1`` base the SDK needs from AZURE_ASTRA_ENDPOINT.

    The env var may point at the full ``.../openai/v1/responses`` path; the SDK
    appends ``/responses`` itself, so we strip it.
    """
    ep = os.environ.get("AZURE_ASTRA_ENDPOINT", "").split("?")[0].rstrip("/")
    if ep.endswith("/responses"):
        ep = ep[: -len("/responses")]
    return ep.rstrip("/")


class AstraAssessor:
    """Assessor backed by an Azure Responses-API deployment.

    ``client`` can be injected (tests pass a fake); otherwise an ``openai.OpenAI``
    client is built lazily from the environment.
    """

    def __init__(
        self,
        *,
        client: Any = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self._client = client
        self._model = model or os.environ.get("AZURE_ASTRA_DEPLOYMENT", "")
        self._base_url = base_url or astra_base_url()
        self._api_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY", "")

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI  # imported lazily so Phase 1 never needs it

            self._client = OpenAI(base_url=self._base_url, api_key=self._api_key)
        return self._client

    @staticmethod
    def _response_text(resp: Any) -> str:
        text = getattr(resp, "output_text", None)
        if isinstance(text, str) and text:
            return text
        # Fallback: walk the structured output.
        parts = []
        for item in getattr(resp, "output", None) or []:
            for chunk in getattr(item, "content", None) or []:
                t = getattr(chunk, "text", None)
                if isinstance(t, str):
                    parts.append(t)
        return "".join(parts)

    def assess(self, stage_config: StageConfig, transcript: list) -> TurnAssessment:
        client = self._get_client()
        resp = client.responses.create(
            model=self._model,
            input=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _build_user_input(stage_config, transcript)},
            ],
        )
        data = _extract_json(self._response_text(resp))
        raw_scores = data.get("field_scores", {})
        if not isinstance(raw_scores, dict):
            raw_scores = {}
        field_scores = {
            name: _clamp01(raw_scores.get(name, 0.0))
            for name in stage_config.required_fields
        }
        gain = _clamp01(data.get("last_followup_gain", 0.0))
        return TurnAssessment(field_scores=field_scores, last_followup_gain=gain)
