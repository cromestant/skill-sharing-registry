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
        "title": "Watch a product page for restock with a scheduled browser agent",
        "complaint": "There's a product I want that keeps selling out before I can buy it, and I can't sit there refreshing the page all day. I want to know the minute it's actually purchasable — not 'maybe', not a false alarm from a loading spinner.",
        "what_it_does": "A scheduled job spawns a live-browser task every 30 minutes to check the buy-box state on the product page. It reads the accessibility tree (never screenshots) for the real button state, recovers from stuck loading placeholders with a fresh navigation, and stays silent unless the state changed. On an enabled buy button it either alerts immediately or proceeds through a pre-authorized purchase flow.",
        "setup_doc": (
            "1. Pick the product page URL (PDP) and confirm it renders the buy box without login.\n"
            "2. Create a cron job every 30 minutes that spawns one live-browser task per retailer with this brief:\n"
            "   - Navigate to the PDP, wait for the buy box to settle.\n"
            "   - Read the button state from the accessibility tree: enabled vs disabled, exact label, price.\n"
            "   - If the buy box is stuck on a disabled 'Loading' placeholder after ~40s, do a FRESH navigation\n"
            "     (navigate away and back as a new page load, not a reload) — reloads often don't clear it.\n"
            "   - Report one of: purchasable (with price), not purchasable (with button label), or indeterminate.\n"
            "   - Read-only: click nothing except when executing a pre-authorized purchase.\n"
            "3. Handoff reliability: browser-task handoffs sometimes go silent (task completes, no report).\n"
            "   Before declaring a check failed, read the worker's completion result — the verdict is usually there.\n"
            "   Only re-spawn if the completion result is also empty.\n"
            "4. State tracking: keep a small state file with the last observed button state per retailer.\n"
            "   Alert (or purchase) only on transitions to purchasable. Routine no-op runs stay silent.\n"
            "5. Purchase flow (optional, needs explicit pre-authorization): on a confirmed enabled buy button,\n"
            "   spawn a checkout task with the exact item, quantity, shipping address, and payment method.\n"
            "   The human handles CAPTCHAs — the agent must stop and hand over at any human-verification step.\n"
            "6. Stop condition: when the item is secured or the watch is no longer wanted, remove the cron."
        ),
        "prerequisites": "A Muse-compatible agent with live-browser tasks and cron/scheduling. Product page must render the buy box without login.",
        "tags": ["shopping", "monitoring", "browser-automation", "scheduling"],
        "manifest": {
            "schedules": ["every 30 minutes"],
            "tools": ["live browser task", "cron"],
            "data_scopes": ["product page (read-only until purchase)", "cart/checkout (only on pre-authorized purchase)"],
        },
    },
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
