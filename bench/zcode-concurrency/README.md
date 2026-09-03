# zcode-concurrency

Measures where the **ZCode harness itself** degrades under concurrency — not
model quality. Marketing says "up to 50 concurrent sessions"; this lane
measures at what concurrency real runs get slower or start failing.

Every run solves one byte-identical composite task (`tasks/composite.md`):
five deterministic sub-tasks (exact-content file, arithmetic value, runnable
`rotl`, JSON repair of a seeded trailing-comma break, exact sorted manifest),
all machine-checked by `check.sh` with zero LLM in the loop.

## Layout

| file | role |
|---|---|
| `tasks/composite.md` | the single prompt every run receives, byte-identical (sha256 recorded per run) |
| `runner.sh <N> <lane-dir>` | spawns N concurrent `zcode -p … --mode yolo` runs; seeds `in.json`; captures stdout, wall ms, exit code; enforces a 900s per-run timeout by killing the process tree |
| `check.sh <run-dir>` | deterministic PASS/FAIL per sub-task; writes `checks.json` |
| `analyze.py <results-dir>` | aggregates lanes → `results/summary.json` + table |

## Conventions (inherited from aux-bench)

- **Timeout is its own failure class**, never scored as model failure — same
  principle as scoring `truncated` in the model suites.
- Raw evidence under `results/lanes/` stays on disk, gitignored. Missing
  output is recorded as missing; nothing is retried or imputed.
- Each run's `meta.json` records the task sha256 so byte-identical prompts
  are verifiable after the fact.

## Running a ramp

```shell
cd bench/zcode-concurrency
for n in 1 4 8 16 32 50; do
  ./runner.sh "$n" "results/lanes/c$n"
  for d in "results/lanes/c$n"/run-*; do ./check.sh "$d"; done
done
python3 analyze.py results/lanes --out results/summary.json
```

Lanes are run sequentially; each lane's wall time is roughly its slowest run
(runs are concurrent, per-run budget 900s).

## Honesty constraints on the numbers

- `zcode-cli-count.log` records the **system-wide** `zcode-cli` process count
  during each lane: that includes the lane's own N processes *and* any
  unrelated sessions running on the machine. The committed results were taken
  during a multi-worker swarm night, so ambient load is part of the
  measurement and is reported alongside it.
- Latency is wall time on a shared machine — same caveat as the model suites
  in the repo README. Pass rate per sub-task is the primary signal;
  degradation shows up as rising p50/p95, timeouts, or sub-task failures.
