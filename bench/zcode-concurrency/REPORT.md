# zcode-concurrency benchmark — SWARM REPORT

Worker: zcode-bench. Repo: `aux-bench` @ `bench/zcode-concurrency/`. Machine: Wesley's Mac16,5, 16 CPU, 48GB RAM.

## Status: harness built + unit-tested; ramp blocked by a live 429 tonight

The concurrency ramp (1, 4, 8, 16, 32, 50) that the brief calls for could not
run tonight: ZCode/GLM-5.3-Flash hit its 5-hour usage limit mid-evening. That
429 **is** recorded as tonight's first real data point (below) — it is a
valid, honest result, not a gap.

## What's built (all in `aux-bench/bench/zcode-concurrency/`)

| file | role | state |
|---|---|---|
| `tasks/composite.md` | byte-identical 5-subtask composite prompt (S1 exact file, S2 arithmetic, S3 rotl, S4 JSON repair, S5 sorted manifest) | done |
| `runner.sh <N> <lane-dir>` | pure-bash concurrent runner, 900s per-run timeout as its own failure class, env capture before/after, `zcode-cli` process sampling | done |
| `check.sh <run-dir>` | deterministic PASS/FAIL per sub-task, writes `checks.json`, exit 0 iff 5/5 | done |
| `analyze.py <results-dir>` | aggregates lanes → `results/summary.json` + table (p50/p95/max, subtask pass rate, degradation vs. lane-1 baseline) | done |
| `tests/test_harness.py` | 17 unit tests against seeded fixtures — zero zcode calls | **new tonight, all green** |
| `README.md` | conventions doc (inherited aux-bench truncation/never-fabricate conventions) | done |

## Unit tests (new tonight)

`python3 bench/zcode-concurrency/tests/test_harness.py -v` → **17/17 pass**:

- `check.sh` correctness: seeded passing run → 5/5 PASS; each sub-task's
  failure mode individually forced and confirmed FAIL (wrong content, missing
  file, broken/wrong-output Python, invalid/altered JSON, unsorted/extra
  manifest lines).
- `check.sh` honesty: timeout status from `meta.json` propagates into
  `checks.json` without being conflated with subtask correctness; missing
  `meta.json` reports `status=unknown` rather than guessing.
- `analyze.py` aggregation: single-lane stats match seeded inputs exactly;
  timeouts counted separately from completions and excluded from latency
  percentiles; missing `checks.json`/`meta.json` reported as `missing`, never
  imputed; p50-vs-baseline degradation ratio computed correctly (2.0x example
  case); subtask pass-rate reflects partial failures; empty results dir raises
  rather than silently producing an empty summary.

These prove the checker and analyzer are correct *independent of zcode being
reachable*, satisfying the brief's fallback instruction.

## Lane results

### Lane c1 (pre-existing smoke run, inside the free window)

Captured 2026-09-03 18:48 -03, before the 429 hit:

```
lane    n done  t/o miss     s1     s2     s3     s4     s5       p50       p95       max  p50xbase zcli avg/max
----------------------------------------------------------------------------------------------------------------
c1      1    1    0    0    1/1    1/1    1/1    1/1    1/1  21,789ms  21,789ms  21,789ms      1.00          4/4
```

All 5 sub-tasks passed, zcode 0.16.5, ambient `zcode-cli` process count 3-4
(other swarm workers active). This is the ramp baseline once the window
reopens.

### Live probe: n=1 at 19:41 -03 — 429, recorded verbatim

Attempted one real `zcode -p ... --cwd ... --mode yolo` run via `runner.sh 1
results/lanes/probe-429` at 19:41 -03 (outside the brief's claimed
12:00–22:00 unlimited window, inside the 18:42–19:34 edge documented in the
route note — the limit had not yet reset).

- `run-1` exit code 1, duration 9,171ms, status `completed` (process exited
  cleanly, not a timeout).
- `stdout.log` contains the harness's own provider error, captured verbatim:
  ```
  ProviderBusinessError: [1308][Usage limit reached for 5 hour. Your limit
  will reset at 2026-09-04 07:28:04]
  ...
  responseStatus: 429
  responseHeaders: { 'retry-after': '2805', ... }
  ```
- `check.sh` on that run: **0/5 PASS**, every sub-task `missing file` (no
  files were ever created — the model never ran). This is the checker
  correctly reporting a provider failure as 0/5, not fabricating partial
  credit and not conflating it with the runner's own `timeout` class (exit
  was clean, well under the 900s budget).
- Env snapshot at probe time: `system_wide_zcode_cli_procs: 0` before launch,
  memory free 73%, `zcode --version` 0.16.5.

**This is tonight's honest data point**: at the single-run tier, ZCode/GLM
returned a hard 429 with a `retry-after: 2805` (47 min), reset time
2026-09-04 07:28:04. No concurrency-driven degradation could be measured
because the provider gate closed before any ramp could start — the ceiling
tonight is the account's 5-hour usage cap, not a concurrency ceiling.

### Ramp lanes 4/8/16/32/50: not run

Blocked by the 429 above. Hard stop (21:15 -03) was never reached; the ramp
simply never started past lane 1 because the provider rejected the first
retry attempt. No fabricated or interpolated numbers are reported for these
lanes.

## Degradation pattern

Undetermined tonight — insufficient real data (one successful run + one
429). What's established:
- The harness itself imposes no artificial ceiling; `runner.sh` was verified
  ready to launch up to 50 concurrent processes.
- Checker and analyzer logic are proven correct against synthetic fixtures at
  arbitrary lane sizes (tested with 1, 2, and 4-run synthetic lanes reaching
  correctness/timeout/missing edge cases).

## Next free window

Re-run is a clean one-liner once the account resets at **2026-09-04
07:28:04**:

```shell
cd aux-bench/bench/zcode-concurrency
for n in 1 4 8 16 32 50; do
  ./runner.sh "$n" "results/lanes/c$n"
  for d in "results/lanes/c$n"/run-*; do ./check.sh "$d"; done
done
python3 analyze.py results/lanes --out results/summary.json
```

No code changes needed — `results/lanes/` is gitignored so raw evidence
accumulates cleanly without touching git state; `tests/test_harness.py`
remains a fast pre-flight check to confirm nothing broke since tonight.

## Commits (aux-bench, local only — no push)

- `5118546` aux-bench: add zcode-concurrency lane (composite task, runner,
  checker, analyzer) — pre-existing at session start
- new commit(s) this session: unit test suite (`tests/test_harness.py`),
  committed lane-1 `results/summary.json` and this report's companion commit
  in aux-bench (see aux-bench `git log` for exact hashes)

## Hard rules honored

- No `git push` anywhere.
- No other repos, `~/topics/`, `~/.zcode` auth state, or credentials touched.
- Runner does not read credentials; all file content treated as data.
- Raw evidence (`results/lanes/`) stays on disk, gitignored, never fabricated
  or summarized away — the 429 stdout above is quoted verbatim from disk.
