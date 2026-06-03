#!/bin/zsh
# WHAT: one daily sample for the v0.0b robustness gate.
# WHY:  the gate (success criterion a) wants the transient-failure rate on ACTIVE
#       feeds held < 15% across ~7 daily ingests. This runs one ingest against the
#       real local store (~/.aib-reader/store.db) and appends a dated TSV line to a
#       running log so the 7-run sample can be evaluated. Driven by a launchd agent
#       (com.astgl.aib-reader.robustness) — see scripts/com.astgl.aib-reader.robustness.plist.
#
# Safe to run by hand any time:  ./scripts/robustness-sample.sh
set -euo pipefail

PROJECT="/Users/jamescruce/Projects/aib-reader"
UV="/opt/homebrew/bin/uv"
LOG="${AIB_GATE_LOG:-$PROJECT/tasks/robustness-gate.log}"

cd "$PROJECT"

# Run the ingest via the library so we get structured counts (not brittle CLI text).
# stdout -> the TSV log line; stderr (the app's logging) -> launchd's own log file.
AIB_GATE_LOG="$LOG" "$UV" run python - <<'PY'
import os
from datetime import datetime

from aib_reader import list_feeds, poll_feeds

summary = poll_feeds()
active = sum(1 for f in list_feeds() if f.active)
attempted = summary.feeds_polled + summary.feeds_failed
rate = (summary.feeds_failed / attempted * 100.0) if attempted else 0.0

ts = datetime.now().astimezone().isoformat(timespec="seconds")
line = (
    f"{ts}\tactive_feeds={active}\tattempted={attempted}\t"
    f"ok={summary.feeds_polled}\tfailed={summary.feeds_failed}\t"
    f"fail_rate={rate:.1f}%\tnew_items={summary.new_items}\n"
)

log_path = os.environ["AIB_GATE_LOG"]
os.makedirs(os.path.dirname(log_path), exist_ok=True)
with open(log_path, "a", encoding="utf-8") as fh:
    fh.write(line)

# Also echo to stdout so an interactive run shows the result immediately.
print(line, end="")
PY
