#!/usr/bin/env bash
# Resumable study-window ingest. Re-run any time: complete days are skipped (manifest), each day commits atomically,
# so a restart loses at most the day in progress. Dev days first, held-out days last (they are ingested but not examined).
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
DAYS=$($PY - <<'PYEOF'
from tashwish.split import split
dev, held = split()
print(" ".join(d.isoformat() for d in [*dev, *held]))
PYEOF
)
for d in $DAYS; do
  for attempt in 1 2 3 4; do
    $PY -m tashwish.ingest --day "$d" --out data/interim --spool data/raw/spool --workers 2 && break
    echo "$(date -u +%FT%TZ) $d attempt $attempt failed" >&2
    sleep 20
  done
done
echo "$(date -u +%FT%TZ) study ingest finished"
