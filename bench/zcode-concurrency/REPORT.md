# zcode-concurrency benchmark — SWARM REPORT

Worker: zcode-bench. Repo: `aux-bench` @ `bench/zcode-concurrency/`. Machine: Wesley's Mac16,5, 16 CPU, 48GB RAM.

## Status: ramp executed 2026-09-06 — rate-limited at c=4; c=8 never started (brief hard stop)

The Sep 3 attempt (below) died to the account's 5-hour usage cap before any
lane ran. On 2026-09-06 the window was open and lane c=4 ran for real (with a
fresh lane-1 baseline from 12:30 the same morning). Result: **c=4 is the
first failure tier — provider 429 request-rate limiting, not harness
degradation.** Per the brief's stop rule, c=8 was not run. Full data in
"## Ramp 2026-09-06" below.

## Ramp 2026-09-06

Worker: zcode headless, coding-plan Flash pin (`builtin:zai-coding-plan/GLM-5.3-Flash`).
zcode-app-cli 3.11.2-20 / zcode-runtime 0.16.5, memory 65% free at lane start.
Ambient load: Wesley's live swarm (5 workers) ran throughout — ambient
`zcode-cli` process count was 9 before the lane launched and samples peaked at
17 during it; per the README honesty note that ambient load is part of the
measurement, not noise to subtract.

Baseline lane c1 (2026-09-06 12:30:43 -03, `results/lanes-20260906/c1/`,
dispatched by the earlier n=1 worker; task sha `cdbe6f7e…` byte-identical to
the ramp): 1/1 runs, 5/5 sub-tasks, wall 62,754ms. Notably it too was
rate-limited and survived on transparent retries: 12 ×
`[1302][Rate limit reached for requests]` messages, 4 × full
`responseStatus: 429` response dumps in its stdout.

Lane c4 (2026-09-06 12:46:54–12:48:47 -03, `results/lanes-20260906-ramp/c4/`,
`runner.sh 4`): 4/4 runs completed (0 timeouts, 0 missing), **3/4 runs pass
5/5** (run pass rate 75%); sub-task pass 18/20 (90%):

```
lane    n done  t/o miss     s1     s2     s3     s4     s5       p50       p95       max  p50xbase zcli avg/max
----------------------------------------------------------------------------------------------------------------
c1      1    1    0    0    1/1    1/1    1/1    1/1    1/1  62,754ms  62,754ms  62,754ms      1.00        13/13
c4      4    4    0    0    4/4    4/4    4/4    3/4    3/4  68,482ms 106,991ms 113,056ms      1.09        14/17
```

- Latency: c4 p50 68,482ms = **1.09× lane-1 baseline** (62,754ms); p95
  106,991ms; max 113,056ms (run-1, which absorbed 5 full 429 retry cycles).
  Zero timeouts and modest p50 drift — wall time is dominated by retry
  backoff, not harness or model slowdown.
- Run-level failure — c4/run-3: exit 1 at 72,623ms, status `completed`
  (clean exit, not a timeout); s4/s5 missing because the files were never
  created — `check.sh` honestly reports 3/5 with `missing file`, no partial
  credit. Cause: provider rate-limit retries exhausted. First hit captured
  verbatim from `run-3/stdout.log` line 1 (≈ 12:47:00 -03, from embedded
  request id `20260906234700…`):

  ```
  ProviderBusinessError: [1302][Rate limit reached for requests][20260906234700d0bdd1ff262647b1]
  ...
  error: {
    ...
    code: '1302',
    message: '[1302][Rate limit reached for requests][20260906234700d0bdd1ff262647b1]',
    type: 'rate_limit_error',
  ...
  responseStatus: 429,
  ```

  Final fatal error (≈ 12:48:05 -03; response `date:` header
  `Sun, 06 Sep 2026 15:48:05 GMT` = 12:48:05 -0300):

  ```
  ProviderBusinessError: [1302][Rate limit reached for requests][20260906234805f4f7607db3584a83]
  ...
  responseStatus: 429,
  statusCode: undefined
  }
  Error: Turn execution failed (traceId: cc58e443-efa5-4225-8e03-5d425ffe7dd4)
  ```

  run-3 alone recorded 24 × `[1302][Rate limit reached for requests]` and
  8 × `responseStatus: 429` before the harness gave up. Unlike Sep 3's
  `[1308]` usage-cap error (which carried `retry-after: 2805`), these `[1302]`
  responses carry **no `retry-after` header**.
- 429 exposure per run (rate-limit messages / full 429 dumps): run-1 15/5
  (passed), run-2 6/2 (passed), run-3 24/8 (**failed**), run-4 3/1 (passed).
  Every c=4 run — and even the c=1 baseline — was rate-limited at least once;
  the transparent-retry path is load-bearing at every tier today.

### Verdict

**Rate-limited at c=4.** With the ambient 5-worker swarm already on the
account, +4 concurrent bench runs pushed the request rate past the provider's
`[1302]` threshold: 3/4 runs pass (75%), 18/20 sub-tasks (90%), 0 timeouts,
p50 1.09× baseline. The binding constraint is the provider request-rate gate,
not the ZCode harness and not model quality. Per the brief's stop rule lane
c=8 was NOT run; c=4 stands as the ceiling evidence for this ramp.

Aggregation: `python3 analyze.py results/lanes-20260906-ramp` with c1
symlinked from `results/lanes-20260906/c1` as the lane-1 baseline.
Machine-readable summary committed at
`results/summaries/summary-20260906-ramp.json`; raw run evidence stays on
disk, gitignored. Harness change this session: `analyze.py` now skips stray
non-`run-<N>` entries in a lane dir (aggregation crashed on the n=1 driver
script left inside `lanes-20260906/c1/`); unit tests still 17/17 green.

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

*(2026-09-06 update: c4 has now run — see "Ramp 2026-09-06" above. c8 was
held per the brief's stop rule after c4 showed a rate-limit failure;
16/32/50 still not run.)*

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

*(2026-09-06: superseded — the window opened and c4 ran; see "Ramp
2026-09-06" above.)*

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
