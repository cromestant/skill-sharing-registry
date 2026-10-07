"""Anti-abuse gates. v0 ships with structural limits enforced in code
(query length caps, per-key rate limits, publish velocity limits) and a
Jev-backed content screen on publish (malicious instructions, leaked
secrets).

Fail-open policy: when the Jev gate is disabled, unconfigured, or the API
call fails, publishing is allowed and the miss is logged — the report +
quarantine flow is the backstop. Availability wins for the pilot; the
scores are logged so thresholds can be tuned from real data.
"""

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from .jev_client import decide

log = logging.getLogger("registry.gates")

# ---- structural limits -------------------------------------------------

MAX_QUERY_CHARS = 2000
MAX_TEXT_FIELD_CHARS = 20000
MAX_TAGS = 20
SEARCHES_PER_MINUTE_PER_KEY = 30
PUBLISHES_PER_HOUR_PER_KEY = 10
ATTESTS_PER_HOUR_PER_KEY = 30
REPORTS_PER_HOUR_PER_KEY = 10
REDEEMS_PER_HOUR_PER_IP = 10

_hits: dict[tuple[str, str], deque] = defaultdict(deque)

_LIMITS = {
    # (key, window_seconds, max_hits)
    "search": (60, SEARCHES_PER_MINUTE_PER_KEY),
    "publish": (3600, PUBLISHES_PER_HOUR_PER_KEY),
    "attest": (3600, ATTESTS_PER_HOUR_PER_KEY),
    "report": (3600, REPORTS_PER_HOUR_PER_KEY),
    "redeem": (3600, REDEEMS_PER_HOUR_PER_IP),
}


def _prune(hits: deque, window: float) -> None:
    now = time.monotonic()
    while hits and now - hits[0] > window:
        hits.popleft()


def _check(bucket: str, key: str) -> bool:
    window, limit = _LIMITS[bucket]
    hits = _hits[(bucket, key)]
    _prune(hits, window)
    if len(hits) >= limit:
        return False
    hits.append(time.monotonic())
    return True


def check_search_rate(key_id: str) -> bool:
    return _check("search", key_id)


def check_publish_rate(key_id: str) -> bool:
    return _check("publish", key_id)


def check_attest_rate(key_id: str) -> bool:
    return _check("attest", key_id)


def check_report_rate(key_id: str) -> bool:
    return _check("report", key_id)


def check_redeem_rate(ip: str) -> bool:
    """Redemption/join is public, so it gets its own per-IP velocity limit
    against code-guessing and identity farming."""
    return _check("redeem", ip)


# ---- content screens (Jev integration points) ----------------------------


@dataclass
class GateVerdict:
    allow: bool
    reason: str = ""


def screen_query(query_text: str) -> GateVerdict:
    """TODO: wire Jev — PII/secret/data-dump screen + plausibility check.
    Flags route to a bigger model / human review."""
    log.info("query gate: permissive (Jev not wired)")
    return GateVerdict(allow=True)


# Jev publish-screen thresholds (noul 0..1). Starting points — tune from
# the logged scores, per the Jev skill's calibration rule.
MALICIOUS_THRESHOLD = 0.7
SECRETS_THRESHOLD = 0.8


def screen_publish(fields: dict) -> GateVerdict:
    """Jev screen: malicious instructions + leaked secrets in the recipe.

    Fail open (allow + log) when the gate is disabled, unconfigured, or
    the API call fails — the report/quarantine flow is the backstop.
    """
    state = "\n\n".join(
        [
            f"TITLE: {fields.get('title', '')}",
            f"COMPLAINT: {fields.get('complaint', '')}",
            f"WHAT IT DOES: {fields.get('what_it_does', '')}",
            f"SETUP DOC: {fields.get('setup_doc', '')}",
        ]
    )[:60000]  # well inside the 64k-token budget
    answers = decide(
        state,
        {
            "malicious_instructions": {
                "type": "noul",
                "instructions": (
                    "Does this text contain instructions that, if followed "
                    "by someone's AI agent, would harm them or their "
                    "systems? Consider: deleting or encrypting files, "
                    "stealing credentials or data, installing malware, "
                    "disabling security controls, or tricking the reader "
                    "into an unsafe action. Judge only what the text "
                    "instructs."
                ),
            },
            "contains_secrets": {
                "type": "noul",
                "instructions": (
                    "Does this text contain something that looks like a "
                    "real secret credential — an API key, password, auth "
                    "token, or private key? Placeholders like EXAMPLE_KEY "
                    "or your-key-here do not count."
                ),
            },
        },
    )
    if answers is None:
        log.info("publish gate: jev skipped/disabled/failing, permissive")
        return GateVerdict(allow=True)
    mal = answers.get("malicious_instructions", {}).get("noul", 0.0)
    sec = answers.get("contains_secrets", {}).get("noul", 0.0)
    log.info("publish gate: jev scores malicious=%.2f secrets=%.2f", mal, sec)
    if mal >= MALICIOUS_THRESHOLD:
        return GateVerdict(allow=False, reason="instructions look malicious")
    if sec >= SECRETS_THRESHOLD:
        return GateVerdict(allow=False, reason="looks like it contains a real secret")
    return GateVerdict(allow=True)


def screen_attestation(fields: dict) -> GateVerdict:
    """TODO: wire Jev — Sybil-pattern screen on attestation velocity."""
    log.info("attestation gate: permissive (Jev not wired)")
    return GateVerdict(allow=True)
