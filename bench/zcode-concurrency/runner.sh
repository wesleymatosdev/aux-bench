#!/usr/bin/env bash
# zcode-concurrency lane runner. Pure bash — NO LLM anywhere in the runner.
#
# Usage: runner.sh <concurrency> <lane-dir>
#
# Spawns <concurrency> concurrent `zcode -p` processes, one per run-i/
# subdirectory of <lane-dir>, each solving the byte-identical composite task
# in tasks/composite.md against a fresh cwd. Per run:
#   - in.json is seeded with a known trailing-comma break (S4 input)
#   - stdout+stderr captured verbatim to run-i/stdout.log
#   - wall time (ms) to run-i/duration_ms, exit code + status to run-i/meta.json
#   - 900s per-run timeout: the runner kills the whole process tree and records
#     status=timeout. A timeout is a failure class of its own — never scored as
#     model failure, mirroring aux-bench's truncation convention.
# Missing output stays missing: nothing here retries, edits, or fabricates.

set -u

CONCURRENCY="${1:?usage: runner.sh <concurrency> <lane-dir>}"
LANE_DIR="${2:?usage: runner.sh <concurrency> <lane-dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK_FILE="$SCRIPT_DIR/tasks/composite.md"

RUN_TIMEOUT_MS=900000     # per-run wall budget (15 min)
TERM_GRACE_SECS=5         # TERM -> wait -> KILL
LANE_HARD_CAP_MS=1080000  # absolute lane cap (18 min); survivors are killed as timeout
POLL_SECS=1
PROC_SAMPLE_EVERY=5       # sample system-wide zcode-cli count every N polls

[ -r "$TASK_FILE" ] || { echo "FATAL: task file missing: $TASK_FILE" >&2; exit 2; }
command -v zcode >/dev/null || { echo "FATAL: zcode not on PATH" >&2; exit 2; }
PROMPT="$(cat "$TASK_FILE")"
TASK_SHA="$(shasum -a 256 "$TASK_FILE" | awk '{print $1}')"

mkdir -p "$LANE_DIR"
LANE_DIR="$(cd "$LANE_DIR" && pwd)"

now_ms() { perl -MTime::HiRes=time -e 'printf("%d\n", time()*1000)'; }

# Kill a pid and every descendant (zcode is a sh wrapper -> node -> zcode-cli).
kill_tree() {
  local pid="$1" sig="$2" child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child" "$sig"
  done
  kill -"$sig" "$pid" 2>/dev/null || true
}

zcode_cli_count() { pgrep -x zcode-cli | wc -l | tr -d ' '; }

capture_env() { # $1 = outfile, $2 = label
  {
    echo "label: $2"
    echo "date: $(date '+%Y-%m-%d %H:%M:%S %z')"
    echo "zcode_version: $(zcode --version 2>&1 | head -1)"
    echo "zcode_version_full: $(zcode version 2>&1 | tr '\n' ' ')"
    echo "system_wide_zcode_cli_procs: $(zcode_cli_count)"
    echo "memory: $(memory_pressure | tail -1)"
    echo "hw_memsize: $(sysctl -n hw.memsize)"
    echo "hw_model: $(sysctl -n hw.model)"
    echo "hw_ncpu: $(sysctl -n hw.ncpu)"
    echo "--- ps aux | head -15 ---"
    ps aux | head -15
  } > "$1" 2>&1
}

seed_in_json() { # $1 = run dir; deterministic, byte-identical every seed
  cat > "$1/in.json" <<'EOF'
{
  "bench": "zcode-concurrency",
  "year": 2026,
  "constants": {
    "width": 128,
    "height": 64,
    "offset": 7,
  },
}
EOF
}

echo "lane: concurrency=$CONCURRENCY dir=$LANE_DIR"
echo "task_sha256: $TASK_SHA"
echo "per_run_timeout_ms: $RUN_TIMEOUT_MS"
capture_env "$LANE_DIR/env-before.txt" "before"

declare -a PIDS=() STARTS=() STATUS=() EXITCODES=() DURATIONS=() RUN_DIRS=()
for i in $(seq 1 "$CONCURRENCY"); do
  run_dir="$LANE_DIR/run-$i"
  mkdir -p "$run_dir"
  seed_in_json "$run_dir"
  RUN_DIRS[$i]="$run_dir"
  STARTS[$i]="$(now_ms)"
  zcode -p "$PROMPT" --cwd "$run_dir" --mode yolo > "$run_dir/stdout.log" 2>&1 &
  PIDS[$i]=$!
  STATUS[$i]="running"
  echo "launched run-$i pid=${PIDS[$i]}"
done
lane_start_ms="$(now_ms)"
lane_deadline_ms=$((lane_start_ms + LANE_HARD_CAP_MS))
echo "all launched at $(date '+%H:%M:%S'); lane hard cap in $((LANE_HARD_CAP_MS/1000))s"

poll=0
while :; do
  sleep "$POLL_SECS"
  poll=$((poll + 1))
  now="$(now_ms)"
  running=0
  for i in $(seq 1 "$CONCURRENCY"); do
    [ "${STATUS[$i]:-running}" != "running" ] && continue
    pid="${PIDS[$i]}"
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid"; rc=$?
      STATUS[$i]="completed"; EXITCODES[$i]="$rc"
    elif [ $((now - ${STARTS[$i]})) -ge "$RUN_TIMEOUT_MS" ] || [ "$now" -ge "$lane_deadline_ms" ]; then
      echo "run-$i over budget -> killing process tree (pid=$pid)"
      kill_tree "$pid" TERM
      sleep "$TERM_GRACE_SECS"
      kill_tree "$pid" KILL
      wait "$pid" 2>/dev/null; rc=$?
      STATUS[$i]="timeout"; EXITCODES[$i]="$rc"
    else
      running=$((running + 1))
      continue
    fi
    DURATIONS[$i]=$(( $(now_ms) - ${STARTS[$i]} ))
  done
  if [ $((poll % PROC_SAMPLE_EVERY)) -eq 0 ]; then
    echo "$(date '+%H:%M:%S') running=$running zcode_cli_system_wide=$(zcode_cli_count)" \
      | tee -a "$LANE_DIR/zcode-cli-count.log"
  else
    echo "$(date '+%H:%M:%S') running=$running"
  fi
  [ "$running" -eq 0 ] && break
done

for i in $(seq 1 "$CONCURRENCY"); do
  run_dir="${RUN_DIRS[$i]}"
  printf '%s\n' "${DURATIONS[$i]}" > "$run_dir/duration_ms"
  python3 - "$run_dir/meta.json" "$i" "${PIDS[$i]}" "${STATUS[$i]}" \
    "${EXITCODES[$i]:-none}" "${DURATIONS[$i]}" "$TASK_SHA" <<'PYEOF'
import json, sys, time
out, run_i, pid, status, exit_code, duration_ms, task_sha = sys.argv[1:8]
json.dump({
    "run": int(run_i),
    "pid": int(pid),
    "status": status,               # completed | timeout (timeout = own class, not model failure)
    "exit_code": exit_code,
    "duration_ms": int(duration_ms),
    "task_sha256": task_sha,        # proves the prompt was byte-identical across runs
    "recorded_at_unix": int(time.time()),
}, open(out, "w"), indent=2)
PYEOF
  echo "run-$i status=${STATUS[$i]} exit=${EXITCODES[$i]:-none} duration_ms=${DURATIONS[$i]}"
done

capture_env "$LANE_DIR/env-after.txt" "after"
echo "lane done at $(date '+%Y-%m-%d %H:%M:%S %z')"
