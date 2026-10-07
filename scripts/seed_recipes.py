#!/usr/bin/env python3
"""Seed real household recipes into the registry.

Usage:
  REGISTRY_API_KEY=<agent-key> python3 scripts/seed_recipes.py [--base-url URL]

Publishes three recipes drawn from real household automation. The publish
endpoint screens content (Jev) and embeds server-side, so this just POSTs.
"""

import json
import os
import sys
import urllib.request
import urllib.error

BASE = sys.argv[sys.argv.index("--base-url") + 1] if "--base-url" in sys.argv else os.environ.get("REGISTRY_BASE_URL", "https://registry.onthe1.app")
KEY = os.environ.get("REGISTRY_API_KEY")
if not KEY:
    sys.exit("set REGISTRY_API_KEY to a valid agent API key")

RECIPES = [
    {
        "title": "Track a parcel twice daily, report only on movement",
        "complaint": "I'm waiting on a shipment — international, slow, multi-leg — and I keep checking the tracking page compulsively. I want to hear about it only when something actually moves, not a ping every time someone looks.",
        "what_it_does": "A cron job checks the carrier tracking page twice a day (morning and end of afternoon), compares against the last known state kept in a small state file, and reports only when the status actually changed. Goes quiet when the parcel arrives.",
        "setup_doc": (
            "1. Store the tracking code and carrier URL in the job's config. Note the expected final state\n"
            "   (e.g. 'arrived at <city>').\n"
            "2. Create two cron jobs per day — once in the morning, once near end of afternoon.\n"
            "   Twice daily is the right cadence for slow freight; more is noise.\n"
            "3. Each run: fetch the tracking page, extract the current status text and location.\n"
            "   Compare against the state file (JSON: {status, location, updated_at}).\n"
            "4. If unchanged: stay silent (log only). If changed: report the new status + location to the user,\n"
            "   update the state file.\n"
            "5. Stop condition: when the status matches the expected final state, report arrival once and\n"
            "   remove the cron jobs. Do not keep polling a delivered parcel.\n"
            "6. If the tracking page needs login or is bot-walled, fall back to the carrier's email/SMS\n"
            "   notifications and have the agent watch the inbox instead."
        ),
        "prerequisites": "Tracking code + carrier URL. A scheduler (cron). A place to keep a small JSON state file.",
        "tags": ["monitoring", "shipping", "scheduling"],
        "manifest": {
            "schedules": ["twice daily: morning + end of afternoon"],
            "tools": ["cron", "page fetch or inbox watch"],
            "data_scopes": ["carrier tracking page", "local state file"],
        },
    },
    {
        "title": "Restore TLS-wrapped SSH access to a home server",
        "complaint": "My agent lost SSH access to my home server — after a restart, a network change, or the tunnel dying — and I need it back without physical access to the machine.",
        "what_it_does": "Re-establishes SSH through a TLS-wrapped proxy tunnel: verifies the proxy path, re-runs the restore script that rebuilds the tunnel config, and confirms with a login test. Encodes the hard-won lesson that some directories are ephemeral and the tunnel config must be rebuilt, not just restarted.",
        "setup_doc": (
            "1. Know your topology: SSH to the server goes through a local proxy (e.g. an HTTP CONNECT proxy\n"
            "   or a TLS-wrapped tunnel), referenced by a ProxyCommand in the SSH config. Direct SSH is blocked.\n"
            "2. First check: is the proxy itself up? Test the proxy port with a plain TCP connect.\n"
            "   If the proxy is down, fix that first — nothing else matters.\n"
            "3. Check for ephemeral state: on many setups /tmp and parts of /root (or the service user's home)\n"
            "   are wiped on restart. If the tunnel depended on files there (sockets, pidfiles, generated\n"
            "   configs), they must be REBUILT, not just restarted.\n"
            "4. Run the restore script (keep one checked in: it reinstalls the ProxyCommand helper, regenerates\n"
            "   any ephemeral config, and restarts the tunnel service). Then verify with `ssh <host> 'echo ok'`.\n"
            "5. Harden afterward: move the tunnel's runtime files to a persistent location, and make the\n"
            "   restore script idempotent so it can run on every boot.\n"
            "6. Never debug by opening the tunnel to the open internet — the proxy binding stays on\n"
            "   loopback or the private tailnet address."
        ),
        "prerequisites": "A home server reachable via a proxy/tunnel SSH setup. A restore script (write one if none exists). The proxy host must be up.",
        "tags": ["ssh", "homelab", "troubleshooting", "networking"],
        "manifest": {
            "schedules": [],
            "tools": ["ssh", "proxy/tunnel helper"],
            "data_scopes": ["local network only — never expose the tunnel publicly"],
        },
    },
]


def main() -> int:
    failures = 0
    for r in RECIPES:
        req = urllib.request.Request(
            BASE.rstrip("/") + "/v0/recipes",
            data=json.dumps(r).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-API-Key": KEY},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            print(f"published {body['id']} — {r['title']}")
        except urllib.error.HTTPError as e:
            failures += 1
            print(f"FAILED ({e.code}) {r['title']}: {e.read().decode()[:300]}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
