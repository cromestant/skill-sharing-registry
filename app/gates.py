"""Anti-abuse gates. v0 ships with structural limits enforced in code
(query length caps, per-key rate limits, publish velocity limits) and a
pluggable content-screen interface.

The design calls for a cheap classifier (Jev) at three checkpoints —
query ingress, publish, attestation — as *triage*, not a security
boundary. That wiring is a TODO: `screen_publish`, `screen_query`, and
`screen_attestation` are the integration points. Until wired, they are
permissive and every decision is logged.
"""

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass

log = logging.getLogger("registry.gates")

# ---- structural limits -------------------------------------------------

MAX_QUERY_CHARS = 2000
MAX_TEXT_FIELD_CHARS = 20000
MAX_TAGS = 20
SEARCHES_PER_MINUTE_PER_KEY = 30
PUBLISHES_PER_HOUR_PER_KEY = 10
REDEEMS_PER_HOUR_PER_IP = 10

_search_hits: dict[str, deque] = defaultdict(deque)
_publish_hits: dict[str, deque] = defaultdict(deque)
_redeem_hits: dict[str, deque] = defaultdict(deque)


def _prune(hits: deque, window: float) -> None:
    now = time.monotonic()
    while hits and now - hits[0] > window:
        hits.popleft()


def check_search_rate(key_id: str) -> bool:
    hits = _search_hits[key_id]
    _prune(hits, 60)
    if len(hits) >= SEARCHES_PER_MINUTE_PER_KEY:
        return False
    hits.append(time.monotonic())
    return True


def check_publish_rate(key_id: str) -> bool:
    hits = _publish_hits[key_id]
    _prune(hits, 3600)
    if len(hits) >= PUBLISHES_PER_HOUR_PER_KEY:
        return False
    hits.append(time.monotonic())
    return True


def check_redeem_rate(ip: str) -> bool:
    """Redemption is the one public endpoint, so it gets its own
    per-IP velocity limit against code-guessing."""
    hits = _redeem_hits[ip]
    _prune(hits, 3600)
    if len(hits) >= REDEEMS_PER_HOUR_PER_IP:
        return False
    hits.append(time.monotonic())
    return True


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


def screen_publish(fields: dict) -> GateVerdict:
    """TODO: wire Jev — malicious-instruction screen, manifest-vs-doc
    consistency check, secret/PII scrub of the setup doc."""
    log.info("publish gate: permissive (Jev not wired)")
    return GateVerdict(allow=True)


def screen_attestation(fields: dict) -> GateVerdict:
    """TODO: wire Jev — Sybil-pattern screen on attestation velocity."""
    log.info("attestation gate: permissive (Jev not wired)")
    return GateVerdict(allow=True)
