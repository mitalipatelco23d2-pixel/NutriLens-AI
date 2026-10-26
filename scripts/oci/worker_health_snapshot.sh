#!/usr/bin/env bash
set -euo pipefail

systemctl is-active nutrilens-ai-worker.service
docker inspect nutrilens-ai-worker \
  --format '{{json .State}}'
docker stats --no-stream --format \
  '{{json .}}' nutrilens-ai-worker
df -h /
journalctl --unit nutrilens-ai-worker.service --since '30 minutes ago' \
  --no-pager --lines 200
