#!/bin/bash
# Start the registry API on localhost (nginx terminates TLS in front).
# Peer auth over the Unix socket — no DB password needed.
# (Normally managed via the systemd user service; this is the manual fallback.)
set -e
cd /var/www/skill-sharing-registry
export DATABASE_URL="postgresql+psycopg://muse@/registry?host=/var/run/postgresql"
export HF_HOME=/var/www/skill-sharing-registry/.hf-cache
mkdir -p "$HF_HOME"
nohup ./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8077 \
  > /tmp/registry-app.log 2>&1 &
echo "registry started pid $!"
