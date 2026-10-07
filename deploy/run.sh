#!/bin/bash
# Start the registry API on localhost (nginx terminates TLS in front).
# Peer auth over the Unix socket — no DB password needed. Runs as www-data
# (systemd unit in deploy/registry.service is the normal path; this is the
# manual fallback — run it as www-data).
set -e
cd /var/www/skill-sharing-registry
export DATABASE_URL="postgresql+psycopg://www-data@/registry?host=/var/run/postgresql"
export HF_HOME=/var/www/skill-sharing-registry/.hf-cache
mkdir -p "$HF_HOME"
nohup ./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8077 \
  > /tmp/registry-app.log 2>&1 &
echo "registry started pid $!"
