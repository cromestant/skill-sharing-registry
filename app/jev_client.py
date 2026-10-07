"""Minimal stdlib client for TypeSafe's Jev decision API.

Used by the publish gate to screen recipes for malicious instructions and
leaked secrets. Honors the Jev skill's operating rules: JEV_GATE_ENABLED=0
kills every call; JEV_GATE_SAMPLE_RATE caps the fraction that hit the API.

Note: recipe text sent here goes to TypeSafe's API. Recipes are
public-to-members by design, so this is shareable — but never send
anything that isn't already destined for the shared corpus.
"""

import json
import logging
import os
import random
import urllib.request

log = logging.getLogger("registry.jev")

API_URL = "https://api.typesafe.ai/v1/systemone"
TIMEOUT_S = 10


def _config() -> dict:
    return {
        "enabled": os.environ.get("JEV_GATE_ENABLED", "1") == "1",
        "api_key": os.environ.get("JEV_API_KEY", ""),
        "sample_rate": float(os.environ.get("JEV_GATE_SAMPLE_RATE", "1.0")),
    }


def decide(state: str, questions: dict) -> dict | None:
    """Ask Jev; return the answers dict, or None when the gate is disabled,
    unconfigured, skipped by sampling, or the API call fails.

    None means "no verdict" — the caller decides the fail-open policy and
    logs accordingly. Never raises on API failure.
    """
    cfg = _config()
    if not cfg["enabled"]:
        return None
    if not cfg["api_key"]:
        log.warning("jev: JEV_API_KEY not set, gate skipped")
        return None
    if random.random() >= cfg["sample_rate"]:
        return None
    body = json.dumps(
        {"state": state, "model": "jev-latest", "questions": questions}
    ).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        log.warning("jev: api call failed (%s), gate skipped", exc)
        return None
    return payload.get("answers")
